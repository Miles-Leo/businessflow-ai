# 模块职责：任务表的可重复增量升级；仅添加缺失表或列，不删除历史记录。
"""Explicit additive task table setup; no agent execution or sample tasks."""
from app.db.models import AgentTask, TaskEvent
from app.db.session import engine
from sqlalchemy import inspect


def initialize_tasks(bind):
    """Explicit, repeatable additive setup; preserve all existing rows."""
    AgentTask.__table__.create(bind, checkfirst=True)
    with bind.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("agent_tasks")}
        if "answer" not in columns:
            connection.exec_driver_sql("ALTER TABLE agent_tasks ADD COLUMN answer TEXT")
        if "result" not in columns:
            connection.exec_driver_sql("ALTER TABLE agent_tasks ADD COLUMN result JSON")
    TaskEvent.__table__.create(bind, checkfirst=True)
    with bind.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("task_events")}
        if "step_name" not in columns:
            connection.exec_driver_sql("ALTER TABLE task_events ADD COLUMN step_name VARCHAR(40)")


if __name__ == "__main__":
    initialize_tasks(engine)
    print("Agent task table initialized; existing data preserved.")
