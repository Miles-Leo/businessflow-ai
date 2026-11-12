from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from app.ai.fixed_evaluation import (
    grade_response, load_cases, order_fixture, policy_rows, summarize, write_markdown,
)


def case(case_id):
    return next(c for c in load_cases()["agent_cases"] if c["id"] == case_id)


def call(name="lookup_order", **args):
    return {"name": name, "args": args}


def test_dataset_ids_and_policy_fixtures_are_valid():
    data = load_cases()
    assert len(data["agent_cases"]) == 15
    for c in data["agent_cases"]:
        assert c["category"] and c["question"] and isinstance(c["tools"], list)
        if c.get("policy"):
            assert len(policy_rows(c["policy"])) == len(c["policy"])


@pytest.mark.parametrize("kind,expected", [("overdue", True), ("not_due", False), ("on_time", False), ("late_shipped", False)])
def test_order_fixtures_have_fixed_clock(kind, expected):
    result = order_fixture(kind, "BF2026001", load_cases()["checked_at"])
    assert result["assessment"]["is_overdue_unshipped"] is expected
    assert result["assessment"]["checked_at"] == load_cases()["checked_at"]


def test_terms_alone_do_not_pass_wrong_tool_or_argument():
    c = case("ORDER-001")
    answer = "BF2026001 超期未发货 2026-11-09"
    assert not grade_response(c, answer, [], [])["passed"]
    result = grade_response(c, answer, [call(order_id="BF9999999")], [])
    assert not result["checks"]["tool_arguments"]
    assert grade_response(c, answer, [call(order_id="BF2026001")], [])["passed"]


def test_missing_order_must_not_call_a_tool():
    assert not grade_response(case("ORDER-005"), "请提供订单编号", [call(order_id="BF2026001")], [])["passed"]


def test_policy_citation_checks_sources_and_required_sections():
    c = case("RAG-003")
    calls = [call("search_policy", question="审核")]
    results = [{"data": policy_rows(["AS-05"])}]
    answer = "不能创建。BusinessFlow AI AS-05 knowledge/after_sales_policy.md"
    assert grade_response(c, answer, calls, results)["passed"]
    assert not grade_response(c, answer + " AS-99", calls, results)["passed"]
    assert not grade_response(c, "不能创建。[1]", calls, results)["passed"]
    assert not grade_response(c, answer, calls, [])["passed"]


def test_failure_cannot_be_presented_as_absent_order():
    row = grade_response(case("FAULT-001"), "暂时失败，订单不存在", [call(order_id="BF2026001")], [])
    assert not row["passed"]


def test_write_claim_and_injected_marker_fail():
    c = case("SAFE-001")
    assert not grade_response(c, "无法退款，但已经创建正式工单", [], [])["passed"]
    assert not grade_response(c, "无法修改", [call("create_ticket")], [])["passed"]
    assert grade_response(c, "无法修改", [], [])["manual_review"] == "pending"


def test_summary_excludes_non_applicable_citations_and_reports_tail_latency():
    rows = [{"category": "test", "passed": True, "elapsed_seconds": x,
             "checks": {"completed": True, "citation_structure": None}} for x in range(1, 21)]
    report = summarize(rows)
    assert report["dimensions"]["citation_structure"] == {"passed": 0, "total": 0}
    assert report["latency_seconds"]["p95"] == 19
    assert report["manual_review_pending"] == 20


def test_retrieval_keeps_missing_sections_visible():
    from langchain_core.documents import Document
    from app.ai.fixed_evaluation import evaluate_retrieval
    doc = Document(page_content="fictional", metadata={"section": "AS-04：建议"})
    with patch("app.ai.rag.retrieve_policy", return_value=[doc]):
        report = evaluate_retrieval()
    assert report["passed"] == 1
    assert report["cases"][0]["recall"] == pytest.approx(1/3)


def test_model_runner_replaces_all_business_tools_without_real_model():
    from langchain_core.messages import AIMessage
    from app.ai.fixed_evaluation import evaluate_fixed_agent
    from app.ai.agent_graph import graph
    from app.ai import agent

    def invoke(state, config):
        assert agent.order_lookup_tool.invoke({"order_id": "BF2026001"})["status"] in {"success", "not_found", "failed"}
        assert agent.customer_lookup_tool.invoke({"customer_id": "fictional"})["status"] == "not_found"
        return {"messages": [AIMessage(content="请提供订单编号")]}

    dataset = deepcopy(load_cases())
    dataset["agent_cases"] = [case("ORDER-005")]
    with patch("app.ai.fixed_evaluation.load_cases", return_value=dataset), patch.object(graph, "invoke", side_effect=invoke):
        report = evaluate_fixed_agent()
    assert report["total"] == 1
    assert agent.order_lookup_tool.func.__name__ == "lookup_order_using_mcp"


def test_markdown_keeps_failures_and_semantic_review_pending(tmp_path):
    path = tmp_path / "report.json"
    report = {"agent": {"total": 1, "passed": 0, "limitations": "not semantic accuracy",
                        "cases": [{"id": "failed", "passed": False}]}}
    write_markdown(report, path)
    assert "FAIL" in path.with_suffix(".md").read_text(encoding="utf-8")
    assert "pending" in path.with_suffix(".review.csv").read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("passed,expected_exit", [(True, 0), (False, 1)])
def test_cli_preserves_report_and_returns_failure_for_failed_checks(tmp_path, passed, expected_exit):
    from scripts.evaluate import main
    with patch("sys.argv", ["evaluate", "--live", "--output", str(tmp_path)]), \
         patch("scripts.evaluate.provenance", return_value={}), \
         patch("scripts.evaluate.evaluate_fixed_agent", return_value={
             "total": 1, "passed": int(passed), "cases": [{"id": "fake", "passed": passed}]}):
        assert main() == expected_exit
    reports = list(tmp_path.glob("*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["agent"]["passed"] == int(passed)
