# Prompts sent to the model

Both versions send one `generateContent` request per report: the document (inline), then the prompt text. Temperature 0.

## Final (`extract.py`)

```
You are transcribing a medical lab report into structured data. The output becomes the patient's record, so copy exactly what is printed. Never correct, standardise or fill in anything.
```
Frames the task as **transcription, not interpretation**. The baseline's "expert" framing invited the model to apply knowledge (standard names, standard ranges).

```
Return one entry per printed result row, in printed order, across every page.
```
"Across every page" because multi-page reports were the largest single loss; order matches `schema.json`'s "in the order printed".

```
- test_name: exactly as printed. Do not expand abbreviations or rename.
```
The baseline renamed ~25% of rows ("TG" -> "Triglycerides"), so the output couldn't be traced back to the page.

```
- value: the result exactly as printed, as a string, with its qualifiers and formatting: "< 0.5", "2-3", "Negative", "Present (+)", "2,29,000". Do not round, convert or recompute.
```
The examples are the value *shapes* the baseline destroyed (inequality, interval, qualitative, Indian digit grouping). They're formats, not values from any one report.

```
- unit: the unit printed for that row. If it is printed inside the result cell ("179 ng/dL") or the range cell ("0 - 5 /hpf"), put it here instead. null if none is printed.
- reference_range: the range exactly as printed for that row, without the unit. null if that row has no printed range. Never supply a range from your own knowledge.
```
Two layouts in the samples put units in the wrong column. "Never supply a range" reverses the baseline instruction that caused the invented ranges.

```
- legibility: "obscured" if anything (pen marks, stains, folds, glare, blur) overlaps or degrades that row's printed value, else "clear".
```
The one failure we could not fix (a pen mark over a digit) can at least be detected; this flag routes those rows to human review.

```
Include only rows that report a result for this patient. Skip section headings, column headers, methods, comments, signatures, patient details and handwritten notes. Tables may sit side by side: read each table across its own columns.
If the document contains no lab results (for example a prescription or a list of tests advised), return an empty list.
If a value cannot be read with confidence, use null rather than guessing.
```
Scope rules, from documents in the sample set: side-by-side tables (06, 10), a prescription with vitals (12), handwritten notes (07). A null value is safer than a plausible wrong one.

**Structured output:** `responseMimeType: application/json` plus a `responseSchema` (all fields required; value/unit/range nullable strings; legibility an enum). The provider enforces the shape, so there's no regex parsing, and the parse step raises on truncation or malformed output instead of returning `[]`.

## Baseline (`experiments/v0_baseline.py`, unchanged starter)

```
You are an expert at reading medical lab reports.
Look at this lab report and extract every test result from it.
Return JSON in exactly this format:
{"tests": [{"test_name": "...", "value": 0.0, "unit": "...", "reference_range": "...", "status": "normal"}]}
Rules:
- Use the standard medical name for each test.
- value must be a number.
- If a reference range is missing from the report, fill in the standard reference range for that test.
- status is "normal", "high" or "low", based on the value and the reference range.
- Be thorough. Do not miss any tests.
```
Three of its five rules directly cause measured errors: renaming, numeric coercion and invented ranges. The derived `status` then propagates the invented range: HbA1c 6.0 against an invented "4.0 - 5.6" is labelled high.

## Prompts tried and not kept

| Change | Tested on | Result |
|---|---|---|
| Added "Pen marks may overlap printed values: read the printed characters themselves. Never derive a value from other rows or from what it ought to be." | report_07, 3.5-flash-lite, 1 call | Still read 3.1 as 3.3. Dropped: no evidence it helps. |
| Part-level `mediaResolution: ULTRA_HIGH` (2,184 image tokens vs 1,120) | report_07, 3.5-flash-lite, 1 call | Still 3.3. Dropped: doubles image tokens for no gain. |
