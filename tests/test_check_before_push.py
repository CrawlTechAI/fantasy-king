import pytest

from scripts.check_before_push import find_secrets, forbidden_reason, private_env_values

# Fake secrets are assembled from pieces so this file never contains a
# complete secret-looking string that the real check would flag.
FAKE = "a1B2c3D4e5" * 4


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "data/fantasy_king.db",
        "data/imports/week4.json",
        "league.sqlite3",
        "chatgpt_tokens.json",
        "chatgpt_session.dpapi",
        "somewhere/chatgpt_session.json",
        "screenshots/roster.png",
        "notes/roster.jpg",
    ],
)
def test_private_files_are_blocked(path):
    assert forbidden_reason(path) is not None


@pytest.mark.parametrize(
    "path", [".env.example", "app.py", "sample_data/sample_league.json", "README.md"]
)
def test_normal_files_are_allowed(path):
    assert forbidden_reason(path) is None


@pytest.mark.parametrize(
    "text, label",
    [
        ("sk-or-v1-" + FAKE, "OpenRouter API key"),
        ("sk-proj-" + FAKE, "OpenAI API key"),
        ("eyJ" + FAKE + ".eyJ" + FAKE + ".sig", "sign-in token (JWT)"),
        ("ghp_" + FAKE, "GitHub token"),
    ],
)
def test_secrets_are_found_in_any_file(text, label):
    assert label in find_secrets("notes.md", f"some text {text} more text")


def test_filled_in_setting_is_found_but_blank_one_is_not():
    filled = "EMAIL_APP_PASSWORD" + "=" + "hunter2hunter2"
    assert find_secrets("notes.txt", filled) == ["filled-in secret setting"]
    assert find_secrets(".env.example", "EMAIL_APP_PASSWORD=\nOPENROUTER_API_KEY=\n") == []


def test_python_constants_are_not_mistaken_for_secrets():
    assert find_secrets("auth.py", 'TOKEN_FILE = "tokens.json"\n') == []


def test_only_private_env_values_are_collected(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AI_PROVIDER=openrouter\nEMAIL_TO=someone@example.com\nOPENROUTER_API_KEY=\n# note\n"
        "EMAIL_ENABLED=false\n"
    )
    assert private_env_values(env_file) == {"EMAIL_TO": "someone@example.com"}
