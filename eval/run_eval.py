"""Run the deterministic 22-question offline evaluation."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from app.config import Settings
from app.logging_config import close_logging
from app.runtime import ApplicationRuntime


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_questions() -> list[dict[str, object]]:
    path = Path(os.getenv("PDA_EVAL_QUESTIONS_PATH", str(PROJECT_ROOT / "eval" / "questions.jsonl")))
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_runtime(work_root: Path) -> ApplicationRuntime:
    settings = Settings.from_root(work_root)
    settings.ensure_directories()
    fixture_root = Path(os.getenv("PDA_EVAL_FIXTURE_DIR", str(PROJECT_ROOT / "tests" / "fixtures")))
    custom_fixture_root = "PDA_EVAL_FIXTURE_DIR" in os.environ
    if custom_fixture_root:
        for source in fixture_root.rglob("*"):
            if not source.is_file() or source.name == ".gitkeep":
                continue
            target_root = settings.logs_dir if source.suffix.lower() == ".log" else settings.inbox_dir
            shutil.copy2(source, target_root / source.name)
    else:
        for source_name in ("uart.md", "i2c_sensors.md", "troubleshooting.md"):
            shutil.copy2(fixture_root / source_name, settings.inbox_dir / source_name)
        shutil.copy2(fixture_root / "device.log", settings.logs_dir / "device.log")
    runtime = ApplicationRuntime.from_settings(settings)
    if custom_fixture_root:
        for source in settings.inbox_dir.iterdir():
            if source.is_file():
                runtime.indexer.ingest_file(source, relative_path=source.name)
    else:
        for source_name in ("uart.md", "i2c_sensors.md", "troubleshooting.md"):
            source = settings.inbox_dir / source_name
            runtime.indexer.ingest_file(source, relative_path=source_name)
    return runtime


def contains_expected_terms(answer: str, expected_terms: list[str]) -> bool:
    normalized = answer.casefold()
    return all(term.casefold() in normalized for term in expected_terms)


def metric_detail(rows: list[dict[str, object]], field: str) -> dict[str, object]:
    """Return auditable numerator, denominator, rate, and failed question IDs."""
    numerator = sum(bool(row[field]) for row in rows)
    denominator = len(rows)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else None,
        "failed_ids": [str(row["id"]) for row in rows if not row[field]],
    }


def evaluate() -> dict[str, object]:
    questions = load_questions()
    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="pda-eval-") as temporary:
        runtime = build_runtime(Path(temporary))
        for item in questions:
            started = time.perf_counter()
            error: str | None = None
            retrieved_sources: list[str] = []
            citation = False
            answer_supported = False
            refusal_correct = False
            tool_success = False
            answer = ""
            failure_stage: str | None = None
            try:
                expected = item.get("expected_source")
                expected_terms = [str(term) for term in item.get("expected_terms", [])]
                if item["kind"] == "tool":
                    state = runtime.agent.run(str(item["question"]))
                    if item.get("confirm"):
                        state = runtime.agent.confirm(state.session_id, True)
                    answer = state.final_answer or ""
                    retrieved_sources = [e.source_file for e in state.retrieved_evidence]
                    retrieved_sources.extend(e.source_file for e in state.log_evidence)
                    for result in state.tool_results:
                        if result.get("ok") and result.get("tool") == "search_log":
                            matches = result.get("data", {}).get("matches", [])
                            if any(match.get("relative_path") == expected for match in matches):
                                tool_success = True
                    if item.get("confirm"):
                        tool_success = tool_success and bool(state.note_path)
                    answer_supported = contains_expected_terms(answer, expected_terms)
                    if not tool_success:
                        failure_stage = "tool"
                    elif not answer_supported:
                        failure_stage = "generation"
                else:
                    response = runtime.answerer.answer(str(item["question"]), trace_id=f"trace-eval-{item['id']}")
                    answer = response.answer
                    retrieved_sources = [citation.source_file for citation in response.citations]
                    citation = expected is not None and expected in retrieved_sources
                    answer_supported = (
                        bool(response.citations)
                        and contains_expected_terms(answer, expected_terms)
                        if expected is not None
                        else False
                    )
                    refusal_correct = item["kind"] == "unanswerable" and not response.citations and "不足以确定" in answer
                    if item["kind"] == "unanswerable":
                        answer_supported = False
                        if not refusal_correct:
                            failure_stage = "refusal"
                    elif not citation:
                        failure_stage = "retrieval"
                    elif not answer_supported:
                        failure_stage = "generation"
            except Exception as exc:
                error = type(exc).__name__
                failure_stage = "execution"
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
            rows.append(
                {
                    "id": str(item["id"]),
                    "kind": str(item["kind"]),
                    "question": item["question"],
                    "expected_source": item.get("expected_source"),
                    "retrieved_sources": retrieved_sources,
                    "answer": answer,
                    "citation": citation,
                    "retrieval_hit_at_5": citation,
                    "answer_supported": answer_supported,
                    "refusal_correct": refusal_correct,
                    "tool_success": tool_success,
                    "latency_ms": latency_ms,
                    "error": error,
                    "failure_stage": failure_stage,
                }
            )
        close_logging()
    answerable = [row for row, item in zip(rows, questions, strict=True) if item["kind"] != "unanswerable" and item["kind"] != "tool"]
    unanswerable = [row for row, item in zip(rows, questions, strict=True) if item["kind"] == "unanswerable"]
    tool_rows = [row for row, item in zip(rows, questions, strict=True) if item["kind"] == "tool"]
    metrics = {
        "question_count": len(rows),
        "hit_at_5": sum(bool(row["retrieval_hit_at_5"]) for row in answerable) / len(answerable),
        "citation_correctness": sum(bool(row["citation"]) for row in answerable) / len(answerable),
        "answer_supported_rate": sum(bool(row["answer_supported"]) for row in answerable) / len(answerable),
        "refusal_correct_rate": sum(bool(row["refusal_correct"]) for row in unanswerable) / len(unanswerable),
        "tool_success_rate": sum(bool(row["tool_success"]) for row in tool_rows) / len(tool_rows),
        "average_latency_ms": round(sum(float(row["latency_ms"]) for row in rows) / len(rows), 3),
    }
    metric_details = {
        "retrieval_hit_at_5": metric_detail(answerable, "retrieval_hit_at_5"),
        "citation_correctness": metric_detail(answerable, "citation"),
        "answer_supported_rate": metric_detail(answerable, "answer_supported"),
        "refusal_correct_rate": metric_detail(unanswerable, "refusal_correct"),
        "tool_success_rate": metric_detail(tool_rows, "tool_success"),
    }
    bad_cases = []
    for row, item in zip(rows, questions, strict=True):
        is_bad_refusal = item["kind"] == "unanswerable" and not row["refusal_correct"]
        is_bad_answer = item["kind"] not in {"unanswerable", "tool"} and (
            not row["citation"] or not row["answer_supported"]
        )
        is_bad_tool = item["kind"] == "tool" and (
            not row["tool_success"] or not row["answer_supported"]
        )
        if row["error"] or is_bad_refusal or is_bad_answer or is_bad_tool:
            bad_cases.append(row)
    report = {
        "mode": "offline-mock",
        "metrics": metrics,
        "metric_details": metric_details,
        "rows": rows,
        "bad_cases": bad_cases,
    }
    report_value = os.getenv("PDA_EVAL_REPORT_PATH")
    report_path = Path(report_value) if report_value else PROJECT_ROOT / "data" / "eval_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
