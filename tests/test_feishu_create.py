from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from app.core.config import Settings
from app.integrations.feishu import FeishuClient, FeishuError, FeishuWriteUnknown


@pytest.fixture
def api():
    return FeishuClient(Settings(_env_file=None, feishu_bitable_app_token="base-demo", feishu_bitable_table_id="tbl-demo"))


def test_create_sends_stable_id_and_returns_record_id(api):
    request_id = str(uuid4())
    with patch.object(api, "get_tenant_access_token", return_value="test-token"), patch("app.integrations.feishu.httpx.Client") as factory:
        client = factory.return_value.__enter__.return_value
        client.post.return_value.status_code = 200
        client.post.return_value.json.return_value = {"code": 0, "data": {"record": {"record_id": "rec-demo"}}}
        assert api.create_record({"工单编号": "TK-demo"}, request_id) == "rec-demo"
        client.post.assert_called_once_with(
            "https://open.feishu.cn/open-apis/bitable/v1/apps/base-demo/tables/tbl-demo/records",
            headers={"Authorization": "Bearer test-token"}, params={"client_token": request_id}, json={"fields": {"工单编号": "TK-demo"}},
        )
        factory.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("fields,identifier", [({}, "bad"), ({"工单编号": None}, str(uuid4())), ({"工单编号": "TK"}, "bad")])
def test_invalid_input_skips_auth(api, fields, identifier):
    with patch.object(api, "get_tenant_access_token") as auth:
        with pytest.raises(ValueError):
            api.create_record(fields, identifier)
    auth.assert_not_called()


def test_timeout_is_unknown_and_not_retried(api):
    with patch.object(api, "get_tenant_access_token", return_value="test-token"), patch("app.integrations.feishu.httpx.Client") as factory:
        client = factory.return_value.__enter__.return_value
        client.post.side_effect = httpx.ReadTimeout("secret")
        with pytest.raises(FeishuWriteUnknown) as error:
            api.create_record({"工单编号": "TK"}, str(uuid4()))
        assert "secret" not in str(error.value)
        client.post.assert_called_once()


@pytest.mark.parametrize("payload", [{"code": 0}, [], {"code": 0, "data": {"record": {"record_id": ""}}}])
def test_success_without_record_id_is_unknown(api, payload):
    with patch.object(api, "get_tenant_access_token", return_value="test-token"), patch("app.integrations.feishu.httpx.Client") as factory:
        response = factory.return_value.__enter__.return_value.post.return_value
        response.status_code = 200
        response.json.return_value = payload
        with pytest.raises(FeishuWriteUnknown):
            api.create_record({"工单编号": "TK"}, str(uuid4()))


def test_permission_rejection_hides_payload(api):
    with patch.object(api, "get_tenant_access_token", return_value="test-token"), patch("app.integrations.feishu.httpx.Client") as factory:
        response = factory.return_value.__enter__.return_value.post.return_value
        response.status_code = 403
        with pytest.raises(FeishuError) as error:
            api.create_record({"工单编号": "TK"}, str(uuid4()))
        assert not isinstance(error.value, FeishuWriteUnknown)
        response.json.assert_not_called()


def test_business_failure_not_reported_as_success(api):
    with patch.object(api, "get_tenant_access_token", return_value="test-token"), patch("app.integrations.feishu.httpx.Client") as factory:
        response = factory.return_value.__enter__.return_value.post.return_value
        response.status_code = 200
        response.json.return_value = {"code": 1254302, "msg": "secret"}
        with pytest.raises(FeishuError) as error:
            api.create_record({"工单编号": "TK"}, str(uuid4()))
        assert "secret" not in str(error.value)
