# 模块职责：独立审核图与 SQLite Checkpointer 生命周期；只提供单进程锁。
"""审核图与 SQLite 检查点的公共运行入口。"""

from contextlib import contextmanager
from pathlib import Path
from threading import Lock

# Shared by task orchestration and approval APIs in the single-process demo.
review_lock = Lock()


class ReviewDatabaseNotInitialized(RuntimeError):
    """审核检查点数据库尚未显式初始化。"""


@contextmanager
def open_review_graph(database: Path | None = None):
    """在上下文内使用审核图，退出时关闭检查点连接。"""
    if database is None:
        database = Path(__file__).resolve().parents[2] / "review_checkpoints.db"
    if not database.is_file():
        raise ReviewDatabaseNotInitialized(
            "审核数据库尚未初始化，请先运行审核演示启动脚本"
        )

    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import END, START, StateGraph
    from app.ai.review import wait_for_review
    from app.ai.state import TicketReviewState

    with SqliteSaver.from_conn_string(str(database)) as saver:
        builder = StateGraph(TicketReviewState)
        builder.add_node("review", wait_for_review)
        builder.add_edge(START, "review")
        builder.add_edge("review", END)
        yield builder.compile(checkpointer=saver)
