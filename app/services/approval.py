# 模块职责：审核状态校验、精确恢复与新审核创建；不执行正式工单写入。
from uuid import uuid4

from langgraph.types import Command


class ReviewNotFound(ValueError):
    pass


class ReviewConflict(ValueError):
    pass


def get_pending_review(graph, approval_id: str):
    config = {
        "configurable": {
            "thread_id": approval_id,
        }
    }




    snapshot = graph.get_state(config)
    if not snapshot.values:
        raise ReviewNotFound(f"审批任务 {approval_id} 不存在")

    if snapshot.values["proposal"]["approval_status"] != "pending":
        raise ReviewConflict(f"审批任务 {approval_id} 已完成")

    if "review" not in snapshot.next:
        raise ReviewConflict("任务当前不在等待审核节点")

    interrupts = []

    for task in snapshot.tasks:

        interrupts.extend(task.interrupts)

    if len(interrupts) != 1:
        raise ReviewConflict("未找到唯一的审核中断")

    return snapshot, config, interrupts[0].id



def submit_review(
    graph,
    approval_id: str,
    action: str,
    reviewer_id: str,
):



    if action not in ["approved", "rejected"]:
        raise ValueError("审批操作必须是 approved 或 rejected")

    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        raise ValueError("审核人必须是非空字符串")

    snapshot, config, interrupt_id = get_pending_review(
        graph, approval_id
    )

    decision = {
        "decision": action,
        "reviewer_id": reviewer_id.strip(),
    }

    result = graph.invoke(
        Command(resume={interrupt_id: decision}),
        config=config,
    )

    return result


def start_review(graph, proposal, *, approval_id: str | None = None):




    approval_id = approval_id or str(uuid4())
    state = {
        "proposal": proposal,
        "reviewer_id": None,
        "reviewed_at": None,
    }
    config = {
        "configurable": {
            "thread_id": approval_id,
        }
    }

    result = graph.invoke(state, config=config)

    if not result.get("__interrupt__"):
        raise ValueError("审核任务未进入等待状态")

    return {
        "approval_id": approval_id,
        "approval_status": result["proposal"]["approval_status"],
    }
