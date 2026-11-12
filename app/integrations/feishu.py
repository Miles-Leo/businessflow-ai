# 模块职责：飞书 HTTP 适配器；业务授权、幂等与未知结果处理由上层服务负责。
import re
from uuid import UUID
import httpx

from app.core.config import Settings, get_settings


class FeishuError(RuntimeError):
    """Safe external-service error without provider payloads or credentials."""


class FeishuWriteUnknown(FeishuError):
    """The request may have reached Feishu; do not blindly submit a new write."""


def build_ticket_fields(ticket: dict[str, object]) -> dict[str, str]:
    """Map JSON-mode ticket data to the seven text columns of the demo table."""
    mapping = {
        "工单编号": "ticket_id",
        "审核编号": "approval_id",
        "订单编号": "order_id",
        "问题类型": "issue_type",
        "工单描述": "description",
        "工单状态": "status",
        "创建时间": "created_at",
    }
    fields = {}
    for column, key in mapping.items():
        value = ticket.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"工单字段 {key} 必须是非空字符串")
        fields[column] = value
    return fields


class FeishuClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings if settings is not None else get_settings()

    def update_record_status(self, record_id: str, status: str) -> str:
        """Idempotent assignment to an existing record; no record creation."""
        if not re.fullmatch(r"[A-Za-z0-9_-]+", record_id) or status not in {"open", "in_progress", "closed"}:
            raise FeishuError("飞书记录或状态无效")
        app, table = self._settings.feishu_bitable_app_token, self._settings.feishu_bitable_table_id
        if not all(re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in (app, table)):
            raise FeishuError("飞书表格配置无效")
        token = self.get_tenant_access_token()
        try:
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                response = client.put(
                    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app}/tables/{table}/records/{record_id}",
                    headers={"Authorization": f"Bearer {token}"}, json={"fields": {"工单状态": status}},
                )
                if response.status_code in {400, 401, 403, 404}:
                    raise FeishuError("飞书拒绝更新工单状态")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise FeishuWriteUnknown("飞书更新结果未知，请先核对记录") from None
        if not isinstance(payload, dict) or type(payload.get("code")) is not int:
            raise FeishuWriteUnknown("飞书更新响应无效")
        if payload["code"] != 0:
            raise FeishuError("飞书未接受状态更新")
        record = (payload.get("data") or {}).get("record") or {}
        if record.get("record_id") != record_id:
            raise FeishuWriteUnknown("飞书更新记录编号未确认")
        return record_id

    def validate_ticket_fields(self, fields: dict[str, str]) -> None:
        available = {field["field_name"]: field["type"] for field in self.list_fields()}
        if any(available.get(name) != 1 for name in fields):
            raise FeishuError("测试表缺少所需文本字段，或字段类型不符")

    def find_records_by_ticket(self, ticket_id: str) -> list[dict]:
        """Read all pages (bounded for demo) and match exact text, not a view filter."""
        app_token = self._settings.feishu_bitable_app_token
        table_id = self._settings.feishu_bitable_table_id
        if not all(re.fullmatch(r"[A-Za-z0-9_-]+", v) for v in (app_token, table_id)):
            raise FeishuError("飞书表格配置无效")
        token = self.get_tenant_access_token()
        found, seen = [], set()
        params = {"page_size": 500}
        try:
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                for _ in range(100):
                    response = client.get(
                        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                        headers={"Authorization": f"Bearer {token}"}, params=params.copy(),
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0:
                        raise FeishuError("飞书记录查询被拒绝，请检查读取权限")
                    data = payload.get("data")
                    if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
                        raise FeishuError("飞书记录响应无效")
                    for item in data.get("items", []):
                        if not isinstance(item, dict) or not isinstance(item.get("fields"), dict) or not isinstance(item.get("record_id"), str):
                            raise FeishuError("飞书记录响应无效")
                        if feishu_text(item["fields"].get("工单编号")) == ticket_id:
                            found.append(item)
                    more = data.get("has_more", False)
                    if type(more) is not bool:
                        raise FeishuError("飞书记录分页无效")
                    if not more:
                        return found
                    cursor = data.get("page_token")
                    if not isinstance(cursor, str) or not cursor or cursor in seen:
                        raise FeishuError("飞书记录分页游标无效")
                    seen.add(cursor)
                    params["page_token"] = cursor
                raise FeishuError("飞书记录查询超过演示分页上限")
        except (httpx.HTTPError, ValueError):
            raise FeishuError("飞书记录查询失败，请检查网络与权限") from None

    def create_record(self, fields: dict[str, str], client_token: str) -> str:
        """Low-level write adapter, not an authorization or durable deduplication layer.

        Caller must persist the request UUID before calling and reuse it for the
        same immutable payload/target. No automatic retries are performed here.
        """
        if not isinstance(client_token, str):
            raise ValueError("写入请求标识必须是 UUID 字符串")
        try:
            UUID(client_token)
        except ValueError:
            raise ValueError("写入请求标识必须是 UUID 字符串") from None
        if not isinstance(fields, dict) or not fields or not all(
            isinstance(k, str) and k.strip() and isinstance(v, str) for k, v in fields.items()
        ):
            raise ValueError("飞书写入字段必须是非空的文本字段字典")
        app_token = self._settings.feishu_bitable_app_token
        table_id = self._settings.feishu_bitable_table_id
        if not all(re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in (app_token, table_id)):
            raise FeishuError("飞书多维表格标识未配置或格式无效")
        access_token = self.get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        try:
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                response = client.post(
                    url, headers={"Authorization": f"Bearer {access_token}"},
                    params={"client_token": client_token}, json={"fields": fields},
                )
                if response.status_code in (400, 401, 403, 404):
                    raise FeishuError("飞书拒绝新增记录，请检查权限、表格与字段配置")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise FeishuWriteUnknown("飞书写入结果未知，请先核对远端记录，勿使用新标识重复提交") from None
        if not isinstance(payload, dict) or type(payload.get("code")) is not int:
            raise FeishuWriteUnknown("飞书写入响应无效，需核对远端记录")
        if payload["code"] != 0:
            raise FeishuError("飞书新增记录未成功，请检查权限和字段配置")
        data = payload.get("data")
        record = data.get("record") if isinstance(data, dict) else None
        record_id = record.get("record_id") if isinstance(record, dict) else None
        if not isinstance(record_id, str) or not record_id.strip():
            raise FeishuWriteUnknown("飞书未返回有效记录 ID，需核对远端记录")
        return record_id

    def get_tenant_access_token(self) -> str:
        app_id = self._settings.feishu_app_id
        secret = self._settings.feishu_app_secret.get_secret_value()
        if not app_id.strip() or not secret.strip():
            raise FeishuError("飞书应用凭证未配置")

        # Do not log requests/responses or expose upstream error messages.
        # No redirect following: credentials must only reach this fixed endpoint.
        try:
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                response = client.post(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    json={"app_id": app_id, "app_secret": secret},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError):
            raise FeishuError("飞书访问令牌获取失败，请检查网络和应用配置") from None

        if not isinstance(data, dict) or type(data.get("code")) is not int or data["code"] != 0:
            raise FeishuError("飞书访问令牌获取失败，请检查应用状态及凭证")
        token = data.get("tenant_access_token")
        if not isinstance(token, str) or not token.strip():
            raise FeishuError("飞书未返回有效的访问令牌")
        return token

    def list_fields(self) -> list[dict]:
        app_token = self._settings.feishu_bitable_app_token
        table_id = self._settings.feishu_bitable_table_id
        if not all(re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in (app_token, table_id)):
            raise FeishuError("飞书多维表格标识未配置或格式无效")
        token = self.get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
        fields = []
        page_token = None
        seen_tokens = set()
        try:
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                for _ in range(100):
                    params = {"page_size": 100}
                    if page_token is not None:
                        params["page_token"] = page_token
                    response = client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0:
                        raise FeishuError("飞书字段查询失败，请检查应用权限与表格访问权限")
                    data = payload.get("data")
                    if not isinstance(data, dict):
                        raise FeishuError("飞书字段响应结构无效")
                    items = data.get("items", [])
                    if not isinstance(items, list) or not all(
                        isinstance(item, dict) and isinstance(item.get("field_name"), str)
                        and type(item.get("type")) is int for item in items
                    ):
                        raise FeishuError("飞书字段响应结构无效")
                    fields.extend(items)
                    has_more = data.get("has_more", False)
                    if type(has_more) is not bool:
                        raise FeishuError("飞书字段分页状态无效")
                    if not has_more:
                        return fields
                    page_token = data.get("page_token")
                    if not isinstance(page_token, str) or not page_token.strip() or page_token in seen_tokens:
                        raise FeishuError("飞书字段分页游标无效")
                    seen_tokens.add(page_token)
                raise FeishuError("飞书字段分页超过安全上限")
        except (httpx.HTTPError, ValueError):
            raise FeishuError("飞书字段查询失败，请检查网络和应用配置") from None


def feishu_text(value) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(v, dict) and v.get("type") == "text" and isinstance(v.get("text"), str) for v in value):
        return "".join(v["text"] for v in value)
    return None
