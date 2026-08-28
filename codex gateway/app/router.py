from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import AppConfig, ProviderConfig
from .state_store import StateStore, StoredProviderState


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ProviderState:
    consecutive_failures: int = 0
    recovery_successes: int = 0
    circuit_open_until: datetime | None = None
    last_error: str | None = None
    last_success_at: datetime | None = None
    next_recovery_check_at: datetime | None = None

    def is_available(self, now: datetime) -> bool:
        return self.circuit_open_until is None or now >= self.circuit_open_until and self.recovery_successes > 0

    def is_open(self, now: datetime) -> bool:
        return self.circuit_open_until is not None and now < self.circuit_open_until


class PriorityRouter:
    def __init__(self, config: AppConfig):
        self.config = config
        self.providers = list(config.providers)
        self.store = StateStore(config.gateway.state_database_path)
        stored_states = self.store.load_all()
        self.states = {
            provider.name: self._from_stored_state(stored_states.get(provider.name))
            for provider in self.providers
        }
        self.store.retain_only(set(self.states))
        self._lock = asyncio.Lock()

    async def candidates(self) -> list[ProviderConfig]:
        now = utc_now()
        async with self._lock:
            healthy = [
                provider
                for provider in self.providers
                if provider.enabled
                and not self.states[provider.name].is_open(now)
                and (
                    self.states[provider.name].next_recovery_check_at is None
                    or self.states[provider.name].next_recovery_check_at <= now
                )
                and self.states[provider.name].circuit_open_until is None
            ]
            routing = self.config.routing
            if routing.mode == "manual" and routing.manual_strategy == "pinned_provider":
                return [
                    provider for provider in healthy if provider.name == routing.pinned_provider
                ]
            if routing.mode == "manual":
                if routing.manual_strategy == "failure_transfer":
                    primary = sorted(healthy, key=lambda provider: (provider.priority, provider.name))
                    if not primary:
                        return []
                    first = primary[0]
                    fallback = sorted(
                        [provider for provider in healthy if provider.name != first.name],
                        key=lambda provider: (provider.price_multiplier, provider.priority, provider.name),
                    )
                    return [first, *fallback]
                return sorted(healthy, key=lambda provider: (provider.priority, provider.name))
            return sorted(
                healthy,
                key=lambda provider: (provider.price_multiplier, provider.priority, provider.name),
            )

    async def replace_config(self, config: AppConfig) -> None:
        async with self._lock:
            previous_states = self.states
            self.config = config
            self.providers = list(config.providers)
            self.states = {
                provider.name: previous_states.get(provider.name, ProviderState())
                for provider in self.providers
            }
            self.store.retain_only(set(self.states))

    async def current_config(self) -> AppConfig:
        async with self._lock:
            return self.config.model_copy(deep=True)

    async def unavailable_detail(self) -> str:
        async with self._lock:
            routing = self.config.routing
            if routing.mode == "manual" and routing.manual_strategy == "pinned_provider":
                return f"pinned provider is unavailable: {routing.pinned_provider}"
            return "no healthy upstream provider"

    async def record_success(self, provider: ProviderConfig) -> None:
        async with self._lock:
            state = self.states[provider.name]
            state.consecutive_failures = 0
            state.last_error = None
            state.last_success_at = utc_now()
            self._persist(provider.name, state)

    async def record_failure(self, provider: ProviderConfig, reason: str) -> None:
        async with self._lock:
            state = self.states[provider.name]
            state.consecutive_failures += 1
            state.recovery_successes = 0
            state.last_error = reason
            if state.consecutive_failures >= self.config.gateway.failure_threshold:
                state.circuit_open_until = utc_now() + timedelta(
                    seconds=self.config.gateway.cooldown_seconds
                )
                state.next_recovery_check_at = None
            self._persist(provider.name, state)

    async def recovery_candidates(self) -> list[ProviderConfig]:
        now = utc_now()
        async with self._lock:
            return [
                provider
                for provider in self.providers
                if provider.enabled
                if self.states[provider.name].circuit_open_until is not None
                and not self.states[provider.name].is_open(now)
                and (
                    self.states[provider.name].next_recovery_check_at is None
                    or self.states[provider.name].next_recovery_check_at <= now
                )
            ]

    async def record_health_success(self, provider: ProviderConfig) -> None:
        async with self._lock:
            state = self.states[provider.name]
            state.recovery_successes += 1
            state.last_success_at = utc_now()
            if state.recovery_successes >= self.config.gateway.recovery_success_threshold:
                state.consecutive_failures = 0
                state.recovery_successes = 0
                state.circuit_open_until = None
                state.last_error = None
                state.next_recovery_check_at = None
            else:
                state.next_recovery_check_at = utc_now() + timedelta(
                    seconds=self.config.gateway.recovery_check_interval_seconds
                )
            self._persist(provider.name, state)

    async def record_health_failure(self, provider: ProviderConfig, reason: str) -> None:
        async with self._lock:
            state = self.states[provider.name]
            state.recovery_successes = 0
            state.last_error = reason
            state.circuit_open_until = utc_now() + timedelta(
                seconds=self.config.gateway.cooldown_seconds
            )
            state.next_recovery_check_at = None
            self._persist(provider.name, state)

    async def snapshot(self) -> dict[str, object]:
        async with self._lock:
            now = utc_now()
            providers = {
                provider.name: {
                    "enabled": provider.enabled,
                    "price_multiplier": provider.price_multiplier,
                    "priority": provider.priority,
                    "consecutive_failures": state.consecutive_failures,
                    "recovery_successes": state.recovery_successes,
                    "circuit_open_until": state.circuit_open_until.isoformat()
                    if state.circuit_open_until
                    else None,
                    "next_recovery_check_at": state.next_recovery_check_at.isoformat()
                    if state.next_recovery_check_at
                    else None,
                    "last_error": state.last_error,
                    "last_success_at": state.last_success_at.isoformat() if state.last_success_at else None,
                }
                for provider, state in (
                    (provider, self.states[provider.name]) for provider in self.providers
                )
            }
            candidates = self._candidate_names_locked(now)
            return {
                "routing": self.config.routing.model_dump(),
                "next_provider": candidates[0] if candidates else None,
                "providers": providers,
            }

    def _candidate_names_locked(self, now: datetime) -> list[str]:
        healthy = [
            provider
            for provider in self.providers
            if provider.enabled
            and not self.states[provider.name].is_open(now)
            and (
                self.states[provider.name].next_recovery_check_at is None
                or self.states[provider.name].next_recovery_check_at <= now
            )
            and self.states[provider.name].circuit_open_until is None
        ]
        routing = self.config.routing
        if routing.mode == "manual" and routing.manual_strategy == "pinned_provider":
            return [provider.name for provider in healthy if provider.name == routing.pinned_provider]
        if routing.mode == "manual":
            if routing.manual_strategy == "failure_transfer":
                primary = sorted(healthy, key=lambda item: (item.priority, item.name))
                if not primary:
                    return []
                first = primary[0]
                fallback = sorted(
                    [item for item in healthy if item.name != first.name],
                    key=lambda item: (item.price_multiplier, item.priority, item.name),
                )
                return [first.name, *(item.name for item in fallback)]
            return [provider.name for provider in sorted(healthy, key=lambda item: (item.priority, item.name))]
        return [
            provider.name
            for provider in sorted(
                healthy,
                key=lambda item: (item.price_multiplier, item.priority, item.name),
            )
        ]

    def _persist(self, provider_name: str, state: ProviderState) -> None:
        self.store.save(
            provider_name,
            StoredProviderState(
                consecutive_failures=state.consecutive_failures,
                recovery_successes=state.recovery_successes,
                circuit_open_until=state.circuit_open_until,
                last_error=state.last_error,
                last_success_at=state.last_success_at,
            ),
        )

    @staticmethod
    def _from_stored_state(stored: StoredProviderState | None) -> ProviderState:
        if stored is None:
            return ProviderState()
        return ProviderState(
            consecutive_failures=stored.consecutive_failures,
            recovery_successes=stored.recovery_successes,
            circuit_open_until=stored.circuit_open_until,
            last_error=stored.last_error,
            last_success_at=stored.last_success_at,
        )
