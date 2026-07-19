"""pdfplumber 기반 PDF 텍스트 추출 및 청킹.

PDF에서 텍스트를 추출하고, 문단 경계를 고려해 500~800자 단위의
청크로 분할한다. 손상된 PDF나 텍스트 추출 실패는 PDFParsingError로
명확하게 알린다 (호출부에서 앱을 죽이지 않고 처리할 수 있도록).
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Union

import pdfplumber

DEFAULT_MIN_CHUNK_SIZE = 500
DEFAULT_MAX_CHUNK_SIZE = 800

PDFSource = Union[str, Path, BinaryIO]


class PDFParsingError(Exception):
    """PDF를 열거나 텍스트를 추출하는 데 실패했을 때 발생하는 예외."""


@dataclass
class Chunk:
    id: str
    text: str
    page_start: int
    page_end: int


def _reconstruct_page_text(page: "pdfplumber.page.Page") -> str:
    """줄 간격(레이아웃)을 분석해 문단 경계를 복원한 페이지 텍스트를 만든다.

    pdfplumber의 extract_text()는 원본 PDF에 문단 사이 여백이 있어도
    그 여백을 빈 줄(\\n\\n)로 살려주지 않는 경우가 많아, 텍스트만 보고는
    문단 경계를 구분할 수 없다. 대신 각 줄의 수직 위치(top/bottom)를 보면
    문단이 바뀌는 지점의 줄 간격이 문단 내부 줄 간격보다 뚜렷하게 넓으므로,
    이를 기준으로 문단 경계를 판단해 명시적인 빈 줄을 삽입한다.
    """
    try:
        lines = page.extract_text_lines()
    except Exception:
        lines = []

    if not lines:
        return page.extract_text() or ""

    gaps = [max(lines[i]["top"] - lines[i - 1]["bottom"], 0) for i in range(1, len(lines))]
    normal_gap = statistics.median(gaps) if gaps else 0
    paragraph_break_threshold = normal_gap * 1.5 + 1

    parts = [lines[0]["text"].strip()]
    for i in range(1, len(lines)):
        text = lines[i]["text"].strip()
        if not text:
            continue
        gap = max(lines[i]["top"] - lines[i - 1]["bottom"], 0)
        separator = "\n\n" if gap > paragraph_break_threshold else " "
        parts.append(separator + text)

    return "".join(parts)


def extract_text_by_page(pdf_source: PDFSource) -> list[str]:
    """PDF에서 페이지별 텍스트를 추출한다.

    Args:
        pdf_source: 파일 경로 또는 파일 객체(예: Streamlit UploadedFile).

    Returns:
        페이지 순서대로 텍스트를 담은 리스트 (텍스트가 없는 페이지는 빈 문자열).

    Raises:
        PDFParsingError: 파일을 열 수 없거나(손상/암호화 등) 추출된 텍스트가
            전혀 없을 때(예: 스캔 이미지 기반 PDF).
    """
    try:
        with pdfplumber.open(pdf_source) as pdf:
            if len(pdf.pages) == 0:
                raise PDFParsingError("PDF에 페이지가 없습니다.")

            pages_text: list[str] = []
            for page_number, page in enumerate(pdf.pages, start=1):
                try:
                    text = _reconstruct_page_text(page)
                except Exception as exc:
                    raise PDFParsingError(
                        f"{page_number}페이지에서 텍스트를 추출하는 중 오류가 발생했습니다."
                    ) from exc
                pages_text.append(text)
    except PDFParsingError:
        raise
    except Exception as exc:
        raise PDFParsingError(
            "PDF 파일을 열 수 없습니다. 파일이 손상되었거나 암호화되어 있을 수 있습니다."
        ) from exc

    if not any(text.strip() for text in pages_text):
        raise PDFParsingError(
            "PDF에서 추출된 텍스트가 없습니다. 스캔 이미지 기반 PDF일 수 있습니다."
        )

    return pages_text


_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?다요음됨함])\s+")


def _split_into_paragraphs(page_text: str, page_number: int) -> list[tuple[int, str]]:
    """페이지 텍스트를 (페이지 번호, 문단) 쌍의 리스트로 분리한다."""
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(page_text) if p.strip()]
    if not paragraphs:
        return []
    return [(page_number, p) for p in paragraphs]


def _split_long_paragraph(paragraph: str, max_size: int) -> list[str]:
    """max_size를 초과하는 문단을 문장 경계 기준으로 잘게 나눈다."""
    if len(paragraph) <= max_size:
        return [paragraph]

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(paragraph) if s.strip()]
    if len(sentences) <= 1:
        # 문장 경계로도 나눌 수 없으면 강제로 길이 기준 분할
        return [paragraph[i : i + max_size] for i in range(0, len(paragraph), max_size)]

    pieces: list[str] = []
    buffer = ""
    for sentence in sentences:
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence
        if len(candidate) > max_size and buffer:
            pieces.append(buffer)
            buffer = sentence
        else:
            buffer = candidate
    if buffer:
        pieces.append(buffer)
    return pieces


def chunk_text(
    pages_text: list[str],
    min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
    max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE,
) -> list[Chunk]:
    """페이지별 텍스트를 문단 경계를 고려해 min~max 글자 수 청크로 묶는다.

    문단이 max_chunk_size를 넘으면 문장 단위로 재분할하고, 그래도 나눌 수
    없으면 길이 기준으로 강제 분할한다. max_chunk_size는 절대 넘지 않도록
    보장하지만, min_chunk_size는 문단 경계를 지키기 위한 목표치일 뿐이라
    문단 하나가 그보다 작으면(그리고 이웃 문단과 합치면 max를 넘으면)
    그보다 작은 청크가 나올 수 있다.

    Raises:
        PDFParsingError: 청킹할 텍스트가 하나도 없을 때.
    """
    all_paragraphs: list[tuple[int, str]] = []
    for page_number, page_text in enumerate(pages_text, start=1):
        all_paragraphs.extend(_split_into_paragraphs(page_text, page_number))

    if not all_paragraphs:
        raise PDFParsingError("청킹할 텍스트가 없습니다.")

    chunks: list[Chunk] = []
    buffer_text = ""
    buffer_page_start: int | None = None
    buffer_page_end: int | None = None

    def flush() -> None:
        nonlocal buffer_text, buffer_page_start, buffer_page_end
        if buffer_text.strip():
            chunks.append(
                Chunk(
                    id=f"chunk_{len(chunks) + 1}",
                    text=buffer_text.strip(),
                    page_start=buffer_page_start or 0,
                    page_end=buffer_page_end or buffer_page_start or 0,
                )
            )
        buffer_text = ""
        buffer_page_start = None
        buffer_page_end = None

    for page_number, paragraph in all_paragraphs:
        for piece in _split_long_paragraph(paragraph, max_chunk_size):
            candidate = f"{buffer_text}\n\n{piece}".strip() if buffer_text else piece

            if len(candidate) > max_chunk_size and buffer_text:
                flush()
                candidate = piece

            buffer_text = candidate
            buffer_page_start = buffer_page_start or page_number
            buffer_page_end = page_number

            if len(buffer_text) >= max_chunk_size:
                flush()

    flush()

    return _merge_small_chunks(chunks, min_chunk_size, max_chunk_size)


def _merge_small_chunks(
    chunks: list[Chunk], min_chunk_size: int, max_chunk_size: int
) -> list[Chunk]:
    """min_chunk_size에 못 미치는 청크를 다음 청크와 합쳐도 max를 넘지 않으면 합친다."""
    merged: list[Chunk] = []
    for chunk in chunks:
        if (
            merged
            and len(merged[-1].text) < min_chunk_size
            and len(merged[-1].text) + 2 + len(chunk.text) <= max_chunk_size
        ):
            previous = merged.pop()
            merged.append(
                Chunk(
                    id=previous.id,
                    text=f"{previous.text}\n\n{chunk.text}",
                    page_start=previous.page_start,
                    page_end=chunk.page_end,
                )
            )
        else:
            merged.append(chunk)

    for index, chunk in enumerate(merged, start=1):
        chunk.id = f"chunk_{index}"

    return merged


def parse_pdf(
    pdf_source: PDFSource,
    min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
    max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE,
) -> list[Chunk]:
    """PDF에서 텍스트를 추출하고 청크 리스트로 변환한다.

    Raises:
        PDFParsingError: 추출 또는 청킹 과정에서 실패했을 때.
    """
    pages_text = extract_text_by_page(pdf_source)
    return chunk_text(pages_text, min_chunk_size=min_chunk_size, max_chunk_size=max_chunk_size)
