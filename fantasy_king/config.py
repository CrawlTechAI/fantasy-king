"""Reads the app's settings from the .env file.

Every other part of the app gets its settings by calling load_settings().
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"
DATA_DIR = PROJECT_ROOT / "data"

LEAGUE_DATA_SOURCES = ("sample", "manual", "yahoo_api")
AI_PROVIDERS = ("chatgpt", "openrouter")


class ConfigError(Exception):
    """A setting in .env is missing or has a value the app does not understand."""


@dataclass(frozen=True)
class Settings:
    league_data_source: str
    ai_provider: str


def _choice(values: dict, name: str, allowed: tuple[str, ...], default: str) -> str:
    value = (values.get(name) or default).strip().lower()
    if value not in allowed:
        raise ConfigError(
            f'{name} is set to "{value}" in your .env file, but it must be one of: '
            f'{", ".join(allowed)}. Open .env, fix that line, and save.'
        )
    return value


def load_settings(env_file: Path = ENV_FILE) -> Settings:
    # Values set in the terminal win over the .env file. A missing .env is fine:
    # the defaults below give a working app with sample data.
    values = {**dotenv_values(env_file), **os.environ}
    return Settings(
        league_data_source=_choice(values, "LEAGUE_DATA_SOURCE", LEAGUE_DATA_SOURCES, "sample"),
        ai_provider=_choice(values, "AI_PROVIDER", AI_PROVIDERS, "chatgpt"),
    )
