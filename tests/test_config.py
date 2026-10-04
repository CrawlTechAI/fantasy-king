import pytest

from fantasy_king.config import PROJECT_ROOT, ConfigError, load_settings, save_model


def test_missing_env_file_gives_working_defaults(tmp_path):
    settings = load_settings(tmp_path / "does_not_exist.env")
    assert settings.league_data_source == "sample"
    assert settings.ai_provider == "chatgpt"
    assert (settings.chatgpt_model, settings.openrouter_model, settings.openrouter_api_key) == (
        "",
        "",
        "",
    )
    assert settings.web_search_enabled is True
    assert settings.max_web_searches_per_run == 5


def test_values_are_read_from_the_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LEAGUE_DATA_SOURCE=Manual\n"
        "AI_PROVIDER=openrouter\n"
        "CHATGPT_MODEL=some-chatgpt-model\n"
        "OPENROUTER_MODEL= maker/some-model \n"
        "OPENROUTER_API_KEY=test-key-not-real\n"
        "WEB_SEARCH_ENABLED=false\n"
        "MAX_WEB_SEARCHES_PER_RUN=2\n"
    )
    settings = load_settings(env_file)
    assert settings.league_data_source == "manual"
    assert settings.ai_provider == "openrouter"
    assert settings.chatgpt_model == "some-chatgpt-model"
    assert settings.openrouter_model == "maker/some-model"
    assert settings.openrouter_api_key == "test-key-not-real"
    assert settings.web_search_enabled is False
    assert settings.max_web_searches_per_run == 2
    assert settings.model_for("chatgpt") == "some-chatgpt-model"
    assert settings.model_for("openrouter") == "maker/some-model"


def test_unknown_value_names_the_setting_and_the_choices(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("AI_PROVIDER=gemini\n")
    with pytest.raises(ConfigError, match="AI_PROVIDER.*chatgpt, openrouter"):
        load_settings(env_file)


@pytest.mark.parametrize(
    "line, complaint",
    [
        ("WEB_SEARCH_ENABLED=maybe", "WEB_SEARCH_ENABLED.*true or false"),
        ("MAX_WEB_SEARCHES_PER_RUN=lots", "MAX_WEB_SEARCHES_PER_RUN.*whole number"),
        ("MAX_WEB_SEARCHES_PER_RUN=-1", "MAX_WEB_SEARCHES_PER_RUN.*whole number"),
    ],
)
def test_a_bad_on_off_or_number_setting_is_explained(tmp_path, line, complaint):
    env_file = tmp_path / ".env"
    env_file.write_text(line + "\n")
    with pytest.raises(ConfigError, match=complaint):
        load_settings(env_file)


def test_the_api_key_never_appears_when_settings_are_printed(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=test-key-not-real\n")
    settings = load_settings(env_file)
    assert "test-key-not-real" not in repr(settings)
    assert "test-key-not-real" not in str(settings)


def test_the_example_file_is_valid_and_holds_no_secrets():
    settings = load_settings(PROJECT_ROOT / ".env.example")
    assert settings.league_data_source == "sample"
    assert settings.openrouter_api_key == ""


def test_saving_a_model_changes_only_that_line(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# my settings\nAI_PROVIDER=openrouter\nOPENROUTER_MODEL=\nOPENROUTER_API_KEY=test-key-not-real\n"
    )

    save_model("openrouter", "maker/new-model", env_file)

    assert env_file.read_text().splitlines() == [
        "# my settings",
        "AI_PROVIDER=openrouter",
        "OPENROUTER_MODEL=maker/new-model",
        "OPENROUTER_API_KEY=test-key-not-real",
    ]
    assert load_settings(env_file).openrouter_model == "maker/new-model"


def test_saving_a_model_creates_the_file_if_needed(tmp_path):
    env_file = tmp_path / ".env"
    save_model("chatgpt", "some-chatgpt-model", env_file)
    assert load_settings(env_file).chatgpt_model == "some-chatgpt-model"


@pytest.mark.parametrize("name", ["gpt-6.1-sol", "maker/model-5.5", "~maker/model-latest"])
def test_the_shapes_real_model_names_take_are_accepted(tmp_path, name):
    env_file = tmp_path / ".env"
    save_model("openrouter", name, env_file)
    assert load_settings(env_file).openrouter_model == name


@pytest.mark.parametrize("bad_name", ["", "two words", "model\nAI_PROVIDER=openrouter", "$(rm)"])
def test_something_that_is_not_a_model_name_is_never_written(tmp_path, bad_name):
    env_file = tmp_path / ".env"
    env_file.write_text("CHATGPT_MODEL=original\n")
    with pytest.raises(ConfigError, match="doesn't look like a model name"):
        save_model("chatgpt", bad_name, env_file)
    assert env_file.read_text() == "CHATGPT_MODEL=original\n"
