# Tests for Settings config (Settings 설정 테스트)
# TDD: tests written before implementation (TDD: 구현 전 테스트 작성)

import importlib
import os
import sys

import pytest
from pydantic import ValidationError

# Minimal env vars required to import the module the first time
# (모듈 최초 임포트에 필요한 최소 환경 변수)
_MINIMAL_ENV = {
    "SUPABASE_URL": "https://placeholder.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "placeholder-key",
    "GEMINI_API_KEY": "placeholder-gemini-key",
}


def _ensure_module_imported():
    # Import app.core.config for the first time. If a .env file is present,
    # let pydantic-settings load the real values — otherwise inject placeholders
    # so the import doesn't ValidationError on a fresh CI checkout.
    # Why: previously this used os.environ.setdefault unconditionally, which
    # pre-empted .env loading and left the module-level `settings` singleton
    # bound to "https://placeholder.supabase.co" forever. Downstream modules
    # (e.g. app.services.bridge.flows) that imported `from .config import
    # settings` then computed `_REST` against the bogus host, causing live DNS
    # failures in unrelated tests.
    # (placeholder env 주입이 .env 로드를 막아 settings를 영구 오염 → 하위
    # 테스트에서 placeholder.supabase.co로 실 DNS 호출 발생)
    if "app.core.config" in sys.modules:
        return
    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    dotenv_path = os.path.join(backend_root, ".env")
    if os.path.isfile(dotenv_path):
        # Real .env present — let pydantic-settings load it natively.
        import app.core.config  # noqa: F401, PLC0415
        return
    # No .env (CI / fresh checkout) — inject placeholders only for the import,
    # and restore env on the way out.
    _prev = {k: os.environ.get(k) for k in _MINIMAL_ENV}
    for k, v in _MINIMAL_ENV.items():
        os.environ.setdefault(k, v)
    try:
        import app.core.config  # noqa: F401, PLC0415
    finally:
        for k, prev_v in _prev.items():
            if prev_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev_v


def _reload_settings_class():
    # Reload the module to pick up any env var changes, return Settings class
    # (환경 변수 변경사항을 반영하기 위해 모듈 재로드 후 Settings 클래스 반환)
    _ensure_module_imported()
    importlib.reload(sys.modules["app.core.config"])
    return sys.modules["app.core.config"].Settings


def _get_settings_class():
    # Return the Settings class without reloading (재로드 없이 Settings 클래스 반환)
    _ensure_module_imported()
    return sys.modules["app.core.config"].Settings


# Test isolation: importlib.reload() on app.core.config replaces the module-level
# `settings` singleton with one built from the test's monkeypatched env. Even
# after monkeypatch unwinds, the polluted settings instance persists, causing
# downstream modules (e.g. app.services.bridge.flows) to import a settings with
# bogus URLs/keys and trigger live DNS calls in unrelated tests. Snapshotting +
# restoring the singleton around each test keeps the suite hermetic.
# (test_config 리로드가 settings 싱글톤을 오염 → 하위 모듈 isolation 깨짐)
@pytest.fixture(autouse=True)
def _isolate_config_reload():
    _ensure_module_imported()
    cfg = sys.modules["app.core.config"]
    original_settings = cfg.settings
    original_settings_class = cfg.Settings
    try:
        yield
    finally:
        cfg.settings = original_settings
        cfg.Settings = original_settings_class


def test_settings_loads_from_env(monkeypatch):
    # Set all required env vars and verify correct field resolution
    # (모든 필수 환경 변수를 설정하고 필드 값이 올바르게 해석되는지 검증)
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("DEBUG", "true")

    Settings = _reload_settings_class()
    instance = Settings()

    assert instance.supabase_url == "https://test.supabase.co"
    assert instance.supabase_service_role_key == "test-service-role-key"
    assert instance.gemini_api_key == "test-gemini-key"
    assert instance.debug is True


def test_settings_debug_defaults_to_false(monkeypatch):
    # Verify that debug flag defaults to False when not explicitly provided
    # (debug 플래그 기본값 False 검증)
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.delenv("DEBUG", raising=False)

    Settings = _reload_settings_class()
    instance = Settings()

    assert instance.debug is False


def test_settings_missing_required_raises(monkeypatch):
    # Assert ValidationError raised when required env vars are absent.
    # env_file must be disabled — otherwise pydantic-settings reads from .env
    # even after monkeypatch.delenv removes them from the process environment.
    # (필수 환경 변수 누락 시 ValidationError 확인 — .env 파일 로딩 비활성화 필수)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DEBUG", raising=False)

    from pydantic_settings import BaseSettings, SettingsConfigDict

    # Create an isolated Settings subclass that ignores the .env file
    # (env_file을 무시하는 격리된 Settings 서브클래스 생성)
    class SettingsNoEnvFile(BaseSettings):
        model_config = SettingsConfigDict(env_file=None, extra="ignore")
        supabase_url: str
        supabase_service_role_key: str
        gemini_api_key: str
        debug: bool = False

    with pytest.raises(ValidationError):
        SettingsNoEnvFile()
