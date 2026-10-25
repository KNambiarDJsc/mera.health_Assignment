"""[Frozen copy of extract.py as tested in runs/*/v2_* (image mode, 200 DPI). See git history.]
Extract structured lab results from a lab report.

Usage:
    python extract.py reports/report_01.pdf

Prints JSON matching schema.json to stdout. Errors go to stderr with a non-zero exit;
a failed call never prints an empty-but-valid result.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
PDF_MODE = os.environ.get("EXTRACT_PDF_MODE", "image")   # "image": render pages; "native": send the PDF
DPI = 200            # Gemini bills an image at a fixed token count, so resolution is free; 60 DPI lost digits

PROMPT = """You are transcribing a medical lab report into structured data. The output becomes the patient's record, so copy exactly what is printed. Never correct, standardise or fill in anything.

Return one entry per printed result row, in printed order, across every page.

- test_name: exactly as printed. Do not expand abbreviations or rename.
- value: the result exactly as printed, as a string, with its qualifiers and formatting: "< 0.5", "2-3", "Negative", "Present (+)", "2,29,000". Do not round, convert or recompute.
- unit: the unit printed for that row. If it is printed inside the result cell ("179 ng/dL") or the range cell ("0 - 5 /hpf"), put it here instead. null if none is printed.
- reference_range: the range exactly as printed for that row, without the unit. null if that row has no printed range. Never supply a range from your own knowledge.

Include only rows that report a result for this patient. Skip section headings, column headers, methods, comments, signatures, patient details and handwritten notes. Tables may sit side by side: read each table across its own columns.
If the document contains no lab results (for example a prescription or a list of tests advised), return an empty list.
If a value cannot be read with confidence, use null rather than guessing."""

NULLABLE = {"type": "STRING", "nullable": True}
RESPONSE_SCHEMA = {
    "type": "OBJECT", "required": ["tests"],
    "properties": {"tests": {"type": "ARRAY", "items": {
        "type": "OBJECT", "required": ["test_name", "value", "unit", "reference_range"],
        "propertyOrdering": ["test_name", "value", "unit", "reference_range"],
        "properties": {"test_name": {"type": "STRING"}, "value": NULLABLE, "unit": NULLABLE,
                       "reference_range": NULLABLE},
    }}},
}

MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def load_parts(path: Path) -> list[dict]:
    """Every page of the report as Gemini inline-data parts."""
    suffix = path.suffix.lower()
    if suffix == ".pdf" and PDF_MODE == "native":
        return [inline("application/pdf", path.read_bytes())]
    if suffix == ".pdf":
        with tempfile.TemporaryDirectory() as directory:
            try:
                subprocess.run(["pdftoppm", "-r", str(DPI), "-png", str(path), str(Path(directory) / "page")],
                               check=True, capture_output=True)
            except FileNotFoundError:
                raise RuntimeError("Install Poppler (pdftoppm); see README.md.") from None
            except subprocess.CalledProcessError as error:
                raise RuntimeError(f"pdftoppm could not read {path}: {error.stderr.decode().strip()}") from None
            pages = sorted(Path(directory).glob("page*.png"), key=lambda p: int(p.stem.split("-")[-1]))
            return [inline("image/png", p.read_bytes()) for p in pages]
    if suffix in MEDIA_TYPES:
        return [inline(MEDIA_TYPES[suffix], path.read_bytes())]
    raise RuntimeError(f"Unsupported file type {suffix!r}; expected .pdf, .jpg, .jpeg or .png.")


def inline(media_type: str, data: bytes) -> dict:
    return {"inlineData": {"mimeType": media_type, "data": base64.standard_b64encode(data).decode()}}


def call_model(parts: list[dict], attempts: int = 4) -> dict:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY; see README.md. No API call made.")
    body = {
        "contents": [{"role": "user", "parts": [*parts, {"text": PROMPT}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 16000,
                             "responseMimeType": "application/json", "responseSchema": RESPONSE_SCHEMA},
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        data=json.dumps(body).encode(), headers={"x-goog-api-key": key, "Content-Type": "application/json"},
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise RuntimeError(f"Gemini HTTP {error.code}; check API access, model and quota. See README.md.") from None
        except urllib.error.URLError:
            if attempt == attempts - 1:
                raise RuntimeError("Gemini connection failed; check network/TLS access and retry. See README.md.") from None
        time.sleep(2 ** attempt * 3)


def parse(result: dict) -> list[dict]:
    candidate = (result.get("candidates") or [{}])[0]
    if candidate.get("finishReason") != "STOP":
        raise RuntimeError(f"Model stopped early ({candidate.get('finishReason')}); output would be incomplete.")
    text = "".join(p["text"] for p in candidate.get("content", {}).get("parts", [])
                   if "text" in p and not p.get("thought"))
    try:
        return json.loads(text)["tests"]
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("Model returned malformed JSON; refusing to print a partial result.") from None


def text_or_none(value):
    value = None if value is None else str(value).strip()
    return value or None


def clean(tests: list[dict]) -> list[dict]:
    rows = [{"test_name": text_or_none(t.get("test_name")), "value": text_or_none(t.get("value")),
             "unit": text_or_none(t.get("unit")), "reference_range": text_or_none(t.get("reference_range"))}
            for t in tests]
    return [r for r in rows if r["test_name"]]


def extract(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"No such file: {path}")
    return {"tests": clean(parse(call_model(load_parts(path))))}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        print(json.dumps(extract(Path(sys.argv[1])), indent=2, ensure_ascii=False))
    except RuntimeError as error:
        sys.exit(str(error))
