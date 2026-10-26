# Experiment record

Everything behind the README's claims. Every row below maps to a directory under `runs/`, each holding per-report outputs, `meta.json` (latency, token usage, failed attempts) and `score*.json`. Regenerate any table with `python eval/score.py <run dirs>` (no API calls).

## 1. Method and caveats

- **Corpus:** 12 reports: 8 PDFs (digital and scanned; report_11 has two pages) and 4 JPG phone photos. 8 labelled (125 gold rows), 4 unlabelled (04, 07, 10, 12).
- **Headline metric:** `value_acc` = rows whose matched prediction has the correct value, over **all** gold rows (a missing row counts as wrong). `row_acc` additionally requires unit and reference range to match.
- **Provider quota shaped the study.** The free tier allows **20 requests/day per model**. `gemini-3.8-flash` (the starter default) returned 503 for about an hour, and the retries burned its daily quota. `gemini-3.6-flash` then ran out mid-study; `gemini-3.5-flash` has no free quota on this key. The user chose the free route over enabling billing. Consequence: **every before/after comparison is within a single model**, and 3.8-flash on the final pipeline is **not measured**.
- **Prices** (paid tier, ai.google.dev pricing page, read 2026-10-26): 3.8/3.6-flash $0.75 in / $3.75 out per 1M tokens (doubles on 2027-01-01); 3.5-flash-lite $0.30 / $2.50; 3.1-flash-lite $0.25 / $1.50. Output includes thinking tokens. **Actual spend: $0.**
- **n is small.** Eight reports cannot separate models that all score ≥ 0.99. Treat 0.993 vs 0.993 as a tie, not a ranking.
- **One gold error** (report_01 Platelet Count: label `304000`, document prints `340000`, confirmed in the PDF text layer). Official scores keep the label; `--corrected` shows the sensitivity.

## 2. Run index

| Directory | Model | Pipeline | Coverage | Notes |
|---|---|---|---|---|
| `g36/v0_baseline_r1` | gemini-3.6-flash | starter, unchanged | 12/12 | substituted baseline (3.8-flash blocked) |
| `g35lite/v0_baseline_r1` | gemini-3.5-flash-lite | starter, unchanged | 12/12 | same-model baseline for the headline |
| `g35lite/v0_baseline_r2` | 〃 | starter | 1/12 | stopped by 429; unused |
| `g35lite/v2_image`, `v2_native` | 〃 | v2, rendered pages vs native PDF | 8 PDFs | input-format experiment |
| `g35lite/v3_r1`, `v3_r2` | 〃 | **final** | 12/12 ×2 | headline |
| `g31lite/v2_dpi200`, `v2_dpi60` | gemini-3.1-flash-lite | v2 at 200 vs 60 DPI | 8 PDFs | DPI experiment |
| `g31lite/v3_r1` | 〃 | final | 12/12 | cross-model check |
| `gemma4/v2_r1` | gemma-4-31b-it | v2 (image mode) | 12/12 | open-weights check |
| `docling/rules_r1` | none (Docling + header rules) | Docling 2.142.1, CPU | 12/12 | experiment B |
| `docling/llm_r1` | gemini-3.5-flash-lite | Docling markdown → LLM | 12/12 | experiment C |
| `g36/v2_r1` | gemini-3.6-flash | v2 | 4/12 | stopped by 429; only 01–03 are clean, unused |
| `g38/*` | gemini-3.8-flash | baseline / v1 / v2 | 1–3 reports each | stopped by 429/503; kept for the record, **no claim rests on them** |
| `g35/` | gemini-3.5-flash | n/a | 0 | 429 on first call (no free quota) |

`v0` = starter code; `v1` = starter prompt, all pages, DPI varied; `v2` = new prompt + schema, images; `v3` = final (native PDF + legibility flag). Frozen copies: `experiments/v0_baseline.py`, `v1_pages_dpi.py`, `v2_image.py`.

## 3. Headline results

