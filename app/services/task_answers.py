# 模块职责：旧任务文本兼容；仅更新进度段，不覆盖原始查询说明。
"""Keep original query evidence while replacing the changing task outcome."""
PROGRESS_SEPARATOR = "\n\n处理进度：\n"


def with_progress(answer: str | None, outcome: str) -> str:
    if answer and answer.startswith("订单查询结果"):
        return answer.split(PROGRESS_SEPARATOR, 1)[0] + PROGRESS_SEPARATOR + outcome
    return outcome
