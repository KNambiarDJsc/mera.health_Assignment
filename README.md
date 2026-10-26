# Lab report extraction: find out why it's bad, make it better, prove it

Take-home for the mera.health AI Engineer role. The starter extractor read Indian lab reports with **value accuracy 0.66** (and silently lost rows, mangled values and invented reference ranges). The replacement reaches **0.993**, and the one remaining miss is a mislabelled gold row. It is still a single model call, 127 lines, standard library only.

| Same model (`gemini-3.5-flash-lite`), 8 labelled reports, 125 gold rows | Baseline | Final |
|---|---|---|
| Value accuracy (missing row = wrong) | 0.659 | **0.993** (2 runs) |
| Full-row accuracy (value + unit + range) | 0.638 | **0.993** |
| Missing / extra rows | 46 / 22 | **0 / 0** |
| Reference ranges the lab never printed, invented | 3 | **0** |
| 4 unlabelled reports, 28 values checked by hand | 20 / 28 | **27 / 28** |
| Latency p50 / max | 3.0 s / 4.5 s | 2.8 s / 7.1 s |
| Cost per report (list price; actual spend $0) | $0.0020 | $0.0025 |

The one "wrong value" is the gold label: report_01 Platelet Count is labelled `304000`, the PDF prints `340000` (verified in the text layer). Against the corrected label the final scores 1.000. The unchanged starter on the larger `gemini-3.6-flash` scores 0.594, so the baseline's weakness isn't a small-model problem. Full numbers: [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md).

**Substitution, stated plainly:** the starter's `gemini-3.8-flash` exhausted its free quota (20 requests/day) during provider 503s. I measured the baseline on other models instead, so **every comparison is within one model**. 3.8-flash on the final pipeline is not measured.

## Run it

```bash
export GEMINI_API_KEY=...                      # only requirement: Python 3.10+, no packages, no Poppler
python extract.py reports/report_11.pdf        # schema-valid JSON on stdout; failures -> stderr + exit 1, nothing on stdout
GEMINI_MODEL=gemini-3.1-flash-lite python extract.py reports/report_08.jpg   # any Gemini model

python eval/score.py runs/g35lite/v0_baseline_r1 runs/g35lite/v3_r1     # the eval: baseline vs final, no API calls
python eval/score.py runs/g35lite/v3_r1 --errors                       # every wrong / missing / extra row
python eval/run.py extract.py runs/mine                                # re-run on all 12 reports (API calls; resumable)
pip install pytest jsonschema && python -m pytest -q                   # 27 offline tests
```
Scorer flags: `--corrected` (apply the documented gold fix), `--lenient` (also match renamed tests). Both are sensitivity checks; the headline is always official gold + strict names.

```
extract.py            the extractor (final)               experiments/   starter verbatim + each variant tried
eval/score.py         scorer, cost/latency table          runs/          every run's outputs, token usage, scores
eval/run.py           runner (latency, tokens, retries)   docs/          full experiment record
eval/manual_checks.json   hand-read values, unlabelled    PLAN.md        committed before any code, never edited
tests/                27 tests (scorer + extractor)       PROMPTS.md     the prompts, with why each is shaped that way
```

## Eval (task 2)

A row is correct when its name matches and **value, unit and range** equal gold after *format-only* normalisation (whitespace, case, µ/u, Indian digit grouping `2,29,000`, trailing zeros). `"< 0.5"` ≠ `0.5`; `"2-3"` ≠ `2.5`.
- **One-to-one matching on name, never on value**, so a duplicate can't satisfy two gold rows. Exact, then parenthetical variants (`MCV` ↔ `Mean Corpuscular Volume (MCV)`), then fuzzy on long tokens only (HDL never matches LDL).
- **Value accuracy over all gold rows**, so a dropped row hurts. Wrong values, decimal shifts, **fabricated ranges** and extra rows are reported separately; none can hide inside an F1.
- 13 scorer tests prove each of those failure types lowers the score. `gold/` is never edited.
- **Unlabelled 04 / 07 / 10 / 12:** I read every value off the document (04 from its text layer, 07 and 10 from zoomed crops) into `eval/manual_checks.json`, scored apart from gold. 12 is a prescription, so any row is a fabrication.
- **Would the number move if it got worse in a way that matters?** Yes: dropping a page, rounding `2-3`, or inventing a range each lower it. A renaming-only difference barely does under `--lenient`, which is how I know the 0.66 → 0.99 gap isn't naming (baseline stays ≤ 0.68 with generous matching).

## Diagnosis: three failures that matter (task 3)

| # | Report / row | Baseline did | Document says | Root cause |
|---|---|---|---|---|
| 1 | report_11, all of page 2 (e.g. `Urea 42 mg/dL`) | 30 of 56 rows absent | 56 rows over 2 pages | `pdftoppm -f 1 -l 1`: **page 2 is never rendered**; output looks complete. 21% of all gold rows. |
| 2 | report_06 Leucocytes / CRP / Sugar | `2.5`, `0.5`, row dropped | `2-3`, `< 0.5`, `Present (+)` | Prompt says "value must be a number" and `clean()` calls `float()`, though the schema allows strings. Intervals become invented midpoints, inequalities vanish, glycosuria disappears. |
| 3 | report_03 T3, T4, Glycated Hb | ranges `80 - 200`, `4.5 - 12.0`, `4.0 - 5.6 %` | no range printed | The prompt **orders** "fill in the standard reference range". The derived `status` then flags HbA1c 6.0 *high* against a range the lab never wrote. |

## Fix (task 4)