| Run | value_acc | row_acc | recall | precision | wrong values | fab. ranges | missing / extra | p50 / max s | $/report |
|---|---|---|---|---|---|---|---|---|---|
| g35lite baseline | 0.659 | 0.638 | 0.667 | 0.807 | 1 | 3 | 46 / 22 | 3.0 / 4.5 | 0.0020 |
| g35lite final r1 | 0.993 | 0.993 | 1.000 | 1.000 | 1 | 0 | 0 / 0 | 2.8 / 7.1 | 0.0025 |
| g35lite final r2 | 0.993 | 0.993 | 1.000 | 1.000 | 1 | 0 | 0 / 0 | 2.9 / 6.8 | 0.0025 |
| g36 baseline | 0.594 | 0.580 | 0.609 | 0.771 | 2 | 2 | 54 / 25 | 13 / 21 | 0.0090 |
| g31lite final | 0.993 | 0.993 | 1.000 | 1.000 | 1 | 0 | 0 / 0 | 12.6† / 43† | 0.0016 |
| gemma4 (v2 prompt) | 0.993 | 0.986 | 1.000 | 1.000 | 1 | 0 | 0 / 0 | 62 / 169 | self-host |
| docling rules (no LLM) | 0.964 | 0.920 | 0.971 | 1.000 | 1 | 0 | 4 / 0 | 32 / 45 | 0 |
| docling → LLM | 0.993 | 0.949 | 1.000 | 1.000 | 1 | 0 | 0 / 0 | 39 / 61 | 0.0020 |

†503 bursts from the provider. The single "wrong value" in every row is the report_01 gold error.

