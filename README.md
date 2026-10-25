# Lab report extraction: made better, with evidence

**Setup changed:** no Python packages and **no Poppler**. Python 3.10+ and `GEMINI_API_KEY` only. The default model is now `gemini-3.5-flash-lite` (override with `GEMINI_MODEL`).

```bash
python extract.py reports/report_01.pdf                      # schema-valid JSON on stdout; errors -> stderr, exit 1
python eval/score.py runs/g35lite/v0_baseline_r1 runs/g35lite/v3_r1 runs/g35lite/v3_r2   # the eval (no API calls)
python eval/run.py extract.py runs/<dir>                       # regenerate outputs (API calls)
pip install pytest jsonschema && python -m pytest -q          # 27 offline tests
```
Score flags: `--errors` (every wrong/missing/extra row), `--corrected` (gold sensitivity), `--lenient` (name sensitivity). The baseline is kept verbatim as `experiments/v0_baseline.py`. Prompts and the reasoning behind them are in [PROMPTS.md](PROMPTS.md). The original plan is [PLAN.md](PLAN.md), unedited.

## Results (8 labelled reports, 125 gold rows)

| Same model, `gemini-3.5-flash-lite` | value acc. | full-row acc. | recall | precision | wrong values | fabricated ranges | missing / extra rows | p50 / max latency | $/report* |
|---|---|---|---|---|---|---|---|---|---|
| Baseline (starter code, unchanged) | 0.659 | 0.638 | 0.667 | 0.807 | 1 | 3 | 46 / 22 | 3.0 s / 4.5 s | 0.0020 |
| **Final, run 1** | **0.993** | **0.993** | 1.000 | 1.000 | 1** | 0 | 0 / 0 | 2.8 s / 7.1 s | 0.0025 |
| **Final, run 2** | **0.993** | **0.993** | 1.000 | 1.000 | 1** | 0 | 0 / 0 | 2.9 s / 6.8 s | 0.0025 |
| Baseline on `gemini-3.6-flash` | 0.594 | 0.580 | 0.609 | 0.771 | 2 | 2 | 54 / 25 | 13 s / 21 s | 0.0090 |
| Final on `gemini-3.1-flash-lite` | 0.993 | 0.993 | 1.000 | 1.000 | 1** | 0 | 0 / 0 | 12.6 s† / 43 s† | 0.0016 |

\*Paid-tier list price × measured tokens; actual spend was $0 (free tier). Output tokens include thinking: 3.6-flash spent 2/3 of its output on thinking, lite models spend none. \*\*The only "wrong value" is a **gold-label error**: report_01 Platelet Count is printed as 340000 and labelled 304000 (checked against the text layer). With that one correction (`--corrected`), the final scores 1.000 on every metric and the baselines 0.667 / 0.601. †Provider 503 bursts during the run.

**Is it renaming or real?** With `--lenient`, renamed tests are matched too, and the baseline only reaches 0.681 (3.5-lite) and 0.630 (3.6). The gap isn't naming. **Unlabelled reports**, checked by hand (below): final 27/28 values correct in both runs (the miss is report_07, below), baseline 20/28. Baseline's renaming hides rows from the matcher, so that's a lower bound for it.

## Eval design (task 2)
- **Correct row** = test name matched, and value, unit and range all equal after *format-only* normalisation: whitespace, case, µ/u, Indian digit grouping, trailing zeros. `"<0.5"` ≠ `"0.5"` and `"2-3"` ≠ `2.5`.
- **Matching is on name only, one-to-one**, never on value, so a duplicate can't satisfy two gold rows. Exact name, then parenthetical variants ("MCV" ↔ "Mean Corpuscular Volume (MCV)"), then fuzzy matching on long tokens only, so HDL never matches LDL.
- **Headline = value accuracy over all gold rows**: a missing row is a failure. Reported separately so they can't hide in an F1: **wrong values**, decimal shifts, **fabricated ranges** (gold null, prediction not), extra rows.
- 13 tests prove that a wrong value, a decimal shift, a fabricated range, a duplicate and a missing row each lower the score. `gold/` is never edited.
- **Unlabelled 04/07/10/12:** I read every value myself (04 from its text layer, 07 and 10 from zoomed crops) into `eval/manual_checks.json`. These are scored separately and never merged with gold. report_12 is a prescription, so any row is a fabrication.

## Diagnosis: the three failures that matter (task 3)

| # | Where | Baseline output | Printed | Root cause (earliest point of failure) |
|---|---|---|---|---|
| 1 | report_11, all of page 2, e.g. "Urea 42 mg/dL" | absent: 30 of 56 rows | 56 rows on 2 pages | `pdftoppm -f 1 -l 1`: **only page 1 is ever rendered**. The model never sees page 2, and the output looks complete. 26 rows = 21% of all gold. |
| 2 | report_06 urine panel | Leucocytes `2.5`, Erythrocytes `1.5`, CRP `0.5`; Colour, Clarity, Albumin, **Sugar "Present (+)"** and Ketones dropped | `2-3`, `1-2`, `< 0.5`, qualitative results | Prompt says **"value must be a number"** and `clean()` applies `float()`, though the schema allows strings. The model complies by inventing midpoints, dropping the inequality, or dropping the row. An abnormal finding (glycosuria) silently disappears. |
| 3 | report_03 T3, T4, Glycated Hb | ranges "80 - 200", "4.5 - 12.0", "4.0 - 5.6 %" | no range printed | The prompt **instructs** the model to "fill in the standard reference range", and the derived `status` then marks HbA1c 6.0 high against a range the lab never printed. |

