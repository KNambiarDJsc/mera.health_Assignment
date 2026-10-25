# PLAN

Written after reading the brief, `extract.py`, all gold files and looking at all 12 reports, before writing any code.

## What I expect to find (hypotheses, from reading the code + documents)

1. **Page coverage.** `pdftoppm -f 1 -l 1` renders page 1 only. report_11 is 2 pages; page 2 holds 26 of its 56 gold rows. Expect near-zero recall there.
2. **Resolution.** 60 DPI on an A4 page is ~500x700 px. Small digits/decimal points on the scanned PDFs (05, 06, 07) should get misread. Expect wrong values, not just missing ones.
3. **Fabrication by instruction.** The prompt says "if a reference range is missing, fill in the standard range". report_03 has three rows with no printed range (T3, T4, HbA1c); expect invented ranges. Same risk for report_12 (a prescription, no results at all: correct output is `[]`).
4. **Type coercion.** `value` is forced to `float`, so "Negative", "Present (+)", "2-3", "< 0.5" become `null`, and "2,29,000" becomes `null`. The schema allows strings; the code throws them away.
5. **Silent failure.** `parse()` returns `[]` on any error, so an API/JSON failure looks like "no tests".
6. **Gold noise.** Labels "made in a hurry". Already seen: report_01 Platelet Count gold = 304000, PDF prints 340000. I will not edit gold; I'll list disagreements and report scores both ways.

## Eval first

- One-to-one matching of predicted rows to gold rows on normalised test name (case/punctuation/whitespace), never on value.
- Per matched row: value correct (normalised string compare: strip spaces, Indian digit grouping, trailing-zero-safe numeric compare), unit correct, range correct.
- Headline metrics a doctor cares about: **wrong values** (matched row, wrong number) counted separately from **missing rows** and **fabricated rows** (prediction with no gold). Plus recall/precision on rows, and a "fully-correct row" rate.
- Unit tests that a wrong value / fabricated range moves the number down.
- Unlabelled reports (04, 07, 10, 12): manual row-by-row check against the image, documented in the README. No invented labels mixed into the score.

## Order of work

1. Get model access working (Gemini free tier as supplied; if blocked, document and substitute), measure the baseline unchanged, 3 runs to see variance.
2. Eval + tests.
3. Diagnose from baseline outputs; pick top 3 failure categories by count and clinical impact.
4. Fix one variable at a time (all pages -> DPI -> prompt: transcribe-don't-infer, keep strings -> structured output), re-score after each.
5. Record a change that did not help.
6. Cost/latency per report from token usage counts.

## What I don't plan to do (unless the evidence says otherwise)

RAG, fine-tuning, agent frameworks, OCR-engine pipelines (Docling/Paddle). 8 labelled reports can't justify them and none of the hypothesised failures is a knowledge problem. Keep `extract.py` small.
