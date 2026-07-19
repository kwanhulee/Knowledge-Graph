"""pdf_parser.py 동작 확인용 수동 테스트 스크립트.

실행:
    python scripts/test_pdf_parser.py [PDF_경로]

기본값으로 sample_pdfs/sample_pdfs.pdf 를 사용한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pdf_parser import PDFParsingError, parse_pdf

PREVIEW_LENGTH = 120


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sample_pdfs/sample_pdfs.pdf")

    if not pdf_path.exists():
        print(f"파일을 찾을 수 없습니다: {pdf_path}")
        sys.exit(1)

    print(f"대상 파일: {pdf_path}")

    try:
        chunks = parse_pdf(str(pdf_path))
    except PDFParsingError as exc:
        print(f"[PDFParsingError] {exc}")
        sys.exit(1)

    print(f"\n총 청크 개수: {len(chunks)}\n")

    lengths = [len(c.text) for c in chunks]
    print(f"청크 길이 - 최소: {min(lengths)}, 최대: {max(lengths)}, 평균: {sum(lengths) / len(lengths):.1f}\n")

    for chunk in chunks:
        preview = chunk.text[:PREVIEW_LENGTH].replace("\n", " ")
        ellipsis = "..." if len(chunk.text) > PREVIEW_LENGTH else ""
        print(
            f"[{chunk.id}] page {chunk.page_start}-{chunk.page_end}, "
            f"len={len(chunk.text)}\n  {preview}{ellipsis}\n"
        )


if __name__ == "__main__":
    main()
