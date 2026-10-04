"""Keeps your ChatGPT sign-in on this computer, outside the project folder.

The sign-in lives in your user profile (not in the project), so it can never be
committed to GitHub by accident. On Windows the file is encrypted with DPAPI,
the built-in protection tied to your Windows account: another user, or the same
file copied to another computer, cannot read it. On other systems the file is
plain JSON readable only by you (permissions 0600), as OpenAI's docs ask.
"""

import ctypes
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Set this to keep the sign-in somewhere else (the tests use it).
HOME_ENV = "FANTASY_KING_HOME"

USES_DPAPI = sys.platform == "win32"
SESSION_FILE = "chatgpt_session.dpapi" if USES_DPAPI else "chatgpt_session.json"
LOCK_FILE = "chatgpt_session.lock"


class TokenStoreError(Exception):
    """The saved sign-in could not be read or written."""


def app_dir() -> Path:
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override)
    if USES_DPAPI:
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return Path(base) / "FantasyKing"
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "fantasy_king"


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_char))]


def _dpapi(function_name: str, data: bytes) -> bytes:
    """Run CryptProtectData or CryptUnprotectData for the current Windows user."""
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buffer = ctypes.create_string_buffer(data, len(data))
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    result = _Blob()
    no_prompts = 0x1  # CRYPTPROTECT_UI_FORBIDDEN: never pop up a dialog
    function = getattr(crypt32, function_name)
    if not function(
        ctypes.byref(source), None, None, None, None, no_prompts, ctypes.byref(result)
    ):
        raise OSError(f"{function_name} failed (Windows error {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel32.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


def protect(data: bytes) -> bytes:
    return _dpapi("CryptProtectData", data) if USES_DPAPI else data


def unprotect(data: bytes) -> bytes:
    return _dpapi("CryptUnprotectData", data) if USES_DPAPI else data


def _try_lock(handle) -> None:
    handle.seek(0)
    if USES_DPAPI:
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle) -> None:
    handle.seek(0)
    if USES_DPAPI:
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def empty_state() -> dict:
    return {"host_id": None, "accounts": {}, "active": None}


class TokenStore:
    """Reads and writes the saved sign-in as one protected file."""

    def __init__(self, directory: Path | str | None = None):
        self.directory = Path(directory) if directory else app_dir()

    @property
    def path(self) -> Path:
        return self.directory / SESSION_FILE

    def load(self) -> dict:
        if not self.path.exists():
            return empty_state()
        try:
            return {**empty_state(), **json.loads(unprotect(self.path.read_bytes()))}
        except (OSError, ValueError) as problem:
            raise TokenStoreError(
                "The saved ChatGPT sign-in on this computer couldn't be read."
            ) from problem

    def save(self, state: dict) -> None:
        """Write atomically, so a crash can never leave a half-written file."""
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
            descriptor = os.open(temporary, flags, 0o600)
            with os.fdopen(descriptor, "wb") as file:
                file.write(protect(json.dumps(state).encode("utf-8")))
            os.replace(temporary, self.path)
        except OSError as problem:
            raise TokenStoreError(
                f"The ChatGPT sign-in couldn't be saved in {self.directory}."
            ) from problem

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    @contextmanager
    def lock(self, timeout: float = 30.0):
        """Let only one process at a time change the sign-in.

        OpenAI replaces the refresh token on every refresh. If the dashboard and
        a scheduled check both refreshed at once, one would be left holding a
        dead token, so refreshes take this lock first.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout
        with open(self.directory / LOCK_FILE, "a+b") as handle:
            while True:
                try:
                    _try_lock(handle)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TokenStoreError(
                            "Another Fantasy King process has been using the sign-in for too "
                            "long. Close other Fantasy King windows and try again."
                        ) from None
                    time.sleep(0.1)
            try:
                yield
            finally:
                _unlock(handle)
