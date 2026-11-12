# 模块职责：请求上下文内的安全执行轨迹；不记录提示词、工具载荷或凭证。
"""Request-local, payload-free execution trace; graph workers copy contextvars."""
from contextlib import contextmanager
from contextvars import ContextVar

_events = ContextVar("businessflow_trace", default=None)
ALLOWED_NAMES = {"lookup_order", "lookup_customer", "search_policy", "parse", "query", "proposal", "review", "unsupported", "missing_order_id", "sync_ticket"}


def record_step(name: str, failed: bool = False, *, tool: bool = False):
    events = _events.get()
    if events is not None and name in ALLOWED_NAMES:
        events.append((name, bool(failed), bool(tool)))


@contextmanager
def capture_trace():
    events = []
    token = _events.set(events)
    try:
        yield events
    finally:
        _events.reset(token)
