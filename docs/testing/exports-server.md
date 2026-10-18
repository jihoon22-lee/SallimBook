# 사용자 내보내기·감사 서버 검증

SB-037, Issue #46, R-20. `POST /api/v1/exports`와 `GET /api/v1/audit-events`,
생성 API client와 명시적 42개 업무 테이블 목록을 추가한다. DB migration은 추가하지 않는다.

## 동작

현재 가계의 모든 행을 PostgreSQL REPEATABLE READ READ ONLY 시점에서 읽고 JSON/CSV ZIP을
메모리에서 완성한다. 7개 영역의 기록·원본·정정·관계 ID를 유지하며 잔액과 합계를 다시 계산하지 않는다.
전체 계좌/증권번호와 암호문, 보관함, 인증·세션·초대·멱등 원문, 비공개 파일 경로·키·예약은
명시적으로 제외한다. 선택 문서 원본과 업무 메모에 포함된 민감한 내용은 자동 비식별화하지 않는다.

준비 전과 발급 직전에 현재 세션·기기·구성원과 5분 이내 인증 또는 `data.export`의 현재 가계
일회성 증명을 검사한다. 준비 중 권한 철회가 가능하며 발급 직전 재검사 실패 시 ZIP을 반환하지 않는다.
선택 문서는 현재 가계의 ready/활성 연결·버전·크기·checksum을 다시 확인한다.
발급 감사와 grant 소비를 한 트랜잭션에서 마친다. 감사는 서버 발급 사실이며 로컬 저장 완료가 아니다.

100,000행/metadata 16MiB/문서 10개·40MiB/ZIP 64MiB 한도, 준비 30초·전송 120초를 적용한다.
한 프로세스의 준비·전송 슬롯은 실제 worker 종료와 응답 종료/취소 후에만 반환한다.
서버의 공개 파일 URL이나 임시 평문 파일을 만들지 않는다.
JSON은 원본 문자열·정수 원화 십진 문자열·null을 보존한다. CSV 문자열은 `text:` 접두사,
null은 `\N`으로 구분해 스프레드시트 수식 시작과 값 손실을 막는다.

감사 조회는 시각/UUID keyset 페이지와 가계·필터 바인딩, 알려진 변경 필드 이름만 제공한다.
원본 safe_diff와 전후 값은 반환하지 않으며 손상된 metadata는 실패한다.

## 실행한 검증

```bash
uv run --project services/api python scripts/test_database.py services/api/tests/test_exports.py services/api/tests/test_exports_encoding.py -q
uv run --project services/api ruff check services/api/src/sallimbook/exports services/api/src/sallimbook/audit services/api/tests/test_exports.py services/api/tests/test_exports_encoding.py
pnpm api:generate
pnpm typecheck
python3 scripts/validate_docs.py
```

실제 DB/API 17개 + encoding/catalog/취소·응답 수명 44개 = **61개 통과**.
Alembic drift 없음, downgrade base→upgrade head 통과, 전용 시험 DB 정지를 확인했다.
기존 TestClient/httpx deprecation 경고 1개는 남는다.

- 7개 영역의 모든 행·null/0/거액·정정/참조 관계, JSON/CSV/checksum/선택 원본과 비밀 제외를 대조했다.
- 200행을 넘는 목록, 동시 계좌/자산 변경 중 일관된 snapshot, 새 요청의 새 시점을 확인했다.
- 다른 가계, pending/변경/연결 해제 문서, 준비 중 세션·기기 철회와 최근 인증/증명 만료를 거부했다.
- 실제 합성 WebAuthn grant의 목적·가계·세션·기기 바인딩과 일회 소비, 실패 시 비소비를 확인했다.
- Origin/CSRF·no-store, 감사 페이지 경계·필터/가계 변경·손상 원문 차단을 검증했다.
- 수식·탭·개행·전각 기호·문자열 null, 한도 초과, 취소된 실제 worker, 막힌 전송,
  120초 전송 종료와 ASGI에 전달되지 않은 응답 폐기의 슬롯 반환을 검증했다.

독립 검토에서 공개 필드 목록, snapshot과 발급 권한 검사 분리, 실제 worker 소유권,
문서 재검사와 감사 projection을 읽었다. 이후 보관함 서버의 카드 목록 최적화와 문서만 병합했으며
내보내기 계약과 서비스 코드는 바꾸지 않았다. 생성 계약/타입/문서 검증은 병합 뒤 다시 실행한다.

## 남은 인수

웹/Android 다운로드 화면과 실제 HTTPS 사용자 여정, 운영 백업·별도 서버 복원은 별도 변경에서 검증한다.
기본 사용자 ZIP을 운영 복원 백업으로 사용하지 않는다. 두 실제 Galaxy 기기 시험은 아직 수행하지 않았다.
