"""Safety check to run before every push to GitHub.

Run from the project folder:
    .venv\\Scripts\\python scripts\\check_before_push.py

It lists every file that would be uploaded and stops with a FAILED message if:
  - a private file (settings, league data, database, screenshot) is in the list
  - the .gitignore rules that protect those files are not working
  - any file contains something that looks like a key, password, or sign-in token
  - any file contains a private value copied from your .env file
"""

import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Files that must never be uploaded, and why.
FORBIDDEN_PATHS = {
    ".env": "settings file with secrets",
    ".env.*": "settings file with secrets",
    "data/*": "your league data",
    "*.db": "database file",
    "*.sqlite": "database file",
    "*.sqlite3": "database file",
    "*token*.json": "sign-in token file",
    "chatgpt_session.*": "saved ChatGPT sign-in",
    "*.dpapi": "saved ChatGPT sign-in",
    "screenshots/*": "screenshot",
    "imports/*": "pasted league data",
    "*.png": "image (possible screenshot)",
    "*.jpg": "image (possible screenshot)",
    "*.jpeg": "image (possible screenshot)",
    ".venv/*": "virtual environment",
}
ALLOWED_PATHS = {".env.example"}

# These must be reported as ignored by Git, proving .gitignore is doing its job.
MUST_BE_IGNORED = [
    ".env",
    "data/fantasy_king.db",
    "data/screenshots/roster.png",
    "chatgpt_session.dpapi",
    "chatgpt_session.json",
]

SECRET_PATTERNS = {
    "OpenRouter API key": re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}"),
    "OpenAI API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "sign-in token (JWT)": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\."),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
# A settings line with a secret-sounding name and a filled-in value.
FILLED_IN_SETTING = re.compile(
    r"^[A-Z0-9_]*(?:KEY|SECRET|PASSWORD|TOKEN)[A-Z0-9_]*[ \t]*=[ \t]*[^\s#]+", re.MULTILINE
)
PRIVATE_ENV_NAMES = re.compile(r"KEY|SECRET|PASSWORD|TOKEN|EMAIL|LEAGUE_ID")
ON_OFF_VALUES = {"true", "false"}
MAX_SCAN_BYTES = 2_000_000


def forbidden_reason(path: str) -> str | None:
    """Why this file must not be uploaded, or None if it is fine."""
    if path in ALLOWED_PATHS:
        return None
    name = path.rsplit("/", 1)[-1]
    for pattern, reason in FORBIDDEN_PATHS.items():
        if fnmatch(path, pattern) or fnmatch(name, pattern) or fnmatch(path, f"*/{pattern}"):
            return reason
    return None


def find_secrets(path: str, text: str) -> list[str]:
    """Names of the secret types that appear in this file's text."""
    found = [label for label, pattern in SECRET_PATTERNS.items() if pattern.search(text)]
    # Python code has many harmless lines like TOKEN_FILE = ..., so only check other files.
    if not path.endswith(".py") and FILLED_IN_SETTING.search(text):
        found.append("filled-in secret setting")
    return found


def private_env_values(env_file: Path) -> dict[str, str]:
    """Private values from .env, so we can make sure none were copied into another file."""
    values = {}
    if not env_file.exists():
        return values
    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip().strip("\"'")
        if separator and not name.startswith("#") and PRIVATE_ENV_NAMES.search(name):
            # On/off settings like EMAIL_ENABLED=false are not private.
            if len(value) >= 5 and value.lower() not in ON_OFF_VALUES:
                values[name] = value
    return values


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8"
    )


def files_git_would_upload() -> list[str]:
    # Files Git already tracks, plus new files that .gitignore does not exclude.
    result = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return sorted(path for path in result.stdout.split("\0") if path)


def main() -> int:
    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        print("This folder is not a Git repository yet, so there is nothing to check.")
        return 2

    files = [path for path in files_git_would_upload() if (PROJECT_ROOT / path).exists()]
    env_values = private_env_values(PROJECT_ROOT / ".env")
    problems = []

    for path in MUST_BE_IGNORED:
        if git("check-ignore", "-q", path).returncode != 0:
            problems.append(f".gitignore is not protecting {path}")

    for path in files:
        reason = forbidden_reason(path)
        if reason:
            problems.append(f"{path}: {reason}, must not be uploaded")
            continue
        file = PROJECT_ROOT / path
        if file.stat().st_size > MAX_SCAN_BYTES:
            problems.append(f"{path}: too large to scan ({file.stat().st_size:,} bytes)")
            continue
        text = file.read_text(encoding="utf-8", errors="ignore")
        for label in find_secrets(path, text):
            problems.append(f"{path}: possible {label}")
        for name, value in env_values.items():
            if value in text:
                problems.append(f"{path}: contains your {name} value from .env")

    print(f"Files that would be uploaded ({len(files)}):")
    for path in files:
        print(f"  {path}")
    print()
    if problems:
        print(f"FAILED: {len(problems)} problem(s) found. Do NOT push yet.")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("PASSED: no secrets or private files found. Safe to push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
