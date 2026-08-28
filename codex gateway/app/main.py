from __future__ import annotations

import asyncio
import ipaddress
import hmac
import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, HttpUrl, field_validator
from starlette.background import BackgroundTask
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

from .config import AppConfig, ProviderConfig, RoutingSettings, load_config, save_config
from .credentials import provider_key_env_name, save_provider_key
from .router import PriorityRouter

MAX_REQUEST_BODY_BYTES = 128 * 1024 * 1024
MAX_RESPONSE_BODY_BYTES = 128 * 1024 * 1024

HOP_BY_HOP_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
FORWARDED_REQUEST_HEADERS = {
    "accept",
    "content-type",
    "user-agent",
    "x-request-id",
    "openai-organization",
    "openai-project",
}
HEALTH_CHECK_PATH = "/v1/responses"
HEALTH_CHECK_FALLBACK_MODELS = ("gpt-5.4", "gpt-5.5", "gpt-5.6-terra")
MODEL_ERROR_MARKERS = (
    "model not found",
    "model_not_found",
    "model does not exist",
    "model is not available",
    "unsupported model",
    "unknown model",
    "invalid model",
    "model unavailable",
)


class ProviderInput(BaseModel):
    alias: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    base_url: HttpUrl
    api_key: str | None = Field(default=None, min_length=1)
    price_multiplier: float = Field(ge=0)
    priority: int = 100
    enabled: bool = True

    def to_config(self, api_key_env: str) -> ProviderConfig:
        return ProviderConfig(
            name=self.alias,
            base_url=self.base_url,
            api_key_env=api_key_env,
            price_multiplier=self.price_multiplier,
            priority=self.priority,
            enabled=self.enabled,
        )


class ProviderModelDiscoveryInput(BaseModel):
    base_url: HttpUrl
    api_key: str | None = Field(default=None, min_length=1)
    provider_alias: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class GatewayApiKeyInput(BaseModel):
    api_key: str = Field(min_length=1)