Also present: renaming (about a quarter of rows, so outputs can't be traced to the page), `parse()` returning `[]` on any error (an API failure looks like a clean report), and no retries (3.8-flash returned 503 for about an hour).

## Fix (task 4): one call, different contract (`extract.py`, 125 lines vs 120)
1. **Send the whole PDF natively**: every page, plus the text layer when present. Native vs rendered pages, same model: identical accuracy, p50 **2.9 s vs 8.9 s**, ~40% fewer input tokens, and Poppler is no longer needed.
2. **Transcribe, don't interpret.** Names and values verbatim as strings, units moved out of result/range cells, `null` when no range is printed, model-derived `status` dropped.
3. **Provider-enforced JSON schema**. Truncation, malformed output and HTTP errors **raise** (exit 1, nothing on stdout). 429/5xx are retried with backoff.
4. **Per-row `legibility` flag** (extra property, schema-valid). On report_07 a pen ellipse crosses "3.1" (Serum Globulin). **Every model and setting read 3.3** except one 200 DPI run, and 3.3 is exactly Total Protein − Albumin. The flag marked exactly the 2 rows under the ellipse and **0 of the other 164 rows**, so the error goes to review instead of passing silently.
5. **Model → `gemini-3.5-flash-lite`**: identical results to 3.1-flash-lite on all 12 reports, and the partial 3.6-flash run of the previous version (reports 01–04) matched too. It has no thinking cost. 3.8-flash couldn't be re-run on the final pipeline because its free quota (20/day) is used up. That comparison is pending, not assumed.

## Didn't help (task 5)
| Hypothesis | Experiment (same model) | Result | Decision |
|---|---|---|---|
| 60 DPI loses digits (my PLAN, H2) | final prompt at 60 vs 200 DPI, 8 PDFs, 3.1-flash-lite | **Identical** on all 6 labelled PDFs, and **identical input tokens** (1,534): Gemini bills an image at a fixed token count, and 60 DPI was still legible. One unlabelled hint: the 200 DPI run alone read report_07's obscured "3.1". | Resolution wasn't the cause. Moved to native PDF, which removes the knob entirely. |
| A stronger read fixes the obscured digit | `ultra_high` media resolution (2× image tokens); prompt rule "never derive a value from other rows" | Both still 3.3 (1 call each, n=1) | Dropped both, kept the flag. |

## Three answers (task 6)
**RAG? No.** Every measured failure was a perception or instruction failure (pages not sent, types coerced, ranges invented), not missing knowledge. The one place outside knowledge entered the pipeline, "standard" reference ranges, *was* the bug: a patient's range has to come from their own report. Retrieval could later help downstream canonicalisation (mapping "TG" to a LOINC code), as a separate step that never touches the transcribed value.

**Fine-tuning? No.** 125 labelled rows with a known label error is not training data, and the final pipeline already gets all 125 right after correction. The residual failure (a pen mark over a digit) appears once in 12 documents. Prompt and schema changes transferred unchanged across 4 models; a fine-tune locks us to one. It becomes worth revisiting once the review queue produces thousands of corrected rows from hard photos and handwriting.

**Multi-step agent? Not earned.** One call is perfect on the labelled set, and the residual error isn't fixed by looking again: re-reading at 2× resolution gave the same 3.3. A second model step would add latency, cost and its own errors to 100% of reports to address about 1% of rows. The pipeline that earns its place is plain Python: one call, then route `legibility == "obscured"` rows (2/166) to a human. If a verifier is ever added, it should run only on flagged rows and be measured first. LangGraph adds nothing here.

## 10,000 reports/day
About $25/day at paid list price (**$0.0025/report**; Batch API halves that for non-urgent work), versus about $90/day for the baseline's flash config ($0.009/report measured on 3.6-flash, same price as 3.8-flash), which also drops pages. Volume is ~7 requests/min on average, so even a 10× peak is a small fraction of paid-tier rate limits. The real risks we hit: **provider overload** (3.8-flash returned 503 for about an hour, 3.1-lite in bursts), so production needs a queue with backoff and a fallback model. 3.1-flash-lite gave identical results and is the obvious fallback. **Privacy**: free-tier data may be used by the provider, so real patient reports need a paid tier or Vertex with data-processing terms (and DPDP compliance). An open-weights Gemma 4 run is in `runs/gemma4` as an on-prem data point.

## Decision log (what I checked by hand, where I changed course)
| Moment | Decision and evidence |
|---|---|
| Name matching | The baseline expands "MCV". I chose parenthetical/fuzzy matching so the baseline isn't penalised, and added `--lenient` as a sensitivity check instead of loosening the headline. |
| Gold audit | Compared every digital-PDF gold row with `pdftotext` and every image row by eye. One error (report_01 platelets). Kept official, reported both. |
| My own hypothesis was wrong | PLAN predicted DPI would matter. Measured: it didn't on labelled data. Said so; didn't keep 200 DPI as a "fix". |
| report_07 | Models agreed on 3.3. A 300 DPI crop shows 3.1. Recorded as a manual check and an unfixed limitation, not tuned away. |
| Quota | 3.8-flash's 20/day was burned by 503 retries. **User chose the free substitution** over enabling billing. Every comparison is within one model, and the runner now stops on 429 instead of retrying. |
| Model default | Switched to 3.5-flash-lite on equal measured accuracy. 3.8-flash on the final pipeline is not yet measured. |
| API key | It was pasted into the agent chat once. **Rotate it before sharing the transcript.** It is in no file in this repo. |
| _(Karthik: add where you overruled the agent)_ | |

**Limitations:** 8 labelled reports can't separate models that are all ≥0.99, so the model choice rests on cost and latency at equal measured accuracy. Unseen layouts (handwritten values, multi-patient pages) are untested. Pending runs: `runs/g36/v2_r1` (4/12 done) and 3.8-flash on the final pipeline.
