# 模块职责：真实模型主链验收；业务写入隔离在临时库，不调用飞书。
"""Opt-in real model/Milvus + HTTP workflow, with all business writes in temp DBs."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description="真实模型与 Milvus 冒烟；业务/审核数据只写临时库，不同步飞书")
    parser.add_argument("--live", action="store_true", required=True)
    parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="businessflow-smoke-") as directory:
        root = Path(directory)
        os.environ["DATABASE_URL"] = f"sqlite:///{(root / 'business.db').as_posix()}"
        from fastapi.testclient import TestClient
        from app.db.session import engine
        from app.db.init_all import initialize_all
        from app.services.review_runtime import open_review_graph
        from app.main import app
        initialize_all()
        review_db = root / "review.db"
        review_db.touch()

        @contextmanager
        def review_factory():
            with open_review_graph(review_db) as graph:
                yield graph

        employee = {"X-Demo-User": "employee-demo-001"}
        manager = {"X-Demo-User": "reviewer-demo-001"}
        try:
            with patch("app.services.review_runtime.open_review_graph", review_factory), \
                 patch("app.api.approvals.open_persistent_review_graph", review_factory), TestClient(app) as client:
                def request(method, url, headers=employee, **kwargs):
                    response = client.request(method, url, headers=headers, **kwargs)
                    if response.status_code >= 400:
                        raise RuntimeError("HTTP stage failed: " + url)
                    return response.json()

                query_id = request("POST", "/api/v1/agent/tasks", json={"user_input": "查询订单 BF2026001 的状态"})["task_id"]
                query = request("POST", f"/api/v1/agent/tasks/{query_id}/run")
                assert query["status"] == "completed", "query task did not complete"
                task_id = request("POST", "/api/v1/agent/tasks", json={"user_input": "查询订单 BF2026001，如果超期未发货，请根据政策生成待审核工单建议"})["task_id"]
                pending = request("POST", f"/api/v1/agent/tasks/{task_id}/run")
                assert pending["status"] == "waiting_approval", "proposal did not reach approval"
                approval = pending["approval_id"]
                request("POST", f"/api/v1/approvals/{approval}/decision", headers=manager, json={"decision": "approved"})
                created = request("POST", f"/api/v1/approvals/{approval}/execute", headers=manager)
                repeated = request("POST", f"/api/v1/approvals/{approval}/execute", headers=manager)
                assert repeated["reused"] and repeated["ticket"]["ticket_id"] == created["ticket"]["ticket_id"]
                finished = request("POST", f"/api/v1/agent/tasks/{task_id}/refresh")
                assert finished["status"] == "completed" and finished["ticket_id"]
                events = request("GET", f"/api/v1/agent/tasks/{task_id}/events")
                assert any(event["event_type"] == "tool_completed" for event in events)
                print(json.dumps({"result": "passed", "query": "completed", "proposal": "waiting_approval",
                                  "approval": "approved", "ticket": "completed", "reused": True,
                                  "events": len(events), "storage": "temporary SQLite only", "feishu": "not called"}))
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
