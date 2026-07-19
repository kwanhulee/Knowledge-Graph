# Knowledge-Graph

PDF 문서를 업로드하면 핵심 개념과 관계를 추출해 지식 그래프로 시각화하는 Streamlit 앱.

## 파이프라인

1. **PDF 업로드** — 사용자가 Streamlit UI에서 PDF 파일 업로드
2. **텍스트 추출/청킹** — PDF에서 텍스트를 추출하고 적절한 크기로 청크 분할
3. **LLM 추출** — Gemini API(`gemini-flash-latest`)에 청크를 전달해 핵심 개념(node)과 관계(edge)를 JSON으로 추출
4. **그래프 시각화** — `streamlit-agraph`로 노드/엣지 렌더링
5. **원문 표시** — 그래프에서 노드 클릭 시 해당 개념의 근거가 된 원문(출처 청크)을 표시

## 기술 스택

- Python 3.9+
- Streamlit
- streamlit-agraph
- Gemini API (`gemini-flash-latest`) — 원래 목표는 `gemini-2.5-flash`였으나 현재 프로젝트 API 키에서는 해당 모델 호출이 404(신규 사용자 미제공)로 막혀 있어 대체함. `src/gemini_client.py`의 `DEFAULT_MODEL` 참고

## 핵심 제약사항

### LLM 출력은 반드시 순수 JSON만
- Gemini 호출 시 마크다운 코드펜스(```json)나 설명 텍스트가 섞이지 않도록 프롬프트에서 강제
- 가능하면 Gemini의 구조화 출력(`response_mime_type: application/json` / JSON 스키마) 기능을 사용해 포맷을 강제
- 응답을 그대로 `json.loads`에 넣을 수 있어야 함. 코드펜스가 섞여 나올 가능성에 대비해 파싱 전 방어적으로 스트립하는 처리 포함

### 앱은 절대 죽으면 안 됨 (must never crash)
아래 실패 케이스들은 모두 예외를 잡아 사용자에게 명확한 에러 메시지를 보여주고, 앱은 계속 동작해야 함.

| 실패 케이스 | 처리 방향 |
|---|---|
| PDF 파싱 실패 (손상된 파일, 암호화 등) | try/except로 감싸고 "PDF를 읽을 수 없습니다" 등 사용자 메시지 표시, 다른 파일 재업로드 가능하게 유지 |
| Gemini API 타임아웃/네트워크 오류 | 타임아웃 설정 + 재시도(선택) 후 실패 시 에러 안내, 부분 결과가 있으면 그것만이라도 표시 |
| LLM 응답 JSON 파싱 실패 | `json.loads` 실패 시 예외 처리, 해당 청크는 스킵하고 나머지 청크는 계속 처리, 실패한 청크 목록을 사용자에게 알림 |

- 청크 단위로 실패를 격리할 것 (한 청크의 실패가 전체 파이프라인을 중단시키면 안 됨)
- 모든 외부 호출(PDF 파싱, Gemini API)은 예외 처리 경계를 명확히 두고, 상위 UI 로직까지 예외가 전파되지 않게 함

## 노드/엣지 JSON 스키마 (예시)

LLM 추출 결과는 아래와 같은 구조를 따르도록 프롬프트/스키마를 설계한다. 구현 시 실제 필드는 코드 기준으로 확정한다.

```json
{
  "nodes": [
    { "id": "concept_1", "label": "개념명", "source_chunk_id": "chunk_3" }
  ],
  "edges": [
    { "source": "concept_1", "target": "concept_2", "label": "관계 설명" }
  ]
}
```

## 개발 시 참고

- API 키 등 민감 정보는 `.env`에 두고 커밋하지 않음 (`.gitignore`에 이미 포함됨)
- 아직 초기 단계 프로젝트로 코드가 없으므로, 실제 구현 시 디렉터리 구조/실행 명령이 정해지면 이 문서에 업데이트할 것
