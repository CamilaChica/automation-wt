import asyncio

from services.agent_evaluation import EvaluationReport, compare_reports, evaluate_cases


def test_default_agent_evaluation_suite_is_green():
    report = asyncio.run(evaluate_cases())

    assert report.total_cases == 11
    assert report.passed_cases == report.total_cases
    assert report.score == 1.0


def test_comparison_analysis_identifies_regressions_and_improvements():
    baseline = EvaluationReport(
        total_cases=2,
        passed_cases=1,
        score=0.5,
        results=[
            {"case": "a", "agent": "A", "passed": False, "latency_ms": 10},
            {"case": "b", "agent": "B", "passed": True, "latency_ms": 10},
        ],
    )
    candidate = EvaluationReport(
        total_cases=2,
        passed_cases=1,
        score=0.5,
        results=[
            {"case": "a", "agent": "A", "passed": True, "latency_ms": 12},
            {"case": "b", "agent": "B", "passed": False, "latency_ms": 8},
        ],
    )

    comparison = compare_reports(baseline, candidate)

    assert comparison["score_delta"] == 0.0
    assert comparison["improvements"][0]["case"] == "a"
    assert comparison["regressions"][0]["case"] == "b"
    assert comparison["cases"][0]["latency_delta_ms"] == 2
