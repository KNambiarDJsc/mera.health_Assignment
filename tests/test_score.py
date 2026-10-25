"""The eval must punish the errors a doctor cares about, and nothing else."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
from score import load_gold, match, score_report, summarise, value_eq, norm_range  # noqa: E402

ROW = {"test_name": "Haemoglobin", "value": "13.5", "unit": "g/dL", "reference_range": "13.0 - 17.0"}


def s(preds, golds):
    return summarise(score_report(preds, golds)["counts"])


def test_gold_scores_perfect_against_itself():
    for stem, rows in load_gold(False).items():
        r = s(copy.deepcopy(rows), rows)
        assert r["row_acc"] == 1.0 and r["extra_rows"] == 0, stem


def test_wrong_value_is_penalised_and_counted():
    r = s([ROW | {"value": "15.3"}], [ROW])
    assert r["value_acc"] == 0 and r["wrong_values"] == 1 and r["recall"] == 1


def test_decimal_shift_detected():
    assert s([ROW | {"value": 135}], [ROW])["decimal_errors"] == 1


def test_null_value_is_not_correct():
    r = s([ROW | {"value": None}], [ROW])
    assert r["value_acc"] == 0 and r["null_values"] == 1 and r["wrong_values"] == 0


def test_missing_row_counts_against_value_accuracy():
    other = ROW | {"test_name": "MCV", "value": "77.9"}
    r = s([ROW], [ROW, other])
    assert r["value_acc"] == 0.5 and r["missing_rows"] == 1


def test_duplicate_prediction_cannot_satisfy_two_gold_rows():
    golds = [ROW, ROW | {"value": "13.6"}]
    r = s([ROW, ROW], golds)
    assert r["recall"] == 1 and r["value_acc"] == 0.5


def test_extra_rows_count_against_precision():
    r = s([ROW, {"test_name": "Blood Pressure", "value": "133/81", "unit": "mmHg", "reference_range": None}], [ROW])
    assert r["extra_rows"] == 1 and r["precision"] == 0.5


def test_fabricated_reference_range_counted():
    gold = {"test_name": "T3", "value": "179", "unit": "ng/dL", "reference_range": None}
    r = s([gold | {"reference_range": "80 - 200"}], [gold])
    assert r["fabricated_ranges"] == 1 and r["row_acc"] == 0


def test_matching_is_on_name_not_value():
    hdl = {"test_name": "Cholesterol - HDL", "value": "36", "unit": "mg/dL", "reference_range": "> 40"}
    ldl = hdl | {"test_name": "Cholesterol - LDL", "value": "121"}
    assert match([ldl | {"value": "36"}], [hdl]) == []       # HDL/LDL never fuzzy-match


def test_name_variants_match_fairly():
    assert match([{"test_name": "Mean Corpuscular Volume (MCV)"}], [{"test_name": "MCV"}]) == [(0, 0)]
    assert match([{"test_name": "Hemoglobin"}], [{"test_name": "Haemoglobin"}]) == [(0, 0)]


def test_value_normalisation_is_format_only():
    assert value_eq("2,29,000", "229000") and value_eq(9200.0, "9200") and value_eq("<0.5", "< 0.5")
    assert value_eq("present(+)", "Present (+)") and not value_eq("Negative", "Positive")
    assert not value_eq("2-3", "1-2") and not value_eq(None, "Nil")


def test_range_unit_suffix_ignored_but_numbers_compared():
    assert norm_range("< 5.0 mg/L", ("mg/L",)) == norm_range("< 5.0", ("mg/L",))
    assert norm_range("1,50,000 - 4,10,000", ()) == norm_range("150000 - 410000", ())
    assert norm_range("13.0 - 17.0", ()) != norm_range("13.0 - 18.0", ())


def test_official_gold_files_untouched():
    gold = json.loads((ROOT / "gold" / "report_01.json").read_text(encoding="utf-8"))
    assert next(r for r in gold["tests"] if r["test_name"] == "Platelet Count")["value"] == "304000"
