# 模块职责：SQLAlchemy 持久化模型；UTC 存储、唯一约束与业务状态约束在此定义。
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, String, Text, JSON, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator
from app.db.session import Base


class UTCDateTime(TypeDecorator):
    """SQLite stores naive UTC; application always receives aware UTC."""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone-aware datetime required")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Customer(Base):
    __tablename__ = "customers"
    customer_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    contact: Mapped[str] = mapped_column(String(200))


class Order(Base):
    __tablename__ = "orders"
    order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    promised_ship_at: Mapped[datetime] = mapped_column(UTCDateTime())
    shipped_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(32))


class Ticket(Base):
    __tablename__ = "tickets"
    ticket_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(128), unique=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"))
    issue_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    reviewer_id: Mapped[str] = mapped_column(String(128))
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    executed_by: Mapped[str] = mapped_column(String(128))
    policy_sources: Mapped[list] = mapped_column(JSON)


class TicketExecution(Base):
    __tablename__ = "ticket_executions"
    approval_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    ticket_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class FeishuSync(Base):
    __tablename__ = "feishu_syncs"
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.ticket_id"), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    app_token: Mapped[str] = mapped_column(String(128))
    table_id: Mapped[str] = mapped_column(String(128))
    fields: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempts: Mapped[int] = mapped_column(default=0)
    requested_by: Mapped[str] = mapped_column(String(128))
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    __table_args__ = (CheckConstraint(
        "status IN ('created','running','waiting_approval','rejected','executing','completed','failed')",
        name="ck_agent_task_status",
    ),)
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    user_input: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="created")
    # Approval state is in a separate checkpoint DB; no cross-DB foreign key.
    approval_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.ticket_id"), nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (UniqueConstraint("task_id", "event_key", name="uq_task_event_key"),)
    event_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("agent_tasks.task_id"), index=True)
    event_key: Mapped[str] = mapped_column(String(100))
    step_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(512), unique=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    collection_name: Mapped[str] = mapped_column(String(128))
    chunk_count: Mapped[int] = mapped_column()
    imported_by: Mapped[str] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class TicketStatusChange(Base):
    __tablename__ = "ticket_status_changes"
    change_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.ticket_id"), index=True)
    previous_status: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    changed_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
