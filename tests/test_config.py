import pytest

from fantasy_king.config import ConfigError, load_settings


@pytest.fixture(autouse=True)
def no_settings_from_the_terminal(monkeypatch):
    monkeypatch.delenv("LEAGUE_DATA_SOURCE", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)


def test_missing_env_file_gives_working_defaults(tmp_path):
    settings = load_settings(tmp_path / "does_not_exist.env")
    assert settings.league_data_source == "sample"
    assert settings.ai_provider == "chatgpt"


def test_values_are_read_from_the_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LEAGUE_DATA_SOURCE=Manual\nAI_PROVIDER=openrouter\n")
    settings = load_settings(env_file)
    assert settings.league_data_source == "manual"
    assert settings.ai_provider == "openrouter"


def test_unknown_value_names_the_setting_and_the_choices(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("AI_PROVIDER=gemini\n")
    with pytest.raises(ConfigError, match="AI_PROVIDER.*chatgpt, openrouter"):
        load_settings(env_file)


def test_the_example_file_is_valid():
    from fantasy_king.config import PROJECT_ROOT

    settings = load_settings(PROJECT_ROOT / ".env.example")
    assert settings.league_data_source == "sample"
