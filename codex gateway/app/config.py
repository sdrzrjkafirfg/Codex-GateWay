from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator


class GatewaySettings(BaseModel):
    local_api_key_env: str = "GATEWAY_API_KEY"
    admin_api_key_env: str = "GATEWAY_ADMIN_API_KEY"
    request_timeout_seconds: float = Field(default=90, gt=0)
    connect_timeout_seconds: float = Field(default=10, gt=0)
    failure_threshold: int = Field(default=10, ge=1)
    cooldown_seconds: float = Field(default=60, gt=0)
    health_check_interval_seconds: float = Field(default=60, gt=0)
    health_check_model: str = Field(default="gpt-5.4-mini", min_length=1)
    recovery_check_interval_seconds: float = Field(default=20, gt=0)
    recovery_success_threshold: int = Field(default=2, ge=1)
    retry_status_codes: set[int] = {408, 429, 500, 502, 503, 504}
    state_database_path: str = "gateway-state.db"


class ProviderConfig(BaseModel):
    name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    base_url: HttpUrl
    api_key_env: str = Field(min_length=1)
    price_multiplier: float = Field(ge=0)
    priority: int = 100
    enabled: bool = True

    @property
    def api_key(self) -> str:
        value = os.getenv(self.api_key_env)
        if not value:
            raise RuntimeError(f"missing required environment variable: {self.api_key_env}")
        return value


class RoutingSettings(BaseModel):
    mode: Literal["auto", "manual"] = "auto"
    manual_strategy: Literal[
        "priority_failover", "failure_transfer", "pinned_provider"
    ] = "priority_failover"
    pinned_provider: str | None = None

    @field_validator("pinned_provider")
    @classmethod
    def normalize_pinned_provider(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class AppConfig(BaseModel):
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    routing: RoutingSettings = Field(default_factory=RoutingSettings)
    providers: list[ProviderConfig] = Field(min_length=1)

    @field_validator("providers")
    @classmethod
    def unique_provider_names(cls, providers: list[ProviderConfig]) -> list[ProviderConfig]:
        names = [provider.name for provider in providers]
        if len(names) != len(set(names)):
            raise ValueError("provider names must be unique")
        return providers

    @property
    def local_api_key(self) -> str:
        env_name = self.gateway.local_api_key_env
        value = os.getenv(env_name)
        if not value:
            raise RuntimeError(f"missing required environment variable: {env_name}")
        return value

    @property
    def admin_api_key(self) -> str:
        env_name = self.gateway.admin_api_key_env
        value = os.getenv(env_name)
        if not value:
            raise RuntimeError(f"missing required environment variable: {env_name}")
        return value


def load_config(path: str | Path = "providers.yaml") -> AppConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as config_file:
        raw_config = yaml.safe_load(config_file)
    config = AppConfig.model_validate(raw_config)
    state_path = Path(config.gateway.state_database_path)
    if not state_path.is_absolute():
        config = config.model_copy(
            update={
                "gateway": config.gateway.model_copy(
                    update={"state_database_path": str(config_path.parent / state_path)}
                )
            }
        )
    return config


def save_config(config: AppConfig, path: str | Path) -> None:
    config_path = Path(path)
    serialized = config.model_dump(mode="json")
    config_path.write_text(
        yaml.safe_dump(serialized, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
