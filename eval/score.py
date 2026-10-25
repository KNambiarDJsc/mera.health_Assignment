"""Score extraction runs against gold labels.

    python eval/score.py runs/<run> [runs/<run2> ...] [--corrected] [--errors]

A predicted row is matched to at most one gold row, on test name only (never on
value), so a duplicate prediction cannot satisfy two gold rows. Matched rows are
then checked field by field. Missing gold rows and unmatched predictions are
counted, not hidden.

--corrected applies eval/gold_corrections.json (documented label errors) as a
sensitivity check. --lenient also matches names whose tokens are a subset of the
other's, to show how much of a difference is only renaming. Official numbers are
always strict + uncorrected.
"""
import json
import math
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ---------- normalisation (applied identically to gold and prediction) ----------

def norm_text(s) -> str:
    s = str(s).strip().lower().replace("µ", "u").replace("μ", "u").replace("–", "-")
    s = re.sub(r"(?<=\d),(?=\d)", "", s)          # 2,29,000 -> 229000
    return re.sub(r"\s+", "", s)


def as_num(s):
    try:
        return float(norm_text(s))
    except ValueError:
        return None


def value_eq(pred, gold) -> bool:
    if pred is None or gold is None:
        return pred is None and gold is None
    p, g = as_num(pred), as_num(gold)
    if p is not None and g is not None:
        return abs(p - g) <= 1e-9 * max(1.0, abs(g))
    return norm_text(pred) == norm_text(gold)


def is_decimal_shift(p, g) -> bool:
    """13.5 read as 135 or 1.35: same digits, decimal point moved."""
    if not p or not g or p == g:
        return False
    exponent = math.log10(abs(p / g))
    return abs(exponent - round(exponent)) < 1e-6


def unit_eq(pred, gold) -> bool:
    return norm_text(pred or "") == norm_text(gold or "")


def norm_range(r, units) -> str | None:
    if r is None or not str(r).strip():
        return None
    s = str(r)
    for u in units:                                # "< 5.0 mg/L" with unit mg/L == "< 5.0"
        if u and u.strip():
            s = re.sub(re.escape(u.strip()) + r"\s*$", "", s.strip(), flags=re.I)
    s = norm_text(s).replace("to", "-")
    return re.sub(r"\d+(?:\.\d+)?", lambda m: f"{float(m.group()):g}", s)


# ---------- name matching ----------