One call, different contract. No framework, no extra stages.
1. **Whole PDF sent natively** (all pages + text layer). vs rendered pages: same accuracy, p50 **2.9 s vs 8.9 s**, 41% fewer input tokens, no Poppler.
2. **Transcribe, never interpret:** names and values verbatim as strings, units lifted out of result/range cells, `null` when no range is printed, no model-derived `status` ([PROMPTS.md](PROMPTS.md)).
3. **Provider-enforced JSON schema; failures are loud.** Truncation, malformed JSON and HTTP errors raise (exit 1, empty stdout). 429/5xx retried with backoff. The baseline returned `[]` on any failure, so an outage looked like a clean report.
4. **Per-row `legibility` flag** (`clear`/`obscured`, an extra schema-valid property). On report_07 a pen ellipse crosses Serum Globulin `3.1`; every Gemini model read `3.3` (= Total Protein − Albumin, i.e. computed, not read). The flag marks exactly the two rows under the ellipse and **0 of the other 164**, so the error goes to a human instead of passing silently. It does not fix the misread.
5. **Default model `gemini-3.5-flash-lite`**: identical accuracy to 3.1-flash-lite, no thinking tokens (3.6-flash spent two thirds of its output budget on them).

## What didn't help (task 5)

| Tried | Expected | Measured | Verdict |
|---|---|---|---|
| **200 DPI instead of 60** (my own PLAN, H2) | fewer misread digits | **identical**: 0.992 at both, identical input tokens (Gemini bills images at a flat token count) | Wrong hypothesis; the cause was page 1 only. Replaced by native PDF. |
| **Docling** (layout + tables + OCR), two ways | better table association than the model | rules-only (no LLM): full-row **0.920**; Docling → same LLM: **0.949**; final **0.993**. 32–39 s per report vs 2.8 s. On the skewed photo (report_09) Docling put every reference range one row off; the LLM copied it faithfully | Rejected: a perception stage whose errors the model can't see past. |
| `ultra_high` media resolution; prompt rule "never derive a value" | read the occluded `3.1` | still `3.3` (1 call each, n = 1) | Dropped; kept the flag. |

## RAG, fine-tuning, agents (task 6)

**RAG: no.** Every measured failure was perception or instruction (page not sent, type coerced, range invented), never missing knowledge. The one place outside knowledge entered the pipeline, "standard" reference ranges, *was* the bug: a patient's range must come from their own report. Retrieval could later help map `TG` → a LOINC code, as a separate step that never touches the transcribed value.

**Fine-tuning: no.** 125 labelled rows (one of them wrong) is not a training set, and the pipeline already gets all of them after correction. The residual failure is one occluded digit in 12 documents, and the same prompt transferred unchanged across four models; a fine-tune pins us to one. Revisit once the review queue yields thousands of human-corrected rows from hard photos and handwriting.

**Agents: not earned.** One call is perfect on the labelled set and the residual error isn't fixed by looking again (2× resolution gave the same wrong `3.3`). A second model step adds latency, cost and new errors to 100% of reports to address ~1% of rows. The pipeline that earns its keep is plain Python: one call, then route `obscured` rows (2 / 166) to a human. A verifier, if ever added, should run only on flagged rows and be measured first.

## At 10,000 reports/day

≈ **$25/day** at list price (≈ $12 on the Batch API) versus ≈ $90/day for the baseline's configuration, which also drops pages. That is ~7 requests/min, ~0.3 concurrent at p50 and ~3 at a 10× peak, so rate limits aren't the constraint; **provider availability is** (we lost an hour to 503s and a day's free quota to the retries). Production needs a queue with backoff and a fallback model (3.1-flash-lite gave identical results). **Privacy:** free-tier data may be used by the provider, so real patient reports need a paid tier or Vertex with a data-processing agreement (DPDP Act); open-weights Gemma 4 31B also scored 0.993 as the on-prem path, at 62 s/report on a GPU host, but it misread `µIU/mL` as `pIU/mL`, so add a unit whitelist first. Detail in [docs/EXPERIMENTS.md §6](docs/EXPERIMENTS.md).

## Decision log

| Moment | What happened |
|---|---|
| Gold audit | Compared every digital-PDF gold row against `pdftotext`, every photo row by eye. One error (report_01 platelets). Kept official gold and reported both numbers. |
| Name matching | The baseline renames tests, so strict matching alone would exaggerate the gain. I added `--lenient` as a sensitivity check rather than loosening the headline. |
| My hypothesis was wrong | PLAN predicted low DPI would misread digits. Measured: no effect. Reported it instead of keeping 200 DPI as a "fix". |
| Quota: user overruled the plan | 3.8-flash's 20/day was burned by 503 retries. Offered billing; **the user chose free-tier substitution**. Hence within-model comparisons, a runner that stops on 429, and the 3.8-flash gap stated above. |
| Docling: user overruled the agent | The agent rejected Docling by reasoning alone. **The user asked for it to be measured.** It was, and the measurement confirmed the rejection with numbers and exposed a failure mode (shifted ranges) that reasoning had not predicted. |
| report_07 | All models agreed on `3.3`. A 300 DPI crop shows `3.1`. Logged as a manual check and an unfixed limitation, not tuned away. |
| Verified before publishing | Recomputed every README figure from the `score.json` files; fixed three mismatches (28 vs 38 manual values, a rounded cost, a stale line count). Scanned the repo and full git history for API keys: none. |

## Limitations

Eight labelled reports cannot rank models that all score ≥ 0.99; the default model is chosen on cost and latency at equal measured accuracy. Handwritten values, stamps, folds and multi-patient pages are untested. 3.8-flash on the final pipeline and repeat runs on other models are pending quota, not assumed. The starter kit's `brief.md`, `reports/`, `gold/` and `schema.json` belong to mera.health and are included for reproducibility.
