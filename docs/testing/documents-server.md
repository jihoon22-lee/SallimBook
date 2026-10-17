# 첨부 서버 검증

대상: SB-023, Issue #32, R-13/R-15/R-20. 보험계약·사건·진료·비용·청구·가전·자산의
typed 연결, 암호화 원본 저장과 인증 다운로드를 API 9개로 제공한다.

## 실행 결과

```bash
uv run --project services/api python scripts/test_database.py services/api/tests/test_documents.py services/api/tests/test_document_storage.py services/api/tests/test_document_validation.py -q
uv run --project services/api --frozen python scripts/test_document_tools.py
pnpm api:generate
pnpm typecheck
uv run --project services/api ruff check services/api/src services/api/tests services/api/migrations
python3 scripts/validate_docs.py
```

API·실제 PostgreSQL 39개, 암호화·파일 저장소 30개, 검사 계약 81개로 **150개 통과**했다.
Alembic `upgrade head`, drift 검사, 전체 downgrade/upgrade도 통과했으며 전용 DB를 정지했다.
초기 실패는 링크 종료 중 autoflush로 문서 버전을 두 번 올린 문제와 긴 임시 Unix socket 경로였다.
버전 갱신 전 링크 수를 조회하고 합성 socket 경로를 짧게 고친 뒤 관련 검사와 135개 전체를 다시 통과했다.

다른 가계의 목록/연결/업로드/다운로드/삭제 차단, 부부 공동 접근, 크기·MIME·경로·해시 검증,
DB 직접 우회, 암호문 치환·훼손·권한·symlink/hardlink 거부, 멱등 참조 보존을 확인했다.
검사 중 세션 철회와 연결 종료, 복호화 후 인증 만료, 느린 본문 수신 중 세션 철회,
동시 삭제/링크 추가도 포함한다. 파일에 원문이 저장되지 않고 복원 checksum이 일치함을 검사한다.

실제 ClamAV 1.4.6·Pillow 13.0.0·pypdf 6.21.1·Poppler·Tesseract 도구 검사 **20개도 통과**했다.
합성 영어/한글 영수증 PNG/JPEG/PDF 허용과 EICAR·카드 라벨/PAN·실행 PDF·빈 이미지·도구 장애 거부,
검사 후 RAM spool 정리를 확인했다. 81개 검사에 있는 가짜 Unix daemon/OCR 경계 시험과 구분한다.
고정 버전·이미지 ID·자원 제한·공식 근거는 [도구 기록](../../infra/documents/README.md)에 있다.

## 상태와 정리

업로드 생성은 최초 링크까지 원자적으로 저장한다. pending은 24시간 후 만료되며 원본 저장 전의
metadata와 연결 이력은 유지된다. 마지막 링크를 종료한 ready 문서는 orphaned_at을 기록하지만
사용자의 명시적 삭제 전까지 원본을 보존한다. 다시 연결하면 이 시각을 비운다.
문서 삭제는 현재 링크를 모두 종료하고 즉시 다운로드를 막으며, 암호문 물리 정리는 24시간 후 가능하다.

```bash
uv run --project services/api python scripts/cleanup_documents.py
# 위 dry-run의 개수를 검토한 뒤 같은 설정으로 실행한다.
uv run --project services/api python scripts/cleanup_documents.py --apply
```

정리는 저장소 안의 서비스 소유·0600·단일 link·규격 UUID 파일만 검사한다. 다른 파일·symlink·
현재 DB 참조·최근 파일은 보존한다. 업로드는 DB commit까지 exclusive advisory lock을 가지며
정리는 exclusive lock 안에서 DB 참조와 파일을 대조해 진행 중인 업로드를 지우지 않는다.
정리 결과에는 개수만 출력하며 파일명·원문·암호키를 출력하지 않는다.

## 남은 인수

이 PR은 서버와 검사 도구 범위다. 웹·Android 파일 선택/저장·연결 화면과 실제 HTTPS 흐름은
클라이언트 변경에서 검증한다. 실제 Galaxy 실패 시나리오와 운영 scanner 배포·백업 복원은
전체 기능 구현 뒤에 수행하며 서버 시험이나 debug 빌드를 실기기 보안 인수로 간주하지 않는다.

PR 리뷰 보완: 본문을 읽기 전에 API 프로세스당 업로드 한 개로 제한하며 초과는 503이다.
본문 취소·검증 실패 때 슬롯을 반환하고, 검사 중 HTTP 취소는 worker가 끝날 때까지 슬롯을 유지한다.
worker는 요청 dependency와 별도 DB session을 소유해 취소된 요청의 session 종료와 겹치지 않는다.
실제 비동기 ASGI 수신으로 선행 제한·본문 미수신·취소/실패 후 재사용·worker 완료를 4개 추가 검증했다.
새 서명 갱신 날짜 build 인자를 포함한 도구 이미지의 build-only도 통과했다.

두 번째 리뷰 보완: API의 가계 잠금에 더해 연결 종료도 문서→연결 순서로 잠근다.
부모를 잠근 직접 저장소 트랜잭션이 자식 링크를 기다리지 않고 끝낼 수 있으며, 그 뒤 API는
변경된 버전을 409로 반환함을 실제 경합 시험으로 확인했다. 가전의 문서 연결을 종료해도 과거
연결 이력이 있으면 가전 물리 삭제를 막는 회귀를 추가했다. 총141개와 Alembic drift/왕복을 통과했다.


세 번째 리뷰 보완: 저장 전에 독립 DB 트랜잭션으로 파일명·가계·문서·암호문 크기를 예약한다.
기본 가계 한도는 256MiB/200개, 전체는 2GiB/2,000개이며 AES-GCM tag 16바이트도 센다.
실패·취소·DB rollback이나 commit 결과 불명에도 예약은 유지된다. ready 문서의 마지막 연결 종료나
논리 삭제만으로는 용량을 반환하지 않는다. 24시간 유예 뒤 정리 작업이 실제 제거와 fsync 또는 파일
부재를 확인해야 반환한다. dry-run은 예약을 바꾸지 않는다. 모든 API worker는 같은 설정과 DB를 사용한다.
저장/정리 공통 exclusive barrier가 프로세스 사이의 디스크 쓰기를 직렬화하며 별도 quota 잠금이
용량 집계·예약 commit을 보호한다. 문서는 NO KEY UPDATE로 잠가 독립 예약의 가계 복합 FK 검사를 허용한다.
현재 파일을 가리키는 용량 예약의 직접 해제·변조·삭제와 예약 없는 ready 전환도 DB가 거부한다.

가계/전체 byte·count 경계, 한도 중 멱등 재전송, 다른 가계 동시 업로드, 저장 후 오류로 남은 파일,
연결 종료/삭제/정리의 용량 반환, 디스크 여유 공간과 직접 DB 우회 9개를 추가해 총150개를 통과했다.
설정은 `SALLIMBOOK_DOCUMENT_HOUSEHOLD_QUOTA_BYTES/COUNT`, `SALLIMBOOK_DOCUMENT_GLOBAL_QUOTA_BYTES/COUNT`,
`SALLIMBOOK_DOCUMENT_MIN_FREE_BYTES`이며 기본 여유 공간 1GiB를 남기지 못하면 쓰기 전에 503을 반환한다.
용량은 413 `DOCUMENT_STORAGE_QUOTA_EXCEEDED`, 디스크 여유는 503 `DOCUMENT_STORAGE_CAPACITY_UNAVAILABLE`다.
이미 내려받은 파일이나 운영 백업 공간은 이 온라인 저장소 한도와 별도로 관리한다.
