from concurrent.futures import ThreadPoolExecutor
import importlib

import pytest

backend = importlib.import_module("app.app")


@pytest.mark.parametrize("configured", [None, "", "   "])
def test_generated_key_is_persistent(monkeypatch, tmp_path, configured):
    if configured is None:
        monkeypatch.delenv("SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("SECRET_KEY", configured)
    key_file = tmp_path / "config" / ".secret_key"
    with ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(lambda _: backend._load_secret_key(key_file), range(16)))
    assert len(set(keys)) == 1
    assert len(keys[0]) == 64
    assert backend._load_secret_key(key_file) == keys[0]
    assert key_file.stat().st_mode & 0o777 == 0o600

    monkeypatch.setitem(backend.app.config, "SECRET_KEY", keys[0])
    with backend.app.test_client() as client:
        assert client.get("/kontakt").status_code == 200
        with client.session_transaction() as session:
            assert session["captcha_answer"].isdigit()


def test_explicit_key_takes_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY", "explicit-test-secret")
    key_file = tmp_path / ".secret_key"
    assert backend._load_secret_key(key_file) == "explicit-test-secret"
    assert not key_file.exists()


def test_empty_persisted_key_fails_at_startup(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    key_file = tmp_path / ".secret_key"
    key_file.touch()
    with pytest.raises(RuntimeError, match="Session secret file is empty"):
        backend._load_secret_key(key_file)
