"""Contract tests for extract.py. No network: the model call is faked."""
import base64
import io
import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import extract  # noqa: E402

SCHEMA = json.loads((ROOT / "schema.json").read_text())


def gemini_response(tests, finish="STOP"):
    return {"candidates": [{"finishReason": finish, "content": {"parts": [{"text": json.dumps({"tests": tests})}]}}]}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_output_is_schema_valid_and_keeps_strings(monkeypatch):
    rows = [{"test_name": "Sugar", "value": "Present (+)", "unit": None, "reference_range": "Negative"},
            {"test_name": "Platelets", "value": "2,29,000", "unit": "/cumm", "reference_range": "1,50,000 - 4,10,000"},
            {"test_name": "CRP", "value": "< 0.5", "unit": "mg/L", "reference_range": "< 5.0"},
            {"test_name": "T3", "value": "179", "unit": "ng/dL", "reference_range": None}]
    rows = [r | {"legibility": "clear"} for r in rows]
    monkeypatch.setattr(extract, "call_model", lambda parts: gemini_response(rows))
    out = extract.extract(ROOT / "reports" / "report_08.jpg")
    jsonschema.validate(out, SCHEMA)
    assert out["tests"] == rows                    # verbatim: nothing coerced, no range invented


def test_empty_strings_become_null_and_nameless_rows_dropped():
    rows = extract.clean([{"test_name": " Urea ", "value": " 26 ", "unit": "", "reference_range": "  "},
                          {"test_name": "", "value": "5"}])
    assert rows == [{"test_name": "Urea", "value": "26", "unit": None, "reference_range": None, "legibility": None}]


def test_no_results_document_is_empty_not_error(monkeypatch):
    monkeypatch.setattr(extract, "call_model", lambda parts: gemini_response([]))
    assert extract.extract(ROOT / "reports" / "report_12.jpg") == {"tests": []}


@pytest.mark.parametrize("result", [gemini_response([], finish="MAX_TOKENS"),
                                    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{oops"}]}}]},
                                    {}])
def test_truncated_or_malformed_output_raises(result):
    with pytest.raises(RuntimeError):
        extract.parse(result)


def test_whole_pdf_is_sent_natively():
    pdf = ROOT / "reports" / "report_11.pdf"                     # 2 pages: both must reach the model
    [part] = extract.load_parts(pdf)
    assert part["inlineData"]["mimeType"] == "application/pdf"
    assert base64.b64decode(part["inlineData"]["data"]) == pdf.read_bytes()


def test_images_sent_with_their_media_type():
    [part] = extract.load_parts(ROOT / "reports" / "report_08.jpg")
    assert part["inlineData"]["mimeType"] == "image/jpeg"


def test_unsupported_and_missing_files_raise(tmp_path):
    (tmp_path / "x.docx").write_bytes(b"nope")
    with pytest.raises(RuntimeError):
        extract.load_parts(tmp_path / "x.docx")
    with pytest.raises(RuntimeError):
        extract.extract(tmp_path / "missing.pdf")


def test_corrupt_pdf_raises(tmp_path):
    (tmp_path / "bad.pdf").write_bytes(b"not a pdf")
    with pytest.raises(RuntimeError):
        extract.load_parts(tmp_path / "bad.pdf")


def test_transient_errors_retried_auth_errors_not(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(extract.time, "sleep", lambda s: None)
    calls = []

    def flaky(request, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)
        return FakeResponse(json.dumps(gemini_response([])).encode())

    monkeypatch.setattr(extract.urllib.request, "urlopen", flaky)
    assert extract.call_model([]) == gemini_response([]) and len(calls) == 3

    calls.clear()
    monkeypatch.setattr(extract.urllib.request, "urlopen",
                        lambda r, timeout: calls.append(1) or (_ for _ in ()).throw(
                            urllib.error.HTTPError(r.full_url, 401, "no", {}, None)))
    with pytest.raises(RuntimeError, match="401"):
        extract.call_model([])
    assert len(calls) == 1


def test_missing_key_makes_no_call(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(extract.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network used"))
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        extract.call_model([])


def test_cli_errors_go_to_stderr_with_clean_stdout(tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "extract.py"), str(tmp_path / "missing.pdf")],
                          capture_output=True, text=True)
    assert proc.returncode != 0 and proc.stdout == "" and "No such file" in proc.stderr


def test_no_report_specific_logic():
    source = (ROOT / "extract.py").read_text(encoding="utf-8").split('"""', 2)[2]   # skip usage docstring
    assert "report_" not in source and "Platelet" not in source
