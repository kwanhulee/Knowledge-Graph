"""Gemini API 클라이언트 초기화.

.env의 GEMINI_API_KEY로 google-genai SDK 클라이언트를 생성한다.
"""

from __future__ import annotations

from google import genai
from google.genai import types

from .config import get_gemini_api_key

DEFAULT_MODEL = "gemini-flash-latest"
DEFAULT_TIMEOUT_MS = 30_000


def get_gemini_client(timeout_ms: int = DEFAULT_TIMEOUT_MS) -> genai.Client:
    """GEMINI_API_KEY로 Gemini API 클라이언트를 생성한다.

    API 타임아웃으로 인해 앱이 무한정 멈추지 않도록 요청 타임아웃을 설정한다.

    Raises:
        ConfigError: GEMINI_API_KEY가 설정되어 있지 않을 때.
    """
    api_key = get_gemini_api_key()
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=timeout_ms,
            # SDK 자체 재시도는 끄고, 재시도 정책은 extractor.py에서 직접 제어한다
            # (그래야 재시도 횟수/대기 시간을 예측 가능하게 관리할 수 있다).
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
