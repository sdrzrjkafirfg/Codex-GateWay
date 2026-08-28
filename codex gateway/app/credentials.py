from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import set_key


def provider_key_env_name(alias: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "_", alias).upper()
    return f"PROVIDER_{normalized}_API_KEY"


def save_provider_key(env_path: str | Path, env_name: str, api_key: str) -> None:
    path = Path(env_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    set_key(path, env_name, api_key, quote_mode="auto")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    os.environ[env_name] = api_key
