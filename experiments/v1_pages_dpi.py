"""Baseline prompt and parsing, unchanged. Only the input changes:
every PDF page is sent (baseline: page 1 only), at DPI from $EXP_DPI (baseline: 60).
Isolates rendering/page coverage from prompt effects."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import v0_baseline as base  # noqa: E402

MODEL = base.MODEL
DPI = int(os.environ.get("EXP_DPI", "60"))


def load_images(path: Path) -> list[tuple[str, str]]:
    if path.suffix.lower() != ".pdf":
        return [base.load_image(path)]
    with tempfile.TemporaryDirectory() as directory:
        subprocess.run(["pdftoppm", "-r", str(DPI), "-png", str(path), str(Path(directory) / "page")],
                       check=True, capture_output=True)
        return [("image/png", base64.standard_b64encode(p.read_bytes()).decode())
                for p in sorted(Path(directory).glob("page*.png"))]


def call_model(images: list[tuple[str, str]]) -> str:
    body = {
        "contents": [{"role": "user", "parts": [
            *({"inlineData": {"mimeType": m, "data": d}} for m, d in images), {"text": base.PROMPT},
        ]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 16000},
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        data=json.dumps(body).encode(),
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"], "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "".join(p["text"] for p in parts if "text" in p and not p.get("thought"))


def extract(path: Path) -> dict:
    return {"tests": base.clean(base.parse(call_model(load_images(path))))}


if __name__ == "__main__":
    print(json.dumps(extract(Path(sys.argv[1])), indent=2, ensure_ascii=False))
