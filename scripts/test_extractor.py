"""extractor.py 동작 확인용 수동 테스트 스크립트.

sample_pdfs/sample_pdfs.pdf를 파싱한 청크 중 일부를 실제 Gemini API로
추출해보고, node/edge 결과와 실패 처리(청크 단위 격리)를 확인한다.

실행:
    .venv/bin/python3 scripts/test_extractor.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extractor import ExtractionError, extract_graph_from_chunk, extract_graph_from_chunks
from src.gemini_client import get_gemini_client
from src.pdf_parser import parse_pdf


def main() -> None:
    pdf_path = Path("sample_pdfs/sample_pdfs.pdf")
    chunks = parse_pdf(str(pdf_path))
    print(f"청크 {len(chunks)}개 파싱 완료\n")

    client = get_gemini_client()

    print("=== 단일 청크 추출 (chunk_1) ===")
    result = extract_graph_from_chunk(client, chunks[0])
    print(f"nodes={len(result.nodes)}, edges={len(result.edges)}")
    for node in result.nodes:
        print(f"  node: {node}")
    for edge in result.edges:
        print(f"  edge: {edge}")

    print("\n=== 순수 JSON 강제 확인 (마크다운 펜스 없이 파싱됨) ===")
    print("위에서 예외 없이 파싱됐다면 response_schema로 순수 JSON이 강제된 것")

    print("\n=== 여러 청크 일괄 추출 (전체) ===")
    graph, failures = extract_graph_from_chunks(client, chunks)
    print(f"성공: nodes={len(graph.nodes)}, edges={len(graph.edges)}")
    print(f"실패한 청크 수: {len(failures)}")
    for failure in failures:
        print(f"  실패: {failure}")

    print("\n=== 실패 격리 확인 (존재하지 않는 모델로 강제 실패) ===")
    try:
        extract_graph_from_chunk(client, chunks[0], model="gemini-2.5-flash")
        print("예상과 다르게 성공함 (모델이 이제 사용 가능해진 걸 수도 있음)")
    except ExtractionError as exc:
        print(f"예상대로 ExtractionError 발생 (앱이 죽지 않음): {exc}")


if __name__ == "__main__":
    main()
