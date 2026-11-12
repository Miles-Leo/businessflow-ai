# 模块职责：显式建立同步记录表；不调用飞书远端接口。
"""Explicit additive sync table initialization; no remote calls."""
from app.db.models import FeishuSync
from app.db.session import engine

if __name__ == "__main__":
    FeishuSync.__table__.create(engine, checkfirst=True)
    print("Feishu sync table initialized; existing records preserved.")
