# 模块职责：从权威检查点构建审核列表；先枚举后读取，避免游标锁重入。
"""Reviewer inbox derived from authoritative checkpoint state, including old reviews."""
from datetime import datetime, timezone

from pydantic import ValidationError

from app.schemas.approval import ApprovalDetailResponse, ApprovalListItem, ApprovalListResponse


def checkpoint_time(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


def list_approvals(graph, *, status="pending", offset=0, limit=20, query=""):
    threads = {}
    # Finish iterating before calling get_state: SqliteSaver.list holds its cursor lock.
    for checkpoint in graph.checkpointer.list(None):
        config = checkpoint.config.get("configurable", {})
        thread_id = config.get("thread_id")
        if not thread_id or config.get("checkpoint_ns", ""):
            continue
        times = threads.setdefault(thread_id, [])
        timestamp = checkpoint_time(checkpoint.checkpoint.get("ts"))
        if timestamp is not None:
            times.append(timestamp)

    items, unavailable = [], 0
    needle = query.strip().casefold()
    for approval_id, times in threads.items():
        snapshot = graph.get_state({"configurable": {"thread_id": approval_id}})
        try:
            review = ApprovalDetailResponse.model_validate({"approval_id": approval_id, **snapshot.values})
        except (ValidationError, TypeError):
            unavailable += 1
            continue
        proposal = review.proposal
        if proposal.approval_status == "pending" and (
            "review" not in snapshot.next or not any(task.interrupts for task in snapshot.tasks)
        ):
            unavailable += 1
            continue
        if status != "all" and proposal.approval_status != status:
            continue
        if needle and needle not in approval_id.casefold() and needle not in proposal.order_id.casefold():
            continue
        items.append(ApprovalListItem(
            approval_id=approval_id, order_id=proposal.order_id, issue_type=proposal.issue_type,
            description=proposal.description[:180], approval_status=proposal.approval_status,
            submitted_at=min(times) if times else None, updated_at=max(times) if times else None,
        ))
    # Oldest first: do not bury a long-waiting suggestion under newer submissions.
    items.sort(key=lambda item: (item.submitted_at or datetime.max.replace(tzinfo=timezone.utc), item.approval_id))
    return ApprovalListResponse(items=items[offset:offset + limit], total=len(items),
                                offset=offset, limit=limit, unavailable_count=unavailable)
