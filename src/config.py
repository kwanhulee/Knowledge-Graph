"""환경 변수 기반 설정 로드.

.env 파일에서 GEMINI_API_KEY 등을 읽어온다.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    """필수 환경 변수가 설정되어 있지 않을 때 발생하는 예외."""


def get_gemini_api_key() -> str:
    """GEMINI_API_KEY 환경 변수를 반환한다.

    Raises:
        ConfigError: GEMINI_API_KEY가 설정되어 있지 않을 때.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ConfigError(
            "GEMINI_API_KEY가 설정되어 있지 않습니다. "
            "프로젝트 루트에 .env 파일을 만들고 GEMINI_API_KEY=발급받은_키 를 추가하세요."
        )
    return api_key
