# 模块职责：数据库引擎及会话依赖；事务提交责任由调用服务持有。
from collections.abc import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.core.config import get_settings

class Base(DeclarativeBase):
    pass

# Engine creation does not create tables or open a connection.
_url = get_settings().database_url
engine = create_engine(_url, connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine)

def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
