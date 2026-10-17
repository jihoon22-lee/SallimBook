# 보관함 서버 검증

SB-028~SB-032, Issues #37~41, R-09/R-10/R-11/R-12/R-20. 서버 구현은 23개 opaque API와
0014_vault의 11개 테이블·불변 제약이다. 실제 암호화는 Android/PC client에서 수행한다.

## 구현과 보안 경계

일반 가계 가입과 보관함 공유를 분리한다. 본인 current wrapping만 조회하며 공유 대기 wrapping은
최근 인증한 수신자만 읽는다. 수락/취소/15분 만료 이력을 보존한다. 철회 즉시 opaque 접근을 막고
새 HVK 회전 전의 새 비밀 저장·재공유를 거부한다. 마지막 구성원 철회는 허용하지 않는다.

회전은 종료 카드까지 모든 미폐기 비밀과 활성 구성원의 ID/revision/version을 고정한다.
현재 키 읽기를 유지하면서 전체 새 wrapping/복구/key check와 각 카드 암호문을 준비한다.
준비 중 비밀 수정·공유·복구·rewrap을 동결하고 완전한 묶음만 원자 전환한다. 중단 버전/nonce는 보존한다.
DELETE는 모든 온라인 버전의 카드 암호문만 폐기하고 원본 참조·nonce·마지막 네 자리·감사를 남긴다.
백업/오프라인 사본의 즉시 회수는 보장하지 않는다.

서버는 평문 PAN/유효기간/CVC/보관함 암호/HVK/복구코드를 받지 않는다. strict schema가 추가 필드,
비정규 base64url/UUID, bool 정수 위장, 과도한 KDF, 다른 키 버전 bundle, 중복 nonce/구성원을 거부한다.
서버의 confirmed flag는 동의 기록일 뿐 key-check 복호화나 생체인증의 증거가 아니다.

## 실행 결과

```bash
uv run --project services/api python scripts/test_database.py services/api/tests/test_vault.py services/api/tests/test_vault_schemas.py services/api/tests/test_vault_database.py services/api/tests/test_cards.py services/api/tests/test_documents.py -q
uv run --project services/api ruff check services/api/src services/api/tests services/api/migrations
pnpm api:generate
pnpm typecheck
python3 scripts/validate_docs.py
```

vault API 22 + strict schema 81 + 독립 DB 우회 7 + 카드 30 + 첨부 quota 통합 39 = **179개 통과**.
실제 PostgreSQL에서 Alembic upgrade head, 모델 drift 없음, downgrade base→upgrade head를 확인했다.
전용 시험 DB를 정지했다. 기존 FastAPI/httpx TestClient deprecation 경고 1개는 남는다.
직전 vault/카드 133개도 통과했으며 deprecated SQLAlchemy partial flush를 full flush로 바꾼 뒤 재검증했다.

타 가계/미등록/철회 권한, 세션·기기 철회 경합, 최근 인증 만료, 실제 합성 WebAuthn grant의 목적/대상/
일회 소비, 멱등 재전송/409, nonce·salt 재사용, 복구 동시 교체, 빈 카드 회전과 두 구성원 bundle,
종료 카드 포함 manifest, 일부 준비 후 실패, abort 후 다음 버전, 모든 버전 비밀 폐기를 포함한다.
합성 opaque 패턴은 서버 저장/권한 시험이며 암호학적 roundtrip으로 표현하지 않는다.

별도 코드 검토에서 HTTP 계약·권한 잠금·관리 인증·공유·복구·stage/finalize/abort·카드 metadata 연결을
확인했다. 독립 SQL 시험은 manifest 카드/구성원 변조, staging 중 현재 비밀 폐기/권한 철회,
부분 준비 상태의 직접 current 전환, 수락 없는 구성원 활성화, 일반 카드 last4 변조를 거부하고
실패 rollback 뒤 정상 전체 회전/공유가 성공함을 대조했다.

공개 합성 Python 벡터는 [v1 포맷 결정](../adr/vault-format-v1.md)과
[공유 fixture](../../packages/test-fixtures/vault-v1.json)에 있다. 실제 키·부부 자료를 사용하지 않는다.
일반 카드 응답의 has_secret bool에 맞춘 Android metadata 9개·납부 연결 12개, 합계21개도 통과했다.
납부 연결의 합성 카드 fixture에 has_secret=false를 반영했다. 처음 SDK 경로 누락으로 실행되지 않은
명령은 ANDROID_HOME=/home/jihoon/Android/Sdk를 설정해 재실행했다. 이전 release Kotlin compile도 통과했다.

```bash
cd apps/client/android
ANDROID_HOME=/home/jihoon/Android/Sdk ./gradlew --no-daemon :app:testDebugUnitTest --tests '*CardMetadataPolicyTest' --tests '*PaymentLinksPolicyTest'
```

## 카드 목록 조회 보강

첫 코드 리뷰의 N+1 지적에 따라 일반 카드 목록은 페이지의 카드 ID를 한 번에 조회해
current key/current envelope/non-purged 조건을 만족하는 ID 집합만 응답에 사용한다.
조회에는 암호문 열을 적재하지 않는다. 단건 조회의 보안 의미는 유지한다.

```bash
uv run --project services/api python scripts/test_database.py services/api/tests/test_vault.py services/api/tests/test_vault_database.py services/api/tests/test_cards.py -q
```

추가 회귀를 포함한 **60개 통과**(vault23 + DB7 + cards30), drift 없음·마이그레이션 왕복 통과.
현재/교체/폐기/비밀 없음/종료 카드와 다른 가계 카드, 배우자 조회를 함께 대조하고
목록의 비밀 존재 판정 SELECT가 한 번이며 암호문 열을 조회하지 않음을 확인했다.
처음 명령의 파일명 오타(test_vault_storage.py)는 테스트를 실행하지 못했고 올바른 파일명으로 재실행했다.

## 남은 검증

Android/PC의 실제 암호화·보호 화면·공유/복구/재개 UI는 별도 변경에서 검증한다.
실제 Galaxy S25/S24 Ultra Android16의 Keystore/CryptoObject·생체 변경·백업·메모리/화면 실패
시험과 CVC 활성화 판단은 전체 기능 뒤에 수행한다. 서버 또는 debug compile 결과로 대체하지 않는다.
운영 서버 키·서명키·실사용 복구코드를 이 개발 검증에서 생성·기록하지 않았다.
