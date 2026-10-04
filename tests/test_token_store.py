import sys

import pytest

from fantasy_king.ai.token_store import SESSION_FILE, TokenStore, TokenStoreError, app_dir

STATE = {"host_id": "urn:uuid:abc", "accounts": {"u": {"refresh_token": "very-private"}}, "active": "u"}


def test_nothing_saved_yet_gives_an_empty_sign_in(store):
    assert store.load() == {"host_id": None, "accounts": {}, "active": None}


def test_what_is_saved_comes_back(store):
    store.save(STATE)
    assert TokenStore(store.directory).load() == STATE


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI encryption is Windows only")
def test_the_file_on_disk_is_encrypted(store):
    store.save(STATE)
    on_disk = store.path.read_bytes()
    assert b"very-private" not in on_disk
    assert b"refresh_token" not in on_disk


@pytest.mark.skipif(sys.platform == "win32", reason="File permissions are checked off Windows")
def test_the_file_is_readable_only_by_its_owner(store):
    store.save(STATE)
    assert store.path.stat().st_mode & 0o777 == 0o600


def test_saving_leaves_no_temporary_file_behind(store):
    store.save(STATE)
    assert [path.name for path in store.directory.iterdir()] == [SESSION_FILE]


def test_a_damaged_file_is_reported_not_guessed_at(store):
    store.directory.mkdir(parents=True)
    store.path.write_bytes(b"not a valid saved sign-in")
    with pytest.raises(TokenStoreError, match="couldn't be read"):
        store.load()


def test_clear_removes_the_saved_sign_in(store):
    store.save(STATE)
    store.clear()
    store.clear()  # clearing twice is harmless
    assert store.load()["accounts"] == {}


def test_only_one_holder_of_the_lock_at_a_time(store):
    with store.lock():
        with pytest.raises(TokenStoreError, match="too long"):
            with TokenStore(store.directory).lock(timeout=0.3):
                pass
    with store.lock(timeout=0.3):  # released, so it can be taken again
        pass


def test_the_sign_in_is_kept_outside_the_project_folder(monkeypatch):
    from fantasy_king.ai.token_store import HOME_ENV
    from fantasy_king.config import PROJECT_ROOT

    monkeypatch.delenv(HOME_ENV)
    assert PROJECT_ROOT not in app_dir().parents
    assert app_dir() != PROJECT_ROOT
