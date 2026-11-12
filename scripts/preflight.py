# 模块职责：只读启动预检；不初始化数据库、不调用模型、不创建业务数据。
"""Read-only local delivery checks; no model calls, initialization or data writes."""
import argparse
import json
from pathlib import Path
import socket
import sqlite3
import sys
from urllib.parse import urlsplit

import httpx
from sqlalchemy.engine import make_url
from app.core.config import get_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    settings = get_settings()
    checks = []

    def check(name, operation):
        try:
            passed = bool(operation())
        except Exception:
            passed = False
        checks.append({'check': name, 'passed': passed})

    check('python_3_13', lambda: sys.version_info[:2] == (3, 13))
    check('model_key_configured_not_validated', lambda: settings.dashscope_api_key.get_secret_value().strip())

    def schema_ready():
        url = make_url(settings.database_url)
        if url.get_backend_name() != 'sqlite' or not url.database:
            return False
        path = Path(url.database).resolve()
        if not path.is_file():
            return False
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as connection:
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            columns = {r[1] for r in connection.execute('PRAGMA table_info(agent_tasks)')}
        return {'orders', 'customers', 'tickets', 'agent_tasks', 'task_events'} <= tables and {'answer', 'result'} <= columns

    check('business_sqlite_schema_read_only', schema_ready)
    check('review_checkpoint_file_exists', lambda: (Path(__file__).resolve().parents[1] / 'review_checkpoints.db').is_file())

    def milvus_port():
        uri = urlsplit(settings.milvus_uri)
        with socket.create_connection((uri.hostname, uri.port or 19530), timeout=3):
            return True

    check('milvus_port_reachable_not_collection_validation', milvus_port)
    with httpx.Client(timeout=5, trust_env=False) as client:
        check('fastapi_health', lambda: client.get(args.url.rstrip('/') + '/health').json().get('status') == 'ok')
        check('frontend_http_200', lambda: client.get(args.url.rstrip('/') + '/app/').status_code == 200)
    report = {'kind': 'read_only_preflight', 'checks': checks, 'passed': all(c['passed'] for c in checks),
              'limitations': '不验证模型Key有效性、Milvus集合/政策内容、审核库结构或飞书权限；不调用模型或业务写入。'}
    content = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding='utf-8')
    print(content)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
