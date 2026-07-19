"""Gemini API로 텍스트 청크에서 핵심 개념(node)과 관계(edge)를 추출.

LLM 출력은 response_schema로 JSON 형식을 강제하고, 그래도 실패할 경우를
대비해 마크다운 코드펜스 제거 후 수동 파싱을 한 번 더 시도한다. API 호출
실패(타임아웃/네트워크 오류)와 JSON 파싱 실패는 모두 ExtractionError로
감싸서 앱이 죽지 않고 청크 단위로 실패를 격리할 수 있게 한다.
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

from google.genai import Client, types
from google.genai import errors as genai_errors
from pydantic import BaseModel, ValidationError

from .gemini_client import DEFAULT_MODEL
from .pdf_parser import Chunk

_T = TypeVar("_T")

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY_SECONDS = 2.0

# 429(쿼터 초과)와 5xx(서버 오류)는 재시도하면 성공할 가능성이 있는 일시적 오류.
# 400/401/403/404 같은 요청 자체의 문제는 재시도해도 결과가 같으므로 바로 실패시킨다.
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class ExtractionError(Exception):
    """Gemini 호출 또는 응답 파싱에 실패했을 때 발생하는 예외."""


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, genai_errors.APIError):
        return exc.code in _RETRYABLE_STATUS_CODES
    # APIError가 아닌 예외(타임아웃, 연결 끊김 등)는 일시적 오류로 보고 재시도한다.
    return True


def _call_with_retry(
    fn: Callable[[], _T],
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
) -> _T:
    """지수 백오프(+ 지터)로 fn()을 재시도한다. 재시도 불가능한 오류는 즉시 raise한다."""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == max_retries or not _is_retryable(exc):
                raise
            delay = base_delay * (2**attempt) + random.uniform(0, base_delay)
            time.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


class _NodeSchema(BaseModel):
    id: str
    label: str


class _EdgeSchema(BaseModel):
    source: str
    target: str
    label: str


class _GraphSchema(BaseModel):
    nodes: list[_NodeSchema]
    edges: list[_EdgeSchema]


@dataclass
class Node:
    id: str
    label: str
    source_chunk_id: str


@dataclass
class Edge:
    source: str
    target: str
    label: str
    source_chunk_id: str


@dataclass
class GraphExtraction:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


_PROMPT_TEMPLATE = """다음은 문서에서 추출한 텍스트 조각이다. 이 텍스트에서 핵심 개념(node)과
개념 간의 관계(edge)를 추출하라.

규칙:
- 반드시 순수 JSON만 출력한다. 마크다운 코드펜스나 설명 텍스트를 절대 포함하지 않는다.
- node의 id는 이 텍스트 안에서만 고유하면 되는, 영문 소문자와 언더스코어로 이루어진 짧은 식별자로 만든다 (예: concept_1).
- node의 label은 원문에 등장하는 개념명을 원문과 같은 언어로 간결하게 표기한다.
- edge는 두 node 사이의 관계를 나타내며, source/target은 반드시 위에서 정의한 node id를 참조하고, label은 관계를 짧게 설명한다.
- 텍스트에서 명확한 핵심 개념이나 관계를 찾을 수 없으면 nodes와 edges를 빈 배열로 반환한다.

텍스트:
{chunk_text}
"""

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def _strip_code_fences(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text.strip()).strip()


def _parse_response(response: types.GenerateContentResponse, chunk_id: str) -> _GraphSchema:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, _GraphSchema):
        return parsed

    raw_text = (response.text or "").strip()
    if not raw_text:
        raise ExtractionError(f"[{chunk_id}] Gemini 응답이 비어 있습니다.")

    cleaned = _strip_code_fences(raw_text)
    try:
        data = json.loads(cleaned)
        return _GraphSchema.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ExtractionError(f"[{chunk_id}] Gemini 응답을 JSON으로 파싱하지 못했습니다.") from exc


def extract_graph_from_chunk(
    client: Client,
    chunk: Chunk,
    model: str = DEFAULT_MODEL,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
) -> GraphExtraction:
    """하나의 텍스트 청크에서 node/edge를 추출한다.

    쿼터 초과(429)나 서버 오류(5xx) 등 일시적 오류는 지수 백오프로 최대
    max_retries회 재시도한다. 404/400 같은 재시도해도 소용없는 오류는
    바로 실패 처리한다.

    Raises:
        ExtractionError: 재시도 후에도 API 호출(타임아웃/네트워크 오류 포함)에
            실패했거나 응답 JSON 파싱에 실패했을 때.
    """
    prompt = _PROMPT_TEMPLATE.format(chunk_text=chunk.text)

    def call() -> types.GenerateContentResponse:
        return client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_GraphSchema,
            ),
        )

    try:
        response = _call_with_retry(call, max_retries=max_retries, base_delay=retry_base_delay)
    except Exception as exc:
        raise ExtractionError(
            f"[{chunk.id}] Gemini API 호출에 실패했습니다 (재시도 후에도 실패 — "
            f"타임아웃, 네트워크 오류, 또는 재시도 불가능한 오류일 수 있습니다)."
        ) from exc

    graph = _parse_response(response, chunk.id)

    return GraphExtraction(
        nodes=[Node(id=n.id, label=n.label, source_chunk_id=chunk.id) for n in graph.nodes],
        edges=[
            Edge(source=e.source, target=e.target, label=e.label, source_chunk_id=chunk.id)
            for e in graph.edges
        ],
    )


@dataclass
class ChunkExtractionFailure:
    chunk_id: str
    error: str


def extract_graph_from_chunks(
    client: Client,
    chunks: list[Chunk],
    model: str = DEFAULT_MODEL,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
) -> tuple[GraphExtraction, list[ChunkExtractionFailure]]:
    """여러 청크에서 node/edge를 추출한다. 청크 하나의 실패가 전체를 중단시키지 않는다.

    Returns:
        (성공한 청크들의 결과를 합친 GraphExtraction, 실패한 청크 목록)
    """
    all_nodes: list[Node] = []
    all_edges: list[Edge] = []
    failures: list[ChunkExtractionFailure] = []

    for chunk in chunks:
        try:
            result = extract_graph_from_chunk(
                client,
                chunk,
                model=model,
                max_retries=max_retries,
                retry_base_delay=retry_base_delay,
            )
        except ExtractionError as exc:
            failures.append(ChunkExtractionFailure(chunk_id=chunk.id, error=str(exc)))
            continue

        all_nodes.extend(result.nodes)
        all_edges.extend(result.edges)

    return GraphExtraction(nodes=all_nodes, edges=all_edges), failures