**Sensitivity of the baseline to scoring choices** (so the gain can't be an artefact of my matcher):

| Baseline run | strict names, official gold | `--corrected` | `--lenient` names |
|---|---|---|---|
| g35lite | 0.659 | 0.667 | 0.681 |
| g36 | 0.594 | 0.601 | 0.630 |

Even matching renamed tests generously, the baseline stays below 0.70, so the gap is lost rows and destroyed values, not naming.

**Manual checks on the 4 unlabelled reports** (28 values read by hand into `eval/manual_checks.json`; scored apart from gold): baseline g35lite 20/28, g36 18/28; final 27/28 in both runs (miss = report_07 Serum Globulin). report_12 is a prescription: every system returned 0 rows, which is correct.

## 4. Root causes in detail

Per-report `value_acc` for the baseline on gemini-3.6-flash, strict names: 01 0.93 · 02 0.88 · 03 0.62 · 05 1.00 · 06 0.00 · 08 0.00 · 09 0.86 · 11 0.44.

1. **Page coverage (report_11).** `pdftoppm -f 1 -l 1` renders only page 1. All 26 page-2 rows (Renal, Thyroid, Glycaemic, Vitamins, Urinalysis) are absent from the output and nothing signals it. Page 1 alone gave 0.44; the final gets 54/54 rows.
2. **Forced numerics (report_06).** `"value must be a number"` plus `float()` in `clean()`:
   - `2-3` → `2.5`, `1-2` → `1.5` (invented midpoints: an interval became a measurement)
   - `< 0.5` → `0.5` (the inequality is the clinical content)
   - `Present (+)` / `Negative` / `Dark Yellow` rows dropped or nulled. Glycosuria disappears.
   The schema permits strings; the code threw that away.
3. **Instructed fabrication (report_03).** "If a reference range is missing … fill in the standard reference range" produced `80 - 200 ng/dL` (T3), `4.5 - 12.0 µg/dL` (T4) and `4.0 - 5.6 %` (HbA1c) where the lab printed nothing. The derived `status` then marked HbA1c 6.0 as high against a range the lab never wrote.

Secondary: renaming ("TG" → "Triglycerides", ~25% of rows; makes outputs un-auditable against the page), `parse()` returning `[]` on any failure (an outage looks like a clean report), no retry on 429/5xx, and a 60-DPI render (not a cause; see §5).

## 5. Experiments

### 5.1 DPI: hypothesis rejected
PLAN predicted 60 DPI would misread digits. Same final prompt, `gemini-3.1-flash-lite`, 8 PDFs: **0.992 at both 60 and 200 DPI**, identical input tokens (1,534 — Gemini bills an image at a fixed token count, so resolution is free but also changes nothing here). Only an unlabelled hint differed: the 200-DPI run alone read report_07's obscured digit correctly (once; not repeatable evidence).

### 5.2 Native PDF vs rendered pages: adopted
`gemini-3.5-flash-lite`, 8 PDFs, same prompt: identical accuracy (0.992), **p50 2.9 s vs 8.9 s**, mean input tokens 904 vs 1,534 (-41%). Native input also removes the Poppler dependency and gives the model the text layer when there is one. For JPG photos the image is sent as-is.

### 5.3 The unfixed error: report_07 Serum Globulin
A pen ellipse crosses the value. A 300-DPI crop reads **3.1**; every Gemini model and setting read **3.3**, which equals Total Protein (7.7) − Albumin (4.4): the model computed the value instead of reading it. Tried and rejected (1 call each, n = 1): `ultra_high` media resolution (2,184 image tokens vs ~1,120), and a prompt rule "never derive a value from other rows". What worked as mitigation: a per-row `legibility: clear|obscured` field. It flagged exactly Albumin and Globulin (the two rows under the ellipse) and **0 of the other 164 rows** in both lite models. Gemma 4 read 3.1 correctly but turned `µIU/mL` into `pIU/mL` on report_03, a 10⁶ unit error. Lesson: pair any value check with a unit whitelist.

### 5.4 Docling: considered, measured, rejected
Docling 2.142.1 (CPU, EasyOCR, layout + TableFormer), isolated in its own venv (1.2 GB incl. PyTorch).

| | rules (no LLM) | Docling → LLM | final |
|---|---|---|---|
| value / row accuracy | 0.964 / 0.920 | 0.993 / 0.949 | 0.993 / 0.993 |
| unit / range acc. (matched) | 0.978 / 0.955 | 0.978 / 0.957 | 1.000 / 1.000 |
| p50 latency | 32 s | 39 s | 2.8 s |

- **Table structure was good on clean layouts and side-by-side tables** (report_06's two-column tables came out intact). That is Docling's strength and it is real.
- **On the skewed phone photo (report_09) it misaligned columns:** from Neutrophils down, every reference range sits one row off (Basophils received `2 - 10`; printed `0 - 2`), Neutrophils lost its unit and range, and the Platelets row split across two. Values stayed right, so `value_acc` didn't move, but `row_acc` dropped. The downstream LLM, seeing only text, **copied the misalignment faithfully**.
- report_07's obscured value became the OCR string `TL 3.`; report_10's TSH row merged into its header cell.
- The `rules` path missed report_06's CRP and ESR rows even though Docling's markdown contains both tables. The cause is in my dataframe-to-schema mapping, not diagnosed further, and I did not patch the rules against the answers (that would be tuning on the test set). The `llm` variant, fed the same markdown, got them.
- **Verdict:** a perception stage whose errors the model cannot see past, for 11–14× the latency. Where it could still earn a place: fully offline processing where no model API is allowed.

### 5.5 Not done, on purpose
- **Verification / second-pass agent:** no residual error is fixed by a second look (2× resolution → same wrong 3.3).
- **OCR engines (Tesseract is on this machine; PaddleOCR/RapidOCR not installed):** Docling already showed that adding an OCR stage on these photos adds errors. Not run.
- **Few-shot examples from the gold set:** would leak the test set into the prompt and make the eval unfalsifiable.
- **3.8-flash on the final pipeline:** quota. Pending, not assumed.

## 6. Scaling to 10,000 reports/day

| | final (3.5-flash-lite) | baseline config (3.6/3.8-flash) |
|---|---|---|
| tokens / report (in + out) | 1,105 + 862 | 1,242 + 2,153 (thinking included) |
| $ / report | 0.0025 | 0.0090 |
| $ / day | **≈ $25** (≈ $12 on Batch API, 50% off) | ≈ $90, and drops page 2+ |

- **Output tokens are ~86% of cost** (862 × $2.50 vs 1,105 × $0.30 per M). The main lever is the Batch API for non-urgent reports; the input side is already cheap.
- **Load:** 10,000/day ≈ 7 requests/min; at p50 2.8 s that is ~0.3 concurrent requests on average, ~3 at a 10× peak. Paid-tier rate limits are not the constraint; **provider availability is** (the 503 hour we hit). Production needs a queue with backoff, an idempotent retry, and a fallback model: 3.1-flash-lite produced identical results here.
- **Fallback rate to humans:** 2 of 166 rows (1.2%) flagged on this sample; one of those is a real misread. Expect that to grow on handwriting and poor photos; measure it as the review-queue metric.
- **Privacy:** reports are PHI-like. The free tier may use data for product improvement; production requires a paid tier or Vertex AI with a data-processing agreement, and Indian DPDP Act compliance. Gemma 4 31B (0.993 here) is the on-prem path: 62 s/report and a GPU host, plus a unit whitelist.
- **Cold start:** none for the API path. Docling's model load plus 30–45 s/page CPU conversion is why it was not chosen for throughput.

## 7. What would make this more convincing

1. Fix the quota constraint (billing, or wait for reset) and run 3.8-flash and 3.6-flash on the final pipeline ×3.
2. A larger labelled set, especially photos with handwriting, stamps and folds; the current set has one occluded digit.
3. Re-label the 8 gold files with a second reader; at least one gold row is wrong, so others may be.
4. A unit whitelist and a plausibility check (value vs printed range, with the report's own range only) as a post-filter that flags, never edits.
