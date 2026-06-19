"""Runtime configuration for the cloud server.

All knobs come from env vars so Railway can override without code changes.
The estimator tunables (EMA_ALPHA, CAPACITY_AH, ...) mirror the constructor
defaults of `volthium.estimator.Estimator` so a fresh deployment behaves the
same as the local logger has been behaving on the Mac.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v not in (None, "") else default


def _env_str(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    database_url: str
    # Map of source_id → bearer token. Built from env vars at startup:
    # any env var named READER_TOKEN_<UPPER_SNAKE> populates the source_id
    # <lower-kebab> with the token's value. So READER_TOKEN_PI_BARGE=xyz
    # authenticates source_id="pi-barge".
    tokens: Dict[str, str]
    ema_alpha: float
    capacity_ah: float
    floor_soc: float
    ceiling_soc: float
    idle_current_a: float
    display_tz: str
    auto_migrate: bool


def _collect_tokens() -> Dict[str, str]:
    out: Dict[str, str] = {}
    prefix = "READER_TOKEN_"
    for k, v in os.environ.items():
        if not k.startswith(prefix) or not v:
            continue
        # Convert UPPER_SNAKE back to lower-kebab so the env-var name
        # READER_TOKEN_PI_BARGE matches source_id "pi-barge".
        source_id = k[len(prefix):].lower().replace("_", "-")
        out[source_id] = v
    return out


def load_settings() -> Settings:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        # Allow tests to run without configuring Postgres; the actual server
        # boot path checks for this and errors out clearly.
        database_url = ""
    return Settings(
        database_url=database_url,
        tokens=_collect_tokens(),
        ema_alpha=_env_float("EMA_ALPHA", 0.15),
        capacity_ah=_env_float("CAPACITY_AH", 200.0),
        floor_soc=_env_float("FLOOR_PCT", 10.0),
        ceiling_soc=_env_float("CEILING_PCT", 95.0),
        idle_current_a=_env_float("IDLE_CURRENT_A", 0.5),
        display_tz=_env_str("DISPLAY_TZ", "America/Toronto"),
        auto_migrate=os.environ.get("DB_MIGRATE", "1") not in ("0", "", "false"),
    )
