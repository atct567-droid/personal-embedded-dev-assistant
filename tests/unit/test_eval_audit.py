"""Audit arithmetic tests; held-out questions are deliberately not evaluated."""
from eval.audit_baseline import metric
from eval.run_eval import metric_detail


def test_metric_reports_exact_counts_and_failures():
    rows = [{"id": "a", "ok": True}, {"id": "b", "ok": False}]
    assert metric(rows, "ok") == {
        "numerator": 1, "denominator": 2, "failed_ids": ["b"]
    }


def test_empty_metric_does_not_fabricate_perfect_score():
    assert metric([], "ok") == {
        "numerator": 0, "denominator": 0, "failed_ids": []
    }


def test_metric_detail_keeps_question_ids_and_exact_denominator():
    rows = [{"id": "um01", "ok": True}, {"id": "um02", "ok": False}]
    assert metric_detail(rows, "ok") == {
        "numerator": 1,
        "denominator": 2,
        "rate": 0.5,
        "failed_ids": ["um02"],
    }
