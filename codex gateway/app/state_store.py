from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class StoredProviderState:
    consecutive_failures: int
    recovery_successes: int
    circuit_open_until: datetime | None
    last_error: str | None
    last_success_at: datetime | None


class StateStore:
    """Small SQLite store for provider circuit-breaker state."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def load_all(self) -> dict[str, StoredProviderState]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT provider_name, consecutive_failures, recovery_successes,
                       circuit_open_until, last_error, last_success_at
                FROM provider_state
                """
            ).fetchall()
        return {
            row["provider_name"]: StoredProviderState(
                consecutive_failures=row["consecutive_failures"],
                recovery_successes=row["recovery_successes"],
                circuit_open_until=parse_datetime(row["circuit_open_until"]),
                last_error=row["last_error"],
                last_success_at=parse_datetime(row["last_success_at"]),
            )
            for row in rows
        }

    def save(self, provider_name: str, state: StoredProviderState) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO provider_state (
                    provider_name, consecutive_failures, recovery_successes,
                    circuit_open_until, last_error, last_success_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_name) DO UPDATE SET
                    consecutive_failures = excluded.consecutive_failures,
                    recovery_successes = excluded.recovery_successes,
                    circuit_open_until = excluded.circuit_open_until,
                    last_error = excluded.last_error,
                    last_success_at = excluded.last_success_at
                """,
                (
                    provider_name,
                    state.consecutive_failures,
                    state.recovery_successes,
                    format_datetime(state.circuit_open_until),
                    state.last_error,
                    format_datetime(state.last_success_at),
                ),
            )

    def retain_only(self, provider_names: set[str]) -> None:
        with self._connection() as connection:
            if provider_names:
                placeholders = ", ".join("?" for _ in provider_names)
                connection.execute(
                    f"DELETE FROM provider_state WHERE provider_name NOT IN ({placeholders})",
                    tuple(provider_names),
                )
            else:
                connection.execute("DELETE FROM provider_state")

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_state (
                    provider_name TEXT PRIMARY KEY,
                    consecutive_failures INTEGER NOT NULL,
                    recovery_successes INTEGER NOT NULL,
                    circuit_open_until TEXT,
                    last_error TEXT,
                    last_success_at TEXT
                )
                """
            )

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection


def format_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
