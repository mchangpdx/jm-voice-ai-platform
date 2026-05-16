# Tests for Gemini AI engine factory (Gemini AI 엔진 팩토리 테스트)
# TDD: tests written before implementation (TDD: 구현 전 테스트 작성)

import os
from unittest.mock import MagicMock, patch

import pytest

# Inject required env vars before importing any app modules — but ONLY if a
# real .env is missing. Unconditional injection bleeds the placeholder host
# into other test files via os.environ (downstream modules then cache _REST
# against a non-resolving host and fail with DNS errors).
# (.env가 없는 CI/fresh checkout에서만 placeholder 주입 — 있으면 .env 로딩 우선)
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if not os.path.isfile(os.path.join(_BACKEND_ROOT, ".env")):
    os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "placeholder-service-role-key")
    os.environ.setdefault("GEMINI_API_KEY", "test-gemini-api-key")


def test_get_gemini_model_returns_generative_model():
    # Factory must call GenerativeModel with correct model_name and system_instruction
    # (팩토리는 올바른 model_name과 system_instruction으로 GenerativeModel을 호출해야 함)
    with patch("google.generativeai.configure"), patch(
        "google.generativeai.GenerativeModel"
    ) as mock_model_cls:
        mock_instance = MagicMock()
        mock_model_cls.return_value = mock_instance

        from app.core.gemini import get_gemini_model

        result = get_gemini_model("You are helpful")

        mock_model_cls.assert_called_once_with(
            model_name="gemini-3.1-flash-lite",
            system_instruction="You are helpful",
        )
        assert result is mock_instance


def test_get_gemini_model_calls_configure():
    # genai.configure must be called with the api_key from settings
    # (genai.configure는 settings의 api_key로 호출되어야 함)
    with patch("google.generativeai.configure") as mock_configure, patch(
        "google.generativeai.GenerativeModel"
    ):
        import importlib
        import sys

        # Reload module to re-execute module-level configure call
        # (모듈 수준 configure 호출 재실행을 위해 모듈 재로드)
        if "app.core.gemini" in sys.modules:
            del sys.modules["app.core.gemini"]

        from app.core.config import settings
        from app.core.gemini import get_gemini_model  # noqa: F401

        mock_configure.assert_called_with(api_key=settings.gemini_api_key)


def test_get_gemini_model_different_instructions():
    # Calling factory twice with different instructions must produce two distinct model instances
    # (서로 다른 system_instruction으로 두 번 호출 시 두 개의 별도 모델 인스턴스가 생성되어야 함)
    with patch("google.generativeai.configure"), patch(
        "google.generativeai.GenerativeModel"
    ) as mock_model_cls:
        instance_a = MagicMock(name="model_a")
        instance_b = MagicMock(name="model_b")
        mock_model_cls.side_effect = [instance_a, instance_b]

        import importlib
        import sys

        if "app.core.gemini" in sys.modules:
            del sys.modules["app.core.gemini"]

        from app.core.gemini import get_gemini_model

        result_a = get_gemini_model("You are a sales agent")
        result_b = get_gemini_model("You are a support agent")

        assert result_a is instance_a
        assert result_b is instance_b
        assert result_a is not result_b
        assert mock_model_cls.call_count == 2
