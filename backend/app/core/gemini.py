# Gemini AI engine factory — Layer 1 Core (Gemini AI 엔진 팩토리 — Layer 1 핵심)
# Wraps google-generativeai and pins the model name for the platform
# (google-generativeai를 래핑하고 플랫폼의 모델 이름을 고정함)

import google.generativeai as genai

from app.core.config import settings

# Configure Gemini API key once at module load time (모듈 로드 시 Gemini API 키를 한 번만 설정)
genai.configure(api_key=settings.gemini_api_key)

# Pinned model name for the platform (플랫폼에 고정된 모델 이름)
_MODEL_NAME = "gemini-2.5-flash"


def get_gemini_model(system_instruction: str) -> genai.GenerativeModel:
    """Factory that returns a configured GenerativeModel instance.

    Creates a new model instance per call, allowing different system
    instructions for different skills (e.g., sales vs. support agents).
    (호출마다 새 모델 인스턴스를 생성하여 스킬별로 다른 system_instruction 지원)

    Args:
        system_instruction: The system-level instruction string for the model.
            (모델에 대한 시스템 수준 지침 문자열)

    Returns:
        A configured GenerativeModel ready for content generation.
        (콘텐츠 생성 준비가 완료된 설정된 GenerativeModel)
    """
    # Build and return model with pinned name and caller-supplied instruction
    # (고정된 이름과 호출자가 제공한 지침으로 모델 생성 및 반환)
    return genai.GenerativeModel(
        model_name=_MODEL_NAME,
        system_instruction=system_instruction,
    )
