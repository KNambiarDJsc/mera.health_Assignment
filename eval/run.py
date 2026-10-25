"""Run an extractor over every report and save outputs + latency + token usage.

    python eval/run.py <extractor.py> <out_dir> [report ...]

Imports the extractor in-process and calls its extract(path), so the extractor's
code path is unchanged. Token usage is captured by teeing urllib responses
(both baseline and final call Gemini through urllib.request.urlopen).
5xx/timeouts are retried up to 3 times and every failed attempt is recorded; a 429
stops the run. Reports already saved in <out_dir> are skipped, so runs resume.
"""
import importlib.util
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_real_urlopen = urllib.request.urlopen
_usage: list[dict] = []


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def tee_urlopen(*args, **kwargs):
    with _real_urlopen(*args, **kwargs) as response:
        body = response.read()
    try:
        _usage.append(json.loads(body).get("usageMetadata", {}))
    except ValueError:
        pass
    return _Resp(body)


def load(extractor: Path):
    spec = importlib.util.spec_from_file_location("extractor_under_test", extractor)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    extractor, out = Path(sys.argv[1]), Path(sys.argv[2])
    reports = [Path(p) for p in sys.argv[3:]] or sorted((ROOT / "reports").iterdir())
    out.mkdir(parents=True, exist_ok=True)
    urllib.request.urlopen = tee_urlopen
    module = load(extractor)
    meta = json.loads((out / "meta.json").read_text()) if (out / "meta.json").exists() else {}
    meta.update({"extractor": str(extractor), "model": getattr(module, "MODEL", None)})
    meta.setdefault("reports", {})
    for report in reports:
        if (out / f"{report.stem}.json").exists():       # resumable across daily-quota resets
            continue
        record = {"errors": []}
        for attempt in range(3):
            _usage.clear()
            start = time.perf_counter()
            try:
                result = module.extract(report)
            except Exception as error:  # record and retry 5xx/timeouts; the baseline itself never retries
                record["errors"].append(f"{type(error).__name__}: {error}")
                if "429" in str(error):                  # free-tier daily cap: retrying only burns requests
                    meta["reports"][report.stem] = record
                    (out / "meta.json").write_text(json.dumps(meta, indent=2))
                    sys.exit(f"{report.stem}: quota exhausted (429); stopping run")
                time.sleep(30 * (attempt + 1))
                continue
            record["latency_s"] = round(time.perf_counter() - start, 2)
            record["usage"] = list(_usage)
            (out / f"{report.stem}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            break
        meta["reports"][report.stem] = record
        print(report.stem, record.get("latency_s"), len(result["tests"]) if "latency_s" in record else "FAILED",
              record["errors"] or "", file=sys.stderr)
        (out / "meta.json").write_text(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
