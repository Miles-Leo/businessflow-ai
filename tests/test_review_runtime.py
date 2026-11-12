from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.approvals import open_review_graph as open_api_review_graph
from app.services.approval import start_review, submit_review
from app.services.review_runtime import ReviewDatabaseNotInitialized, open_review_graph


def test_missing_database_is_not_created(tmp_path):
    database = tmp_path / "missing.db"
    with pytest.raises(ReviewDatabaseNotInitialized):
        with open_review_graph(database):
            pytest.fail("不应打开未初始化的数据库")
    assert not database.exists()


def test_review_survives_reopening(tmp_path):
    database = tmp_path / "checkpoints.db"
    database.touch()  # 测试显式准备数据库文件。
    proposal = {
        "order_id": "BF2026001", "issue_type": "shipping_delay",
        "description": "测试建议", "policy_sources": [],
        "checked_at": "2026-11-08T08:00:00+00:00", "approval_status": "pending",
    }
    with open_review_graph(database) as graph:
        started = start_review(graph, proposal)
        assert started["approval_status"] == "pending"

    with open_review_graph(database) as graph:
        config = {"configurable": {"thread_id": started["approval_id"]}}
        assert graph.get_state(config).next == ("review",)
        decided = submit_review(graph, started["approval_id"], "approved", "reviewer-demo-001")
        assert decided["proposal"]["approval_status"] == "approved"

    with open_review_graph(database) as graph:
        saved = graph.get_state(config)
        assert saved.next == ()
        assert saved.values["reviewer_id"] == "reviewer-demo-001"


def test_api_preserves_uninitialized_database_response():
    with patch("app.api.approvals.open_persistent_review_graph", side_effect=
               ReviewDatabaseNotInitialized("审核数据库尚未初始化，请先运行审核演示启动脚本")):
        with pytest.raises(HTTPException) as exc:
            with open_api_review_graph():
                pytest.fail("不应获得审核图")
    assert exc.value.status_code == 503
    assert exc.value.detail == "审核数据库尚未初始化，请先运行审核演示启动脚本"
