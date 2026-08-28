from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest

from app.config import AppConfig, load_config
from app.main import create_app, probe_provider
from app.router import utc_now


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch, tmp_path) -> AppConfig:
    monkeypatch.setenv("GATEWAY_API_KEY", "local-secret")
    monkeypatch.setenv("GATEWAY_ADMIN_API_KEY", "admin-secret")
    monkeypatch.setenv("RELAY_A_API_KEY", "a-secret")
    monkeypatch.setenv("RELAY_B_API_KEY", "b-secret")
    return AppConfig.model_validate(
        {
            "gateway": {
                "failure_threshold": 2,
                "cooldown_seconds": 60,
                "health_check_interval_seconds": 3600,
                "recovery_success_threshold": 1,
                "state_database_path": str(tmp_path / "gateway-state.db"),
            },
            "providers": [
                {
                    "name": "relay-a",
                    "base_url": "https://a.test/v1",
                    "api_key_env": "RELAY_A_API_KEY",
                    "price_multiplier": 0.17,
                    "priority": 1,
                },
                {
                    "name": "relay-b",
                    "base_url": "https://b.test/v1",
                    "api_key_env": "RELAY_B_API_KEY",
                    "price_multiplier": 0.20,
                    "priority": 2,
                },
            ],
        }
    )


@pytest.mark.asyncio
async def test_lowest_cost_provider_is_used_and_model_is_preserved(config: AppConfig) -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    app = create_app(config, transport=httpx.MockTransport(handler))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.post(
            "/v1/responses",
            headers={"authorization": "Bearer local-secret"},
            json={"model": "codex-default", "input": "hello"},
        )

    assert response.status_code == 200
    assert response.headers["x-gateway-provider"] == "relay-a"
    assert seen[0].url == httpx.URL("https://a.test/v1/responses")
    assert json.loads(seen[0].content)["model"] == "codex-default"


@pytest.mark.asyncio
async def test_root_upstream_url_keeps_the_codex_v1_path(config: AppConfig) -> None:
    root_config_data = config.model_dump(mode="json")
    root_config_data["providers"][0]["base_url"] = "https://root.test"
    root_config = AppConfig.model_validate(root_config_data)
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    app = create_app(root_config, transport=httpx.MockTransport(handler))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.post(
            "/v1/responses",
            headers={"authorization": "Bearer local-secret"},
            json={"model": "codex-default", "input": "hello"},
        )

    assert response.status_code == 200
    assert seen[0].url == httpx.URL("https://root.test/v1/responses")


@pytest.mark.asyncio
async def test_retryable_failure_falls_back_to_next_provider(config: AppConfig) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "a.test":
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"provider": "b"})

    app = create_app(config, transport=httpx.MockTransport(handler))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"authorization": "Bearer local-secret"},
            json={"model": "codex-default", "messages": []},
        )

    assert response.status_code == 200
    assert response.headers["x-gateway-provider"] == "relay-b"
    assert response.json() == {"provider": "b"}


@pytest.mark.asyncio
async def test_open_circuit_skips_failed_provider_on_following_request(config: AppConfig) -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "a.test":
            return httpx.Response(503)
        return httpx.Response(200, json={"provider": "b"})

    app = create_app(config, transport=httpx.MockTransport(handler))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        for _ in range(2):
            response = await client.post(
                "/v1/responses",
                headers={"authorization": "Bearer local-secret"},
                json={"model": "codex-default", "input": "hello"},
            )
            assert response.status_code == 200
        response = await client.post(
            "/v1/responses",
            headers={"authorization": "Bearer local-secret"},
            json={"model": "codex-default", "input": "hello"},
        )

    assert response.headers["x-gateway-provider"] == "relay-b"
    assert calls == ["a.test", "b.test", "a.test", "b.test", "b.test"]


