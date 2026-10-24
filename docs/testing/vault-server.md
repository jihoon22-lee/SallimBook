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

## 회전 metadata 조회 보강

후속 코드 리뷰에서 회전 상태 조회도 source/staged envelope를 카드 수만큼 조회하는 문제를
확인했다. source의 ID/revision/last4와 staged card ID를 각각 한 번에 조회하며 ciphertext는
적재하지 않는다. 현재/중단된 회전의 prepared 의미와 가계·권한 검사는 유지한다.

위 vault/card/DB 명령을 다시 실행해 **61개 통과**(vault24 + DB7 + cards30), drift 없음과
마이그레이션 왕복을 확인했다. 새 회귀는 6개 카드(종료 카드 포함), 일부만 준비된 상태,
다른 가계의 동시 회전이 있을 때 metadata가 같고 envelope SELECT가 정확히 2개임을 검사한다.
자동 리뷰 제한을 지키기 위해 원래 PR source에 추가 push하지 않고 최종 통합 branch에서 보강했다.

## 남은 검증

Android/PC의 실제 암호화·보호 화면·공유/복구/재개 UI는 별도 변경에서 검증한다.
실제 Galaxy S25/S24 Ultra Android16의 Keystore/CryptoObject·생체 변경·백업·메모리/화면 실패
시험과 CVC 활성화 판단은 전체 기능 뒤에 수행한다. 서버 또는 debug compile 결과로 대체하지 않는다.
운영 서버 키·서명키·실사용 복구코드를 이 개발 검증에서 생성·기록하지 않았다.


## Issue #118 · 공유 이력의 최신 생성순과 호환성

2026-10-24 변경은 공유 목록의 정렬을 `(created_at DESC, id DESC)` keyset으로 통일한다.
DB migration·암호 포맷·mutation은 바꾸지 않는다. cursor UUID와 응답 필드를 유지하며
현재 가계와 발신자/수신자 조건을 cursor 원본 조회에도 적용한다. 모르는 cursor는 404다.
OpenAPI 설명과 생성 client를 같은 변경에서 갱신한다.

구현 후 별도 소스 검토에서 인증/세션/기기·가계 잠금이 기존 `_lock`/`_read` 경로에 남는지,
다른 가계 또는 참여자가 아닌 공유를 cursor로 사용할 수 없는지, 목록이 wrapping/암호문을
반환하지 않는지, 정렬 기준이 비밀이나 변경 가능한 상태에 의존하지 않는지 대조했다.
이 검토는 동일 작성자의 별도 검토 단계이며 독립 외부 보안 인증을 의미하지 않는다.

Issue의 APK 선배포 전제를 실제 0.1.9 앱 소스(`53a2c72`)와 대조했다.
`NativeVaultWire`, `NativeVaultUiPolicy`, `NativeVaultConnection`은 해당 소스와 같으며
공유 목록에 UUID 내림차순을 요구하지 않는다. ID 중복·가계 혼합·페이지 크기·마지막 ID와
cursor 일치를 검증하므로 생성순 정렬을 이미 받을 수 있다. 새 JVM 회귀는 ID가 증가했다
감소하는 두 페이지가 허용되며 잘못된 next_cursor는 거부됨을 확인한다. 정책을 완화하거나
호환 옵션을 추가하지 않는다. 따라서 이번 정렬 변경에 구 APK 업데이트를 선행 조건으로
둘 필요는 없다. 이는 실제 기기 실행 결과와는 구분되는 소스/정책 호환성 근거다.

합성 API 회귀는 INSERT 전에 UUID 순서와 다른 생성 시각 및 동률을 정하고 실제 공유
생성·취소 5건을 구성하여 발신자·수신자의 3페이지 순서, 누락/중복 없음, 빈 외부 가계, 다른 가계/없는 cursor
404, 페이지 크기 검증과 응답 metadata 경계를 확인한다. 실행 명령·결과는 PR에 기록한다. 서버 관련 27개와 새 정렬 회귀 1개, Android
보관함 JVM 81개(실패·오류·건너뜀 0개)가 통과했다. 최초 정렬 fixture에서 이미 생성된
공유 시각을 바꾸려던 시도는 기존 DB 불변 보호에 거부되어, INSERT 시 합성 값을 정하도록
수정했다. 보호 트리거는 완화하지 않았다. 최초 JVM 실행은 Capacitor 생성 파일 누락으로
테스트 전에 중단되었고 `cap sync android` 후 재실행했다.
실제 Galaxy의 공유 중 잠금·백그라운드·인증 취소 시험은 미실행이며, 사용자가 직접 수행할
후속 인수 항목으로 남긴다. CVC 활성화 상태나 실기기 보안 인수 완료 여부는 바꾸지 않는다.
