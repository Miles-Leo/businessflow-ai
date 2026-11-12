from unittest.mock import patch
import pytest
from app.core.config import Settings
from app.integrations.feishu import FeishuClient, FeishuError, feishu_text


def test_record_lookup_pages_and_exact_text_match():
    api = FeishuClient(Settings(_env_file=None, feishu_bitable_app_token="base", feishu_bitable_table_id="tbl"))
    record = {"record_id": "rec-1", "fields": {"工单编号": [{"type": "text", "text": "TK-demo"}]}}
    with patch.object(api, "get_tenant_access_token", return_value="token"), patch("app.integrations.feishu.httpx.Client") as factory:
        response = factory.return_value.__enter__.return_value.get.return_value
        response.json.side_effect = [
            {"code": 0, "data": {"items": [{"record_id": "other", "fields": {"工单编号": "TK"}}], "has_more": True, "page_token": "p2"}},
            {"code": 0, "data": {"items": [record], "has_more": False}},
        ]
        assert api.find_records_by_ticket("TK-demo") == [record]


def test_schema_preflight_requires_all_text_columns():
    api = FeishuClient()
    with patch.object(api, "list_fields", return_value=[{"field_name": "工单编号", "type": 2}]):
        with pytest.raises(FeishuError):
            api.validate_ticket_fields({"工单编号": "TK"})


@pytest.mark.parametrize("value,expected", [("text", "text"), ([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}], "ab"), (None, None)])
def test_remote_text_normalization(value, expected):
    assert feishu_text(value) == expected