def create_app(
    config: AppConfig | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    config_path = None if config is not None else os.getenv("GATEWAY_CONFIG", "providers.yaml")
    config = config or load_config(config_path)
    router = PriorityRouter(config)
    timeout = httpx.Timeout(
        timeout=config.gateway.request_timeout_seconds,
        connect=config.gateway.connect_timeout_seconds,
    )
    client = httpx.AsyncClient(timeout=timeout, transport=transport)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        health_task = asyncio.create_task(health_check_loop(router, client))
        try:
            yield
        finally:
            health_task.cancel()
            await asyncio.gather(health_task, return_exceptions=True)
            await client.aclose()

    app = FastAPI(title="Codex Priority Gateway", lifespan=lifespan)
    app.mount(
        "/admin/assets",
        StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
        name="admin-assets",
    )
    app.state.config = config
    app.state.router = router
    app.state.client = client
    app.state.config_path = config_path
    app.state.env_path = (
        os.path.join(os.path.dirname(config_path), ".env") if config_path else ".env"
    )
    app.state.config_lock = asyncio.Lock()

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        return {"status": "ok"}

    @app.get("/admin/ui", include_in_schema=False)
    async def admin_ui() -> FileResponse:
        return FileResponse(os.path.join(os.path.dirname(__file__), "static", "admin.html"))

    @app.get("/admin/status")
    async def admin_status(request: Request) -> dict[str, object]:
        verify_admin_key(request, config.admin_api_key)
        return await router.snapshot()

    @app.get("/admin/config")
    async def admin_config(request: Request) -> dict[str, object]:
        verify_admin_key(request, config.admin_api_key)
        return (await router.current_config()).model_dump(mode="json")

    @app.put("/admin/gateway/api-key")
    async def update_gateway_api_key(
        request: Request, details: GatewayApiKeyInput
    ) -> dict[str, bool]:
        verify_admin_key(request, config.admin_api_key)
        current = await router.current_config()
        save_provider_key(
            app.state.env_path,
            current.gateway.local_api_key_env,
            details.api_key,
        )
        return {"configured": True}

    @app.put("/admin/routing")
    async def update_routing(request: Request, routing: RoutingSettings) -> dict[str, object]:
        verify_admin_key(request, config.admin_api_key)
        updated = await update_runtime_config(app, routing=routing)
        return updated.routing.model_dump()

    @app.post("/admin/providers", status_code=status.HTTP_201_CREATED)
    async def create_provider(request: Request, provider: ProviderInput) -> dict[str, object]:
        verify_admin_key(request, config.admin_api_key)
        current = await router.current_config()
        if any(item.name == provider.alias for item in current.providers):
            raise HTTPException(status_code=409, detail="provider name already exists")
        if not provider.api_key:
            raise HTTPException(status_code=422, detail="api_key is required when creating a provider")
        key_env = provider_key_env_name(provider.alias)
        if any(item.api_key_env == key_env for item in current.providers):
            raise HTTPException(status_code=409, detail="provider alias conflicts with an existing API key")
        save_provider_key(app.state.env_path, key_env, provider.api_key)
        config_provider = provider.to_config(api_key_env=key_env)
        updated = await update_runtime_config(app, providers=[*current.providers, config_provider])
        return provider_view(next(item for item in updated.providers if item.name == provider.alias))

    @app.post("/admin/providers/discover-models")
    async def discover_provider_models(
        request: Request, details: ProviderModelDiscoveryInput
    ) -> dict[str, list[str]]:
        verify_admin_key(request, config.admin_api_key)
        await validate_discovery_target(details.base_url)
        api_key = details.api_key
        if not api_key and details.provider_alias:
            current = await router.current_config()
            provider = next(
                (item for item in current.providers if item.name == details.provider_alias), None
            )
            if provider:
                api_key = provider.api_key
        if not api_key:
            raise HTTPException(status_code=422, detail="api_key is required to discover models")
        try:
            response = await client.get(
                build_upstream_url(details.base_url, "/v1/models"),
                headers={"authorization": f"Bearer {api_key}"},
            )
        except httpx.TransportError:
            raise HTTPException(status_code=502, detail="could not connect to upstream provider") from None
        try:
            if response.status_code < 200 or response.status_code >= 300:
                raise HTTPException(
                    status_code=502,
                    detail=f"upstream model discovery failed with HTTP {response.status_code}",
                )
            payload = response.json()
        finally:
            await response.aclose()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="upstream returned an invalid model list")
        models = sorted(
            {
                str(item["id"])
                for item in payload.get("data", [])
                if isinstance(item, dict) and item.get("id")
            }
        )
        return {"models": models}

    @app.put("/admin/providers/{provider_name}")
    async def update_provider(
        provider_name: str, request: Request, provider: ProviderInput
    ) -> dict[str, object]:
        verify_admin_key(request, config.admin_api_key)
        current = await router.current_config()
        existing = next((item for item in current.providers if item.name == provider_name), None)
        if existing is None:
            raise HTTPException(status_code=404, detail="provider not found")
        if provider.alias != provider_name and any(
            item.name == provider.alias for item in current.providers
        ):
            raise HTTPException(status_code=409, detail="provider name already exists")
        key_env = provider_key_env_name(provider.alias)
        if provider.alias != provider_name and any(
            item.name != provider_name and item.api_key_env == key_env
            for item in current.providers
        ):
            raise HTTPException(status_code=409, detail="provider alias conflicts with an existing API key")
        if provider.api_key:
            save_provider_key(app.state.env_path, key_env, provider.api_key)
        elif provider.alias == provider_name:
            key_env = existing.api_key_env
        else:
            old_key = existing.api_key
            save_provider_key(app.state.env_path, key_env, old_key)
        replacement = provider.to_config(api_key_env=key_env)
        providers = [replacement if item.name == provider_name else item for item in current.providers]
        routing = current.routing
        if routing.pinned_provider == provider_name:
            routing = routing.model_copy(update={"pinned_provider": provider.alias})
        updated = await update_runtime_config(app, providers=providers, routing=routing)
        return provider_view(next(item for item in updated.providers if item.name == provider.alias))

    @app.post("/admin/providers/{provider_name}/enable")
    async def enable_provider(provider_name: str, request: Request) -> dict[str, object]:
        verify_admin_key(request, config.admin_api_key)
        return await set_provider_enabled(app, provider_name, True)

    @app.post("/admin/providers/{provider_name}/disable")
    async def disable_provider(provider_name: str, request: Request) -> dict[str, object]:
        verify_admin_key(request, config.admin_api_key)
        return await set_provider_enabled(app, provider_name, False)

    @app.delete("/admin/providers/{provider_name}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_provider(provider_name: str, request: Request) -> Response:
        verify_admin_key(request, config.admin_api_key)
        current = await router.current_config()
        providers = [item for item in current.providers if item.name != provider_name]
        if len(providers) == len(current.providers):
            raise HTTPException(status_code=404, detail="provider not found")
        if current.routing.pinned_provider == provider_name:
            raise HTTPException(
                status_code=409,
                detail="cannot delete the pinned provider; change routing first",
            )
        await update_runtime_config(app, providers=providers)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.api_route("/v1/{upstream_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def proxy(upstream_path: str, request: Request) -> Response:
        verify_local_key(request, config.local_api_key)
        body = await request.body()
        if len(body) > MAX_REQUEST_BODY_BYTES:
            raise HTTPException(status_code=413, detail="request body is too large")
        response, provider = await request_with_failover(
            router, client, request, request.url.path, body
        )
        headers = response_headers(response)
        headers["x-gateway-provider"] = provider.name

        if response.status_code >= 400:
            payload = await read_limited_response(response, MAX_RESPONSE_BODY_BYTES)
            return Response(content=payload, status_code=response.status_code, headers=headers)

        if is_streaming_response(response):
            return StreamingResponse(
                response.aiter_bytes(),
                status_code=response.status_code,
                headers=headers,
                media_type=response.headers.get("content-type"),
                background=BackgroundTask(response.aclose),
            )

        payload = await read_limited_response(response, MAX_RESPONSE_BODY_BYTES)
        return Response(content=payload, status_code=response.status_code, headers=headers)

    return app


async def update_runtime_config(
    app: FastAPI,
    *,
    routing: RoutingSettings | None = None,
    providers: list[ProviderConfig] | None = None,
) -> AppConfig:
    router: PriorityRouter = app.state.router
    async with app.state.config_lock:
        current = await router.current_config()
        updated = AppConfig.model_validate(
            {
                "gateway": current.gateway.model_dump(mode="json"),
                "routing": (routing or current.routing).model_dump(mode="json"),
                "providers": [
                    item.model_dump(mode="json")
                    for item in (providers if providers is not None else current.providers)
                ],
            }
        )
        validate_routing(updated)
        if app.state.config_path:
            save_config(updated, app.state.config_path)
        await router.replace_config(updated)
        return updated


async def set_provider_enabled(app: FastAPI, provider_name: str, enabled: bool) -> dict[str, object]:
    router: PriorityRouter = app.state.router
    current = await router.current_config()
    if not any(item.name == provider_name for item in current.providers):
        raise HTTPException(status_code=404, detail="provider not found")
    providers = [
        item.model_copy(update={"enabled": enabled}) if item.name == provider_name else item
        for item in current.providers
    ]
    updated = await update_runtime_config(app, providers=providers)
    return provider_view(next(item for item in updated.providers if item.name == provider_name))


def validate_routing(config: AppConfig) -> None:
    routing = config.routing
    if routing.mode != "manual" or routing.manual_strategy != "pinned_provider":
        return
    if not routing.pinned_provider:
        raise HTTPException(status_code=422, detail="pinned_provider is required")
    if routing.pinned_provider not in {provider.name for provider in config.providers}:
        raise HTTPException(status_code=422, detail="pinned_provider does not exist")


async def validate_discovery_target(base_url: HttpUrl | str) -> None:
    parsed = urlparse(str(base_url))
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise HTTPException(status_code=422, detail="base_url must use http or https")
    if hostname in {"localhost", "metadata.google.internal"}:
        raise HTTPException(status_code=422, detail="base_url must target a public provider")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return
        addresses = {info[4][0] for info in infos}
        if any(is_blocked_address(item) for item in addresses):
            raise HTTPException(status_code=422, detail="base_url must target a public provider")
        return
    if is_blocked_address(address):
        raise HTTPException(status_code=422, detail="base_url must target a public provider")


def is_blocked_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address | str) -> bool:
    parsed = ipaddress.ip_address(address)
    return parsed.is_private or parsed.is_loopback or parsed.is_link_local or parsed.is_reserved


async def read_limited_response(response: httpx.Response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > limit:
                raise HTTPException(status_code=502, detail="upstream response is too large")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        await response.aclose()


def provider_view(provider: ProviderConfig) -> dict[str, object]:
    return {
        "alias": provider.name,
        "base_url": str(provider.base_url),
        "price_multiplier": provider.price_multiplier,
        "priority": provider.priority,
        "enabled": provider.enabled,
        "has_api_key": bool(os.getenv(provider.api_key_env)),
    }


def verify_local_key(request: Request, expected_key: str) -> None:
    authorization = request.headers.get("authorization", "")
    if not hmac.compare_digest(authorization, f"Bearer {expected_key}"):
        raise HTTPException(status_code=401, detail="invalid gateway API key")


def verify_admin_key(request: Request, expected_key: str) -> None:
    authorization = request.headers.get("authorization", "")
    if not hmac.compare_digest(authorization, f"Bearer {expected_key}"):
        raise HTTPException(status_code=401, detail="invalid gateway admin API key")


def request_headers(request: Request, provider: ProviderConfig) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() in FORWARDED_REQUEST_HEADERS
    }
    headers["authorization"] = f"Bearer {provider.api_key}"
    return headers


def build_upstream_url(base_url: HttpUrl | str, gateway_path: str) -> str:
    """Keep the Codex path, without duplicating an optional provider /v1 suffix."""
    base = str(base_url).rstrip("/")
    path = gateway_path if gateway_path.startswith("/") else f"/{gateway_path}"
    if base.endswith("/v1") and (path == "/v1" or path.startswith("/v1/")):
        path = path[3:]
    return f"{base}{path}"


async def request_with_failover(
    router: PriorityRouter,
    client: httpx.AsyncClient,
    request: Request,
    gateway_path: str,
    body: bytes,
) -> tuple[httpx.Response, ProviderConfig]:
    candidates = await router.candidates()
    if not candidates:
        raise HTTPException(status_code=503, detail=await router.unavailable_detail())

    last_response: httpx.Response | None = None
    last_response_provider: ProviderConfig | None = None
    last_error: Exception | None = None
    for provider in candidates:
        upstream_url = build_upstream_url(provider.base_url, gateway_path)
        outbound_request = client.build_request(
            request.method,
            upstream_url,
            headers=request_headers(request, provider),
            content=body,
            params=request.query_params,
        )
        try:
            response = await client.send(outbound_request, stream=True)
        except httpx.TransportError as error:
            last_error = error
            await router.record_failure(provider, str(error))
            continue

        if response.status_code in router.config.gateway.retry_status_codes:
            await router.record_failure(provider, f"HTTP {response.status_code}")
            if last_response is not None:
                await last_response.aclose()
            last_response = response
            last_response_provider = provider
            continue

        await router.record_success(provider)
        return response, provider

    if last_response is not None:
        assert last_response_provider is not None
        return last_response, last_response_provider
    raise HTTPException(status_code=502, detail=f"all upstream requests failed: {last_error}")


def is_streaming_response(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "")
    return "text/event-stream" in content_type.lower()


def response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


async def health_check_loop(router: PriorityRouter, client: httpx.AsyncClient) -> None:
    while True:
        await asyncio.sleep(router.config.gateway.health_check_interval_seconds)
        for provider in await router.recovery_candidates():
            healthy, error = await probe_provider(client, provider, router.config.gateway.health_check_model)
            if healthy:
                await router.record_health_success(provider)
            else:
                await router.record_health_failure(provider, error or "health check failed")


async def probe_provider(
    client: httpx.AsyncClient, provider: ProviderConfig, model: str
) -> tuple[bool, str | None]:
    """Probe Responses with minimal output, falling back only for model errors."""
    models = list(dict.fromkeys((model, *HEALTH_CHECK_FALLBACK_MODELS)))
    last_error = "health check failed"
    for probe_model in models:
        try:
            response = await client.post(
                build_upstream_url(provider.base_url, HEALTH_CHECK_PATH),
                headers={"authorization": f"Bearer {provider.api_key}"},
                json={
                    "model": probe_model,
                    "input": "1",
                    "max_output_tokens": 1,
                    "store": False,
                },
            )
        except httpx.TransportError as error:
            return False, str(error)

        try:
            payload = await response.aread()
            if 200 <= response.status_code < 300:
                return True, None
            last_error = f"health check HTTP {response.status_code}"
            if not is_model_selection_error(response.status_code, payload):
                return False, last_error
        finally:
            await response.aclose()
    return False, last_error


def is_model_selection_error(status_code: int, payload: bytes) -> bool:
    """Recognize only explicit unsupported-model responses for probe fallback."""
    if status_code not in {400, 404, 422}:
        return False
    text = payload.decode("utf-8", errors="replace").lower()
    return any(marker in text for marker in MODEL_ERROR_MARKERS)
