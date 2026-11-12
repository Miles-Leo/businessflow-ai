from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.integrations.feishu import FeishuClient, FeishuError


@pytest.fixture
def settings():
    return Settings(_env_file=None, feishu_app_id="demo-app", feishu_app_secret=SecretStr("test-secret"))


def test_token_success_uses_config_and_closes_client(settings):
    with patch("app.integrations.feishu.httpx.Client") as factory:
        client = factory.return_value.__enter__.return_value
        client.post.return_value.json.return_value = {"code": 0, "tenant_access_token": "test-token"}
        result = FeishuClient(settings).get_tenant_access_token()
    assert result == "test-token"
    factory.assert_called_once_with(timeout=20, follow_redirects=False)
    client.post.assert_called_once_with(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": "demo-app", "app_secret": "test-secret"},
    )
    client.post.return_value.raise_for_status.assert_called_once()
    factory.return_value.__exit__.assert_called_once()


def test_construction_does_not_send_request(settings):
    with patch("app.integrations.feishu.httpx.Client") as factory:
        FeishuClient(settings)
    factory.assert_not_called()


@pytest.mark.parametrize("field", ["feishu_app_id", "feishu_app_secret"])
def test_missing_credentials_skip_network(settings, field):
    setattr(settings, field, SecretStr("") if field.endswith("secret") else "")
    with patch("app.integrations.feishu.httpx.Client") as factory:
        with pytest.raises(FeishuError, match="未配置"):
            FeishuClient(settings).get_tenant_access_token()
    factory.assert_not_called()


@pytest.mark.parametrize("payload", [
    {"code": 1, "msg": "test-secret"}, {}, [],
    {"code": False, "tenant_access_token": "test-token"},
    {"code": 0}, {"code": 0, "tenant_access_token": "  "},
    {"code": 0, "tenant_access_token": 123},
])
def test_invalid_provider_response_is_safe(settings, payload):
    with patch("app.integrations.feishu.httpx.Client") as factory:
        factory.return_value.__enter__.return_value.post.return_value.json.return_value = payload
        with pytest.raises(FeishuError) as error:
            FeishuClient(settings).get_tenant_access_token()
    assert "test-secret" not in str(error.value)
    assert "test-token" not in str(error.value)


@pytest.mark.parametrize("failure", [httpx.ConnectError("test-secret"), httpx.ReadTimeout("test-token")])
def test_network_failure_is_safe_and_closes_client(settings, failure):
    with patch("app.integrations.feishu.httpx.Client") as factory:
        factory.return_value.__enter__.return_value.post.side_effect = failure
        with pytest.raises(FeishuError) as error:
            FeishuClient(settings).get_tenant_access_token()
    assert "test-secret" not in str(error.value)
    assert "test-token" not in str(error.value)
    factory.return_value.__exit__.assert_called_once()


def test_bad_http_status_skips_json(settings):
    with patch("app.integrations.feishu.httpx.Client") as factory:
        response = factory.return_value.__enter__.return_value.post.return_value
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "test-secret", request=httpx.Request("POST", "https://example.invalid"), response=httpx.Response(403),
        )
        with pytest.raises(FeishuError):
            FeishuClient(settings).get_tenant_access_token()
        response.json.assert_not_called()


def test_invalid_json_is_safe(settings):
    with patch("app.integrations.feishu.httpx.Client") as factory:
        factory.return_value.__enter__.return_value.post.return_value.json.side_effect = ValueError("test-secret")
        with pytest.raises(FeishuError):
            FeishuClient(settings).get_tenant_access_token()


def field_client(settings):
    settings.feishu_bitable_app_token = "base-demo"
    settings.feishu_bitable_table_id = "tbl-demo"
    return FeishuClient(settings)


def test_list_fields_merges_pages_and_passes_cursor(settings):
    api = field_client(settings)
    first = {"field_name": "工单编号", "type": 1}
    second = {"field_name": "订单编号", "type": 1}
    with patch.object(api, "get_tenant_access_token", return_value="test-token"), patch("app.integrations.feishu.httpx.Client") as factory:
        client = factory.return_value.__enter__.return_value
        client.get.return_value.json.side_effect = [
            {"code": 0, "data": {"items": [first], "has_more": True, "page_token": "next"}},
            {"code": 0, "data": {"items": [second], "has_more": False}},
        ]
        assert api.list_fields() == [first, second]
        calls = client.get.call_args_list
        assert calls[0].kwargs["params"] == {"page_size": 100}
        assert calls[1].kwargs["params"] == {"page_size": 100, "page_token": "next"}
        assert calls[0].kwargs["headers"] == {"Authorization": "Bearer test-token"}
        factory.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("data", [
    {"items": [], "has_more": True},
    {"items": "invalid"},
    {"items": [{}]},
    {"items": [], "has_more": "true"},
])
def test_field_malformed_response_is_rejected(settings, data):
    api = field_client(settings)
    with patch.object(api, "get_tenant_access_token", return_value="test-token"), patch("app.integrations.feishu.httpx.Client") as factory:
        factory.return_value.__enter__.return_value.get.return_value.json.return_value = {"code": 0, "data": data}
        with pytest.raises(FeishuError):
            api.list_fields()


def test_repeated_cursor_does_not_loop(settings):
    api = field_client(settings)
    with patch.object(api, "get_tenant_access_token", return_value="test-token"), patch("app.integrations.feishu.httpx.Client") as factory:
        client = factory.return_value.__enter__.return_value
        client.get.return_value.json.return_value = {"code": 0, "data": {"items": [], "has_more": True, "page_token": "same"}}
        with pytest.raises(FeishuError, match="游标"):
            api.list_fields()
        assert client.get.call_count == 2


def test_missing_table_configuration_skips_auth(settings):
    settings.feishu_bitable_app_token = ""
    with patch.object(FeishuClient, "get_tenant_access_token") as auth:
        with pytest.raises(FeishuError):
            FeishuClient(settings).list_fields()
    auth.assert_not_called()


def test_field_permission_error_hides_provider_message(settings):
    api = field_client(settings)
    with patch.object(api, "get_tenant_access_token", return_value="test-token"), patch("app.integrations.feishu.httpx.Client") as factory:
        factory.return_value.__enter__.return_value.get.return_value.json.return_value = {"code": 999, "msg": "test-secret"}
        with pytest.raises(FeishuError) as error:
            api.list_fields()
    assert "test-secret" not in str(error.value)
