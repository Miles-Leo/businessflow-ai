# 模块职责：显式建立 MVP 所需表与审核检查点；保留已有数据。
"""Explicit additive setup for MVP; never run from FastAPI startup."""
from app.db.models import KnowledgeDocument
from app.db.session import engine
from app.db.seed import initialize_demo_data
from app.db.init_tasks import initialize_tasks


def initialize_all(bind=engine):
    initialize_demo_data(bind)
    initialize_tasks(bind)
    KnowledgeDocument.__table__.create(bind, checkfirst=True)


def initialize_review_database():
    from pathlib import Path
    from langgraph.checkpoint.sqlite import SqliteSaver
    database = Path(__file__).resolve().parents[2] / "review_checkpoints.db"
    with SqliteSaver.from_conn_string(str(database)) as saver:
        saver.setup()


if __name__ == "__main__":
    initialize_all()
    initialize_review_database()
    print("MVP tables initialized; existing records preserved.")
