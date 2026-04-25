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
    # Import app.core.config for the first time, injecting minimal env vars if needed
    # (최초 임포트 시 최소 환경 변수를 주입하여 app.core.config 임포트 보장)
    if "app.core.config" not in sys.modules:
        _prev = {k: os.environ.get(k) for k in _MINIMAL_ENV}
        for k, v in _MINIMAL_ENV.items():
            os.environ.setdefault(k, v)
        try:
            import app.core.config  # noqa: F401, PLC0415
        finally:
            # Restore original env state (원래 환경 변수 상태 복원)
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
    # Assert ValidationError raised when required env vars are absent
    # (필수 환경 변수 누락 시 ValidationError 발생 확인)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DEBUG", raising=False)

    # Use cached Settings class; instantiation reads env vars fresh each time
    # (캐시된 Settings 클래스 사용; 인스턴스화 시 매번 환경 변수를 새로 읽음)
    Settings = _get_settings_class()

    with pytest.raises(ValidationError):
        Settings()
