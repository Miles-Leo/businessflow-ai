from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from app.services.approval import get_pending_review, submit_review, start_review


def test_start_review_uses_new_id_and_unreviewed_state():
    proposal = {"approval_status": "pending"}
    graph = Mock()
    graph.invoke.return_value = {"__interrupt__": [object()], "proposal": proposal}
    with patch("app.services.approval.uuid4", return_value=UUID(int=1)):
        result = start_review(graph, proposal)
    assert result == {"approval_id": str(UUID(int=1)), "approval_status": "pending"}
    graph.invoke.assert_called_once_with({
        "proposal": proposal, "reviewer_id": None, "reviewed_at": None,
    }, config={"configurable": {"thread_id": str(UUID(int=1))}})


def test_start_review_generates_distinct_ids():
    graph = Mock()
    graph.invoke.return_value = {"__interrupt__": [object()], "proposal": {"approval_status": "pending"}}
    first = start_review(graph, {"approval_status": "pending"})
    second = start_review(graph, {"approval_status": "pending"})
    assert first["approval_id"] != second["approval_id"]


def test_start_review_without_interrupt_is_not_reported_as_pending():
    graph = Mock()
    graph.invoke.return_value = {"proposal": {"approval_status": "pending"}}
    with pytest.raises(ValueError, match="未进入等待"):
        start_review(graph, {"approval_status": "pending"})


def snapshot(status="pending", next_nodes=("review",), ids=("interrupt-1",)):
    return SimpleNamespace(
        values={"proposal": {"approval_status": status}}, next=next_nodes,
        tasks=(SimpleNamespace(interrupts=tuple(SimpleNamespace(id=i) for i in ids)),),
    )


def test_pending_review_returns_exact_interrupt_and_config():
    saved = snapshot()
    graph = Mock()
    graph.get_state.return_value = saved
    result, config, interrupt_id = get_pending_review(graph, "approval-demo")
    assert result is saved
    assert config == {"configurable": {"thread_id": "approval-demo"}}
    assert interrupt_id == "interrupt-1"
    graph.get_state.assert_called_once_with(config)
    graph.invoke.assert_not_called()


def test_unknown_review_is_rejected():
    graph = Mock()
    graph.get_state.return_value = SimpleNamespace(values={})
    with pytest.raises(ValueError, match="不存在"):
        get_pending_review(graph, "unknown")
    graph.invoke.assert_not_called()


@pytest.mark.parametrize("saved,message", [
    (snapshot(status="approved"), "已完成"),
    (snapshot(status="rejected"), "已完成"),
    (snapshot(next_nodes=()), "不在等待"),
    (snapshot(ids=()), "唯一"),
    (snapshot(ids=("one", "two")), "唯一"),
])
def test_nonresumable_review_is_rejected(saved, message):
    graph = Mock()
    graph.get_state.return_value = saved
    with pytest.raises(ValueError, match=message):
        get_pending_review(graph, "approval-demo")
    graph.invoke.assert_not_called()


@pytest.mark.parametrize("action", ["approved", "rejected"])
def test_submit_targets_saved_interrupt_with_server_identity(action):
    graph = Mock()
    graph.get_state.return_value = snapshot()
    expected = {"proposal": {"approval_status": action}}
    graph.invoke.return_value = expected
    result = submit_review(graph, "approval-demo", action, " reviewer-demo ")
    assert result is expected
    graph.invoke.assert_called_once()
    command = graph.invoke.call_args.args[0]
    assert command.resume == {"interrupt-1": {
        "decision": action, "reviewer_id": "reviewer-demo",
    }}
    assert graph.invoke.call_args.kwargs == {
        "config": {"configurable": {"thread_id": "approval-demo"}},
    }


@pytest.mark.parametrize("action,reviewer", [
    ("pending", "demo"), (None, "demo"), (True, "demo"),
    ("approved", None), ("approved", ""), ("rejected", "  "), ("approved", 123),
])
def test_invalid_submit_does_not_access_graph(action, reviewer):
    graph = Mock()
    with pytest.raises(ValueError):
        submit_review(graph, "approval-demo", action, reviewer)
    graph.get_state.assert_not_called()
    graph.invoke.assert_not_called()


@pytest.mark.parametrize("saved", [
    SimpleNamespace(values={}), snapshot(status="approved"), snapshot(status="rejected"),
    snapshot(next_nodes=()), snapshot(ids=()), snapshot(ids=("one", "two")),
])
def test_submit_does_not_resume_unavailable_task(saved):
    graph = Mock()
    graph.get_state.return_value = saved
    with pytest.raises(ValueError):
        submit_review(graph, "approval-demo", "approved", "reviewer-demo")
    graph.invoke.assert_not_called()
