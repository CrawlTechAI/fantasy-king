"""Reads the app's settings from the .env file.

Every other part of the app gets its settings by calling load_settings().
"""

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values, set_key

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE_FILE = PROJECT_ROOT / ".env.example"
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"
DATA_DIR = PROJECT_ROOT / "data"

LEAGUE_DATA_SOURCES = ("sample", "manual", "yahoo_api")
AI_PROVIDERS = ("chatgpt", "openrouter")

# The only settings the dashboard is allowed to write into .env for you.
MODEL_SETTINGS = {"chatgpt": "CHATGPT_MODEL", "openrouter": "OPENROUTER_MODEL"}
# Letters, digits, and the punctuation model names use. OpenRouter aliases start with "~".
_MODEL_NAME = re.compile(r"~?[A-Za-z0-9][A-Za-z0-9._:/@-]*")

_TRUE = {"true", "yes", "on", "1"}
_FALSE = {"false", "no", "off", "0"}


class ConfigError(Exception):
    """A setting in .env is missing or has a value the app does not understand."""


@dataclass(frozen=True)
class Settings:
    league_data_source: str
    ai_provider: str
    chatgpt_model: str = ""
    openrouter_model: str = ""
    # repr=False keeps the key out of error messages and logs.
    openrouter_api_key: str = field(default="", repr=False)
    web_search_enabled: bool = True
    max_web_searches_per_run: int = 5

    def model_for(self, provider: str) -> str:
        return self.chatgpt_model if provider == "chatgpt" else self.openrouter_model


def _choice(values: dict, name: str, allowed: tuple[str, ...], default: str) -> str:
    value = (values.get(name) or default).strip().lower()
    if value not in allowed:
        raise ConfigError(
            f'{name} is set to "{value}" in your .env file, but it must be one of: '
            f'{", ".join(allowed)}. Open .env, fix that line, and save.'
        )
    return value


def _text(values: dict, name: str) -> str:
    return (values.get(name) or "").strip()


def _on_off(values: dict, name: str, default: bool) -> bool:
    value = _text(values, name).lower()
    if not value:
        return default
    if value in _TRUE or value in _FALSE:
        return value in _TRUE
    raise ConfigError(
        f'{name} is set to "{value}" in your .env file, but it must be true or false. '
        "Open .env, fix that line, and save."
    )


def _whole_number(values: dict, name: str, default: int) -> int:
    value = _text(values, name)
    if not value:
        return default
    if not value.isdigit():
        raise ConfigError(
            f'{name} is set to "{value}" in your .env file, but it must be a whole number '
            "such as 5. Open .env, fix that line, and save."
        )
    return int(value)


def load_settings(env_file: Path = ENV_FILE) -> Settings:
    # Values set in the terminal win over the .env file. A missing .env is fine:
    # the defaults below give a working app with sample data.
    values = {**dotenv_values(env_file), **os.environ}
    return Settings(
        league_data_source=_choice(values, "LEAGUE_DATA_SOURCE", LEAGUE_DATA_SOURCES, "sample"),
        ai_provider=_choice(values, "AI_PROVIDER", AI_PROVIDERS, "chatgpt"),
        chatgpt_model=_text(values, "CHATGPT_MODEL"),
        openrouter_model=_text(values, "OPENROUTER_MODEL"),
        openrouter_api_key=_text(values, "OPENROUTER_API_KEY"),
        web_search_enabled=_on_off(values, "WEB_SEARCH_ENABLED", True),
        max_web_searches_per_run=_whole_number(values, "MAX_WEB_SEARCHES_PER_RUN", 5),
    )


def save_model(provider: str, model: str, env_file: Path = ENV_FILE) -> None:
    """Write the chosen model name into .env, leaving every other line alone."""
    model = model.strip()
    if not _MODEL_NAME.fullmatch(model):
        raise ConfigError(f'"{model}" doesn\'t look like a model name.')
    if not env_file.exists():
        # First run: start from the template so every setting is listed.
        if env_file == ENV_FILE and ENV_EXAMPLE_FILE.exists():
            shutil.copyfile(ENV_EXAMPLE_FILE, env_file)
        else:
            env_file.touch()
    set_key(env_file, MODEL_SETTINGS[provider], model, quote_mode="never")