def _clean(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def name_variants(name: str) -> set[str]:
    name = name.lower()
    variants = {_clean(name), _clean(re.sub(r"\([^)]*\)", " ", name))}
    variants |= {_clean(inner) for inner in re.findall(r"\(([^)]*)\)", name)}
    return {v for v in variants if v}


def _tokens_match(a: str, b: str) -> bool:
    ta, tb = sorted(a.split()), sorted(b.split())
    if len(ta) != len(tb):
        return False
    for x, y in zip(ta, tb):   # short tokens (abbreviations: HDL vs LDL) must be exact
        if x != y and not (min(len(x), len(y)) >= 5 and SequenceMatcher(None, x, y).ratio() >= 0.85):
            return False
    return True


LENIENT = False   # --lenient: sensitivity only, also accepts "Triglycerides" for "Serum Triglycerides"


def name_tier(pred: str, gold: str) -> float:
    """3 exact, 2 a parenthetical/outer variant equal, 1 token-fuzzy, 0.5 token subset (lenient only), 0 none."""
    if _clean(pred) == _clean(gold):
        return 3
    pv, gv = name_variants(pred), name_variants(gold)
    if pv & gv:
        return 2
    if any(_tokens_match(a, b) for a in pv for b in gv):
        return 1
    if LENIENT and any(set(a.split()) < set(b.split()) or set(b.split()) < set(a.split()) for a in pv for b in gv):
        return 0.5
    return 0


def match(preds: list[dict], golds: list[dict]) -> list[tuple[int, int]]:
    pairs = []
    for i, p in enumerate(preds):
        for j, g in enumerate(golds):
            tier = name_tier(str(p.get("test_name", "")), g["test_name"])
            if tier:
                drift = abs(i / max(len(preds), 1) - j / max(len(golds), 1))
                pairs.append((tier, -drift, i, j))
    used_p, used_g, out = set(), set(), []
    for _, _, i, j in sorted(pairs, reverse=True):
        if i not in used_p and j not in used_g:
            used_p.add(i), used_g.add(j), out.append((i, j))
    return out


# ---------- scoring ----------

def score_report(preds: list[dict], golds: list[dict]) -> dict:
    c = dict(gold=len(golds), pred=len(preds), matched=0, value_ok=0, value_wrong=0, value_null=0,
             decimal_err=0, unit_ok=0, range_ok=0, range_fabricated=0, row_ok=0)
    errors = []
    pairs = match(preds, golds)
    for i, j in pairs:
        p, g = preds[i], golds[j]
        c["matched"] += 1
        v_ok = value_eq(p.get("value"), g["value"])
        u_ok = unit_eq(p.get("unit"), g["unit"])
        units = (p.get("unit"), g["unit"])
        pr, gr = norm_range(p.get("reference_range"), units), norm_range(g["reference_range"], units)
        r_ok = pr == gr
        c["value_ok"] += v_ok
        c["unit_ok"] += u_ok
        c["range_ok"] += r_ok
        c["row_ok"] += v_ok and u_ok and r_ok
        if not v_ok:
            if p.get("value") is None:
                c["value_null"] += 1
            else:
                c["value_wrong"] += 1
                c["decimal_err"] += is_decimal_shift(as_num(p.get("value")), as_num(g["value"]))
        if gr is None and pr is not None:
            c["range_fabricated"] += 1
        if not (v_ok and u_ok and r_ok):
            errors.append({"kind": "field", "gold": g, "pred": {k: p.get(k) for k in g},
                           "bad": [f for f, ok in (("value", v_ok), ("unit", u_ok), ("range", r_ok)) if not ok]})
    matched_p, matched_g = {i for i, _ in pairs}, {j for _, j in pairs}
    errors += [{"kind": "missing", "gold": g} for j, g in enumerate(golds) if j not in matched_g]
    errors += [{"kind": "extra", "pred": {k: p.get(k) for k in ("test_name", "value", "unit", "reference_range")}}
               for i, p in enumerate(preds) if i not in matched_p]
    return {"counts": c, "errors": errors}


def load_gold(corrected: bool) -> dict:
    gold = {p.stem: json.loads(p.read_text(encoding="utf-8"))["tests"] for p in sorted((ROOT / "gold").glob("*.json"))}
    if corrected:
        for fix in json.loads((ROOT / "eval" / "gold_corrections.json").read_text(encoding="utf-8")):
            row = next(r for r in gold[fix["report"]] if r["test_name"] == fix["test_name"])
            row[fix["field"]] = fix["corrected"]
    return gold


def summarise(c: dict) -> dict:
    g, p = c["gold"], c["pred"]
    return {
        "rows_gold": g, "rows_pred": p,
        "recall": c["matched"] / g if g else 0, "precision": c["matched"] / p if p else 0,
        "value_acc": c["value_ok"] / g,             # over ALL gold rows: a missing row is a failure
        "row_acc": c["row_ok"] / g,                 # value + unit + range all correct
        "wrong_values": c["value_wrong"], "decimal_errors": c["decimal_err"], "null_values": c["value_null"],
        "missing_rows": g - c["matched"], "extra_rows": p - c["matched"],
        "unit_acc_matched": c["unit_ok"] / max(c["matched"], 1),
        "range_acc_matched": c["range_ok"] / max(c["matched"], 1),
        "fabricated_ranges": c["range_fabricated"],
    }


def score_run(run: Path, gold: dict) -> dict:
    per, total = {}, None
    for stem, golds in gold.items():
        path = run / f"{stem}.json"
        preds = json.loads(path.read_text(encoding="utf-8"))["tests"] if path.exists() else []
        per[stem] = score_report(preds, golds)
        per[stem]["failed"] = not path.exists()
        total = per[stem]["counts"].copy() if total is None else {k: total[k] + v for k, v in per[stem]["counts"].items()}
    unlabelled = {}
    for path in sorted(run.glob("report_*.json")):
        if path.stem not in gold:
            unlabelled[path.stem] = len(json.loads(path.read_text(encoding="utf-8"))["tests"])
    return {"overall": summarise(total), "per_report": {k: summarise(v["counts"]) | {"failed": v["failed"]}
                                                        for k, v in per.items()},
            "errors": {k: v["errors"] for k, v in per.items()}, "unlabelled_row_counts": unlabelled}


PRICE_IN, PRICE_OUT = 0.75, 3.75   # USD / 1M tokens, gemini-3.8-flash paid tier (ai.google.dev/pricing, to 2026-12-31)


def cost_latency(run: Path) -> dict:
    """From run meta.json: tokens of the successful attempt, priced at paid-tier rates (actual spend: $0, free tier)."""
    meta_path = run / "meta.json"
    if not meta_path.exists():
        return {}
    records = [r for r in json.loads(meta_path.read_text())["reports"].values() if "latency_s" in r]
    lat = sorted(r["latency_s"] for r in records)
    tin = [sum(u.get("promptTokenCount", 0) for u in r["usage"]) for r in records]
    tout = [sum(u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0) for u in r["usage"]) for r in records]
    cost = [(i * PRICE_IN + o * PRICE_OUT) / 1e6 for i, o in zip(tin, tout)]
    return {"reports_ok": len(records), "failed_attempts": sum(len(r["errors"]) for r in
                                                               json.loads(meta_path.read_text())["reports"].values()),
            "latency_p50_s": lat[len(lat) // 2], "latency_max_s": lat[-1],
            "tokens_in_mean": round(sum(tin) / len(tin)), "tokens_out_mean": round(sum(tout) / len(tout)),
            "usd_per_report": round(sum(cost) / len(cost), 5)}


def fmt(x):
    return f"{x:.3f}" if isinstance(x, float) else str(x)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    global LENIENT
    corrected, show_errors, LENIENT = "--corrected" in sys.argv, "--errors" in sys.argv, "--lenient" in sys.argv
    gold = load_gold(corrected)
    cols = ["value_acc", "row_acc", "recall", "precision", "wrong_values", "decimal_errors", "null_values",
            "missing_rows", "extra_rows", "fabricated_ranges", "unit_acc_matched", "range_acc_matched"]
    mode = "_".join(m for m, on in (("corrected", corrected), ("lenient", LENIENT)) if on)
    print(f"gold: {'CORRECTED (sensitivity)' if corrected else 'official'}; "
          f"name matching: {'LENIENT (sensitivity)' if LENIENT else 'strict'}\n")
    print("| run | " + " | ".join(cols) + " |\n|" + "---|" * (len(cols) + 1))
    results = {}
    for run in map(Path, args):
        results[run] = res = score_run(run, gold)
        print(f"| {run.parent.name}/{run.name} | " + " | ".join(fmt(res['overall'][k]) for k in cols) + " |")
        res["cost_latency"] = cost_latency(run)
        (run / f"score{'_' + mode if mode else ''}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False),
                                                                    encoding="utf-8")
    ccols = ["reports_ok", "failed_attempts", "latency_p50_s", "latency_max_s", "tokens_in_mean", "tokens_out_mean",
             "usd_per_report"]
    print("\n| run | " + " | ".join(ccols) + " |\n|" + "---|" * (len(ccols) + 1))
    for run, res in results.items():
        print(f"| {run.parent.name}/{run.name} | " + " | ".join(fmt(res["cost_latency"].get(k, "")) for k in ccols) + " |")
    for run, res in results.items():
        print(f"\n{run.name} per report: value_acc / wrong / missing / extra / fab_ranges")
        for stem, s in res["per_report"].items():
            print(f"  {stem}: {s['value_acc']:.2f} / {s['wrong_values']} / {s['missing_rows']} / {s['extra_rows']}"
                  f" / {s['fabricated_ranges']}{'  FAILED' if s['failed'] else ''}")
        print(f"  unlabelled row counts: {res['unlabelled_row_counts']}")
        if show_errors:
            for stem, errs in res["errors"].items():
                for e in errs:
                    print(f"  {stem} {e['kind']}: {json.dumps({k: v for k, v in e.items() if k != 'kind'}, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