@pytest.mark.asyncio
async def test_sse_response_is_proxied(config: AppConfig) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: {\"type\":\"response.completed\"}\n\n",
        )

    app = create_app(config, transport=httpx.MockTransport(handler))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.post(
            "/v1/responses",
            headers={"authorization": "Bearer local-secret"},
            json={"model": "codex-default", "stream": True, "input": "hello"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.content == b"data: {\"type\":\"response.completed\"}\n\n"


@pytest.mark.asyncio
async def test_health_success_reenables_open_circuit(config: AppConfig) -> None:
    app = create_app(config, transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    router = app.state.router
    primary = config.providers[0]

    await router.record_failure(primary, "HTTP 503")
    await router.record_failure(primary, "HTTP 503")
    assert [provider.name for provider in await router.candidates()] == ["relay-b"]

    await router.record_health_success(primary)
    assert [provider.name for provider in await router.candidates()] == ["relay-a", "relay-b"]


@pytest.mark.asyncio
async def test_health_probe_is_minimal_and_does_not_generate_tokens(config: AppConfig) -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        healthy, error = await probe_provider(client, config.providers[0], "gpt-5.4")
    finally:
        await client.aclose()

    assert healthy is True
    assert error is None
    assert seen[0].method == "POST"
    assert seen[0].url == httpx.URL("https://a.test/v1/responses")
    assert json.loads(seen[0].content) == {
        "model": "gpt-5.4",
        "input": "1",
        "max_output_tokens": 1,
        "store": False,
    }
    assert seen[0].headers["authorization"] == "Bearer a-secret"


@pytest.mark.asyncio
async def test_health_probe_falls_back_when_probe_model_is_unsupported(config: AppConfig) -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        model = json.loads(request.content)["model"]
        if model == "gpt-5.4-mini":
            return httpx.Response(400, json={"error": {"message": "model not found"}})
        return httpx.Response(200, json={"id": "probe-ok"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        healthy, error = await probe_provider(client, config.providers[0], "gpt-5.4-mini")
    finally:
        await client.aclose()

    assert healthy is True
    assert error is None
    assert [json.loads(request.content)["model"] for request in seen] == ["gpt-5.4-mini", "gpt-5.4"]


@pytest.mark.asyncio
async def test_recovery_probe_waits_before_second_success(config: AppConfig) -> None:
    test_config = AppConfig.model_validate(
        config.model_dump(mode="json")
        | {
            "gateway": config.gateway.model_dump(mode="json")
            | {"recovery_success_threshold": 2}
        }
    )
    app = create_app(test_config, transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    router = app.state.router
    provider = test_config.providers[0]

    await router.record_failure(provider, "HTTP 503")
    await router.record_failure(provider, "HTTP 503")
    router.states[provider.name].circuit_open_until = utc_now() - timedelta(seconds=1)

    await router.record_health_success(provider)
    assert router.states[provider.name].recovery_successes == 1
    assert await router.recovery_candidates() == []

    router.states[provider.name].next_recovery_check_at = utc_now() - timedelta(seconds=1)
    assert [item.name for item in await router.recovery_candidates()] == [provider.name]


@pytest.mark.asyncio
async def test_manual_priority_mode_ignores_price_multiplier(config: AppConfig) -> None:
    manual = AppConfig.model_validate(
        config.model_dump(mode="json")
        | {
            "routing": {
                "mode": "manual",
                "manual_strategy": "priority_failover",
            }
        }
    )
    app = create_app(manual, transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    router = app.state.router

    assert [provider.name for provider in await router.candidates()] == ["relay-a", "relay-b"]
    updated = await router.current_config()
    updated.providers[0].priority = 20
    updated.providers[1].priority = 1
    await router.replace_config(updated)

    assert [provider.name for provider in await router.candidates()] == ["relay-b", "relay-a"]


@pytest.mark.asyncio
async def test_manual_failure_transfer_uses_priority_first_then_lowest_price(config: AppConfig) -> None:
    manual = AppConfig.model_validate(
        config.model_dump(mode="json")
        | {
            "routing": {
                "mode": "manual",
                "manual_strategy": "failure_transfer",
            }
        }
    )
    app = create_app(manual, transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    router = app.state.router
    updated = await router.current_config()
    updated.providers[0].priority = 20
    updated.providers[1].priority = 1
    updated.providers[1].price_multiplier = 0.30
    updated.providers.append(
        updated.providers[0].model_copy(
            update={
                "name": "relay-c",
                "price_multiplier": 0.10,
                "priority": 3,
            }
        )
    )
    await router.replace_config(updated)

    assert [provider.name for provider in await router.candidates()] == ["relay-b", "relay-c", "relay-a"]


@pytest.mark.asyncio
async def test_admin_disable_and_pinned_mode(config: AppConfig) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"host": request.url.host})

    app = create_app(config, transport=httpx.MockTransport(handler))
    transport = httpx.ASGITransport(app=app)
    headers = {"authorization": "Bearer local-secret"}
    admin_headers = {"authorization": "Bearer admin-secret"}
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        disabled = await client.post("/admin/providers/relay-a/disable", headers=admin_headers)
        assert disabled.status_code == 200

        automatic = await client.post(
            "/v1/responses", headers=headers, json={"model": "codex", "input": "hello"}
        )
        assert automatic.headers["x-gateway-provider"] == "relay-b"

        routing = await client.put(
            "/admin/routing",
            headers=admin_headers,
            json={
                "mode": "manual",
                "manual_strategy": "pinned_provider",
                "pinned_provider": "relay-b",
            },
        )
        assert routing.status_code == 200

        pinned = await client.post(
            "/v1/responses", headers=headers, json={"model": "codex", "input": "hello"}
        )
        assert pinned.headers["x-gateway-provider"] == "relay-b"

        await client.post("/admin/providers/relay-b/disable", headers=admin_headers)
        unavailable = await client.post(
            "/v1/responses", headers=headers, json={"model": "codex", "input": "hello"}
        )

    assert unavailable.status_code == 503
    assert unavailable.json()["detail"] == "pinned provider is unavailable: relay-b"


@pytest.mark.asyncio
async def test_admin_provider_changes_persist_to_yaml(config: AppConfig, tmp_path) -> None:
    config_path = tmp_path / "providers.yaml"
    app = create_app(config, transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    app.state.config_path = str(config_path)
    app.state.env_path = str(tmp_path / ".env")
    transport = httpx.ASGITransport(app=app)
    headers = {"authorization": "Bearer local-secret"}
    provider = {
        "alias": "relay-c",
        "base_url": "https://c.test/v1",
        "api_key": "c-secret",
        "price_multiplier": 0.3,
        "priority": 3,
        "enabled": True,
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        created = await client.post("/admin/providers", headers={"authorization": "Bearer admin-secret"}, json=provider)
        assert created.status_code == 201
        assert created.json()["alias"] == "relay-c"
        assert created.json()["has_api_key"] is True
        assert "api_key" not in created.json()

        renamed = await client.put(
            "/admin/providers/relay-c",
            headers={"authorization": "Bearer admin-secret"},
            json=provider | {"alias": "relay-c-primary", "price_multiplier": 0.12},
        )
        assert renamed.status_code == 200
        assert renamed.json()["alias"] == "relay-c-primary"
        assert renamed.json()["price_multiplier"] == 0.12

        deleted = await client.delete("/admin/providers/relay-c-primary", headers={"authorization": "Bearer admin-secret"})

    assert deleted.status_code == 204
    persisted = config_path.read_text(encoding="utf-8")
    assert "relay-c-primary" not in persisted
    assert "c-secret" not in persisted
    assert "PROVIDER_RELAY_C_API_KEY" in (tmp_path / ".env").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_proxy_key_cannot_access_admin_api(config: AppConfig) -> None:
    app = create_app(config, transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.get(
            "/admin/status",
            headers={"authorization": "Bearer local-secret"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_healthz_does_not_expose_provider_state(config: AppConfig) -> None:
    app = create_app(config, transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_proxy_does_not_forward_sensitive_request_headers(config: AppConfig) -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    app = create_app(config, transport=httpx.MockTransport(handler))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.post(
            "/v1/responses",
            headers={
                "authorization": "Bearer local-secret",
                "cookie": "session=secret",
                "x-request-id": "request-1",
            },
            json={"model": "codex", "input": "hello"},
        )

    assert response.status_code == 200
    assert "cookie" not in seen[0].headers
    assert seen[0].headers["x-request-id"] == "request-1"


@pytest.mark.asyncio
async def test_admin_ui_and_assets_are_served_without_api_key(config: AppConfig) -> None:
    app = create_app(config, transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        page = await client.get("/admin/ui")
        script = await client.get("/admin/assets/admin.js")

    assert page.status_code == 200
    assert "Codex Gateway" in page.text
    assert 'data-i18n="failureTransfer"' in page.text
    assert script.status_code == 200
    assert "saveProvider" in script.text
    assert 'translations.zh.failureTransfer = "失败转移"' in script.text


@pytest.mark.asyncio
async def test_model_discovery_does_not_persist_or_select_a_model(config: AppConfig) -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "gpt-5.6"}, {"id": "gpt-5.4"}]})

    app = create_app(config, transport=httpx.MockTransport(handler))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.post(
            "/admin/providers/discover-models",
            headers={"authorization": "Bearer admin-secret"},
            json={"base_url": "https://new-provider.test/v1", "api_key": "temporary-key"},
        )

    assert response.status_code == 200
    assert response.json() == {"models": ["gpt-5.4", "gpt-5.6"]}
    assert seen[0].url == httpx.URL("https://new-provider.test/v1/models")
    assert seen[0].headers["authorization"] == "Bearer temporary-key"


@pytest.mark.asyncio
async def test_model_discovery_rejects_private_targets(config: AppConfig) -> None:
    app = create_app(config, transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.post(
            "/admin/providers/discover-models",
            headers={"authorization": "Bearer admin-secret"},
            json={"base_url": "http://127.0.0.1:8000", "api_key": "temporary-key"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_routing_rejects_unknown_pinned_provider(config: AppConfig) -> None:
    app = create_app(config, transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        response = await client.put(
            "/admin/routing",
            headers={"authorization": "Bearer admin-secret"},
            json={
                "mode": "manual",
                "manual_strategy": "pinned_provider",
                "pinned_provider": "missing-provider",
            },
        )

    assert response.status_code == 422


def test_relative_state_database_path_is_resolved_next_to_config(tmp_path) -> None:
    config_path = tmp_path / "providers.yaml"
    config_path.write_text(
        """
gateway:
  state_database_path: gateway-state.db
providers:
  - name: relay-a
    base_url: https://a.test/v1
    api_key_env: RELAY_A_API_KEY
    price_multiplier: 0.1
""",
        encoding="utf-8",
    )

    loaded = load_config(config_path)

    assert loaded.gateway.state_database_path == str(tmp_path / "gateway-state.db")


@pytest.mark.asyncio
async def test_admin_can_update_gateway_proxy_key(config: AppConfig, tmp_path) -> None:
    app = create_app(config, transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    app.state.env_path = str(tmp_path / ".env")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        updated = await client.put(
            "/admin/gateway/api-key",
            headers={"authorization": "Bearer admin-secret"},
            json={"api_key": "updated-proxy-key"},
        )
        proxied = await client.post(
            "/v1/responses",
            headers={"authorization": "Bearer updated-proxy-key"},
            json={"model": "codex", "input": "hello"},
        )

    assert updated.status_code == 200
    assert updated.json() == {"configured": True}
    assert proxied.status_code == 200
    assert "updated-proxy-key" in (tmp_path / ".env").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_circuit_state_survives_router_restart(config: AppConfig, tmp_path) -> None:
    persisted_config = AppConfig.model_validate(
        config.model_dump(mode="json")
        | {"gateway": config.gateway.model_dump(mode="json") | {"state_database_path": str(tmp_path / "state.db")}}
    )
    first_app = create_app(persisted_config, transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    primary = persisted_config.providers[0]

    await first_app.state.router.record_failure(primary, "HTTP 503")
    await first_app.state.router.record_failure(primary, "HTTP 503")

    restarted_app = create_app(persisted_config, transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    state = (await restarted_app.state.router.snapshot())["providers"]["relay-a"]

    assert state["consecutive_failures"] == 2
    assert state["circuit_open_until"] is not None
    assert [provider.name for provider in await restarted_app.state.router.candidates()] == ["relay-b"]
