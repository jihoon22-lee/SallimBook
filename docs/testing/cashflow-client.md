# 수입·고정 납부·카드·종료 확인 화면 검증

SB-014~018 / Issues #23~27 / R-07·R-08·R-09·R-18·R-19·R-22.
생활비 진입, 수입 목록/상세/등록/정정/반환/무효/정밀도 전환, 카드 일반정보,
반복 규칙과 적용기간, 예정 회차와 실제 납부, 카드·계좌·연결 자산의 종료 확인을 구현했다.
생성 API 타입과 기존 서버 계산을 사용하며 이번 client 변경은 DB migration을 추가하지 않는다.

## 금액과 이력

수입 요약은 서버의 선택 월 전체 집계이며 목록 필터로 전체 합계를 바꾸지 않는다.
구성원별 근로·부수입과 보험금 유입/반환은 분리한다. 보험금 원본은 읽기 전용이고 보험 영역으로 이동한다.
월합계/일별 혼용은 중복 후보 확인을 거쳐 명시적으로 저장한다. 범위·금액을 바꾸면 확인을 해제한다.
정밀도 전환은 같은 월·구성원·종류의 모든 활성 원본/버전을 조회하고 원본과 대체 합계를 정확히 대조한다.
활성 반환이 있는 원본은 정정·무효·전환을 제한한다. 변경 영수증의 과거 권한을 재사용하지 않고 현재 상세를 다시 읽는다.

고정 납부는 월/연/N일 규칙, 적용기간별 변경, 미래 종료일 단축, 명시적 기간 생성,
예정일 변경·건너뛰기/복원·수동 완료/재개, 일부·초과 납부와 납부 무효를 제공한다.
목록과 달력은 예정일 기준이며 월 요약의 실제 납부는 납부일 기준이다. 예정과 실제를 더하지 않는다.
달력은 월의 모든 페이지를 읽은 후 표시하며 일부 페이지를 전체 달력으로 표시하지 않는다.
미정 null과 명시적 0원은 다르다. 원금+이자=납부액을 정수 원으로 검사하고 이자만 소비로,
연금 등 자산 이동은 소비 0으로 표시한다. 외화는 참고값이며 자동 환산하지 않는다.
모든 수입·납부·무효는 자산 스냅샷을 자동 가감하지 않는다.

금액은 생성 계약의 십진 문자열과 BigInt로 처리한다. 응답 유실/취소 후 재시도는 같은 멱등키를 유지한다.
생성 성공이 확인된 후의 새 명시 요청은 새 키를 사용한다. 납부 무효의 If-Match는 회차가 아니라 원본 cash version이다.
409에서는 입력을 보존하고 현재 내용을 비교한다. 수정하지 않은 필드는 최신 값으로 채우고 사용자가 비교한 뒤 저장한다.

## 카드와 결제수단 종료

카드 일반정보는 소유자·카드사·상품/별칭·신용/체크·마지막 네 자리·결제일·계좌·사용기간·메모만 입력한다.
PAN·유효기간·CVC·암호문 입력이나 일반 state/cache 경로는 추가하지 않는다.
참조 없는 오등록 삭제와 과거 이력을 보존하는 사용 종료를 구분한다. 종료된 계좌는 경고하며 자동 대체하지 않는다.

카드·계좌 종료 및 연결 금융 자산의 종료 수정/보관 처리 전 선택 종료일 기준의 연결을 조회한다.
규칙·회차·카드 cursor를 각각 끝까지 읽고 자원/버전/날짜/digest/총수를 대조한다.
등록된 정기 결제의 카드 승인 계획과 계좌 직접 납부 계획을 구분한다. 전체 카드 명세나 계좌 출금 합계로 표현하지 않는다.
명시 확인 후 현재 digest와 closure_ack를 보낸다. 날짜 변경·409·조회 갱신 시 확인을 해제하고 다시 검토한다.
페이지 사이 연결 변경은 결합하지 않으며 입력 종료일은 유지한다. 종료는 연결을 자동 변경하지 않는다.

## Android 경계

수입 10개, 카드 6개, 고정 납부 18개, 종료 연결 조회 2개를 생성 타입의 네이티브 adapter에 연결했다.
공개 업무 메타데이터만 JS에 반환한다. 잠금·세션 만료·네트워크 오류에서 웹 HTTP로 우회하지 않는다.
늦게 도착한 취소 응답은 화면에 적용하지 않으며 서버 반영 여부가 불확실한 상태는 재시도 흐름으로 유지한다.
React bridge 모의시험은 Android Keystore·생체인증·실기기 검증을 대신하지 않는다.

## 실행 검증

```bash
pnpm typecheck
pnpm build
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp pnpm --filter @sallimbook/client exec playwright test --config playwright.cashflow.config.ts --workers 1
```

전용 18751 포트로 전체 334개 중 332개가 통과했고 신규 82개는 모두 통과했다.
기존 계좌 종료 테스트 2개는 mock의 일반 계좌 GET가 payment-links 경로를 가로채는 문제였다.
정확한 경로를 먼저 처리하도록 fixture를 수정했다. 이후 추가한 달력과 해당 계좌 테스트의 재검증 결과는 아래에 기록한다.
타입 검사와 production build가 통과했다. Vite는 단일 JS chunk가 500KB를 넘는 경고를 표시하며 빌드는 성공한다.

실제 HTTPS 검증 명령은 다음과 같다. 임시 DB schema와 개인 임시 디렉터리, 합성 데이터만 사용한다.
기존 서비스·인증서 신뢰 저장소·운영 데이터는 바꾸지 않으며 전역 DB 시험 잠금을 사용한다.
브라우저 mock 회귀와 Docker 생성/중지는 순서대로 실행한다.

```bash
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp uv run --project services/api python scripts/test_web_auth.py --cashflow
```

실제 HTTPS 검사는 첫 실행에서 통과했다. 모의 HTTP 경로 없이 수입 300만 원을 100만+200만 원으로 전환하고,
정정·10만 원 반환·반환 무효 후 현재 작업 가능 상태를 확인했다. 1월 31일 anchor의 1/31·2/28·3/31 회차,
33,000원 예정에 10,000+25,000원 분할 납부, 미래 적용금액 변경과 종료일 단축을 확인했다.
대출 100만 원 중 원금 70만/이자 30만 원, 자산 이동 납부/무효 후 서버 월 집계는 실제 1,035,000원,
소비 335,000원·원금 700,000원·자산 이동 0원이다. 카드·계좌 종료 확인을 마친 후에도
확정 자산의 version과 금액은 그대로이며 no-store·멱등키·브라우저 저장소 비사용을 확인했다.
검사 중 desktop에서 Android 크기로 전환했으며 실제 Android 기기 검사로 간주하지 않는다.
일회용 DB schema/개인 임시 산출물을 폐기하고 DB 중지를 확인했다.

fixture 수정과 달력 추가 후 계좌·고정 납부 40개를 재실행해 모두 통과했다.
전체 실행에서 통과한 신규 82개에 달력 2개를 더해 신규 UI 검사는 총 84개다.
미해결 테스트 실패는 없으며 336개 전체를 한 번에 재실행했다고 주장하지 않는다.

```bash
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp pnpm --filter @sallimbook/client exec playwright test tests/accounts.spec.ts tests/fixed.spec.ts --config playwright.cashflow.config.ts --workers 1
python3 scripts/validate_docs.py
uv run --project services/api ruff check scripts/test_web_auth.py
git diff --check
```

최종 통합 `abb90a1`에서 최신 앱 잠금·자산 연결·비교 날짜 보완을 함께 검증했다.
전체 UI **342개 통과**, Android JVM **159개 통과**(실패·오류·skip 0), 디버그 APK 조립과
release Kotlin 컴파일 성공을 확인했다. 실제 `--cashflow` HTTPS 흐름도 다시 통과했으며
DB 정지와 시험 잠금 반환을 확인했다. CI에 이 실제 HTTPS 검사를 추가했다.
카드·계좌·연결 자산의 종료 화면과 Android의 확인/digest 경로를 서버 강제 검사와 함께 배포한다.

## SB-017 카드 종료일 검증 보완 (PR #68)

카드 수정과 상세 사용 종료에서 서울 기준 오늘 이후의 종료일을 입력하면 즉시 안내하고 저장을 막는다.
시작일과 같은 종료일은 허용하며, 시작일 이전 날짜는 별도로 안내한다. 두 날짜 입력의 `max`와
공통 payload 검증을 함께 적용하고, 잘못된 종료일로는 연결 납부 계획을 조회하지 않는다.
서버의 `INVALID_CARD_DATES` 안내도 시작일 포함 하한과 서울 오늘 상한을 모두 설명한다.
API 계약·DB 스키마·네이티브 경로·민감정보 처리는 변경하지 않았다.

`pnpm typecheck`, `pnpm build`와 카드/현금흐름 모델 회귀 **28개**가 통과했다(기존 20개, 신규 8개).
빌드에는 기존 단일 JS chunk 500KB 경고가 남아 있다.
수정·종료 양쪽의 미래일 차단, 시작일 이전 차단, 오늘/시작일 포함 허용, 직접 form submit 차단,
서울 자정 전후, 종료일 미입력과 잘못된 달력 날짜, 서버 오류의 한국어 안내를 확인했다.
desktop과 Android 크기 브라우저를 사용했으며 실기기 검증은 아니다.
동시 작업의 포트 충돌을 피하려고 기본 Playwright 설정의 baseURL/webServer만 18754로 바꾼
임시 `playwright.card-date.local.config.ts`를 사용했고 실행 후 제거했다.

```bash
TMPDIR=/home/jihoon/.cache/sallimbook pnpm --filter @sallimbook/client exec playwright test cards.spec.ts cashflow-model.spec.ts --config playwright.card-date.local.config.ts --workers=2
```

## SB-016 회차 생성 중단과 재시도 인수 보완 (Issue #25)

v1의 회차 생성 실행 경계는 화면의 **선택 기간 회차 생성**과
`POST /api/v1/obligations/generate`다. 사용자가 기간과 규칙을 명시하며 별도 스케줄러
daemon은 없다. 따라서 ‘실패 후 보충’은 이 생성 요청의 transaction 실패 후 같은 요청을
다시 실행하거나 누락 기간을 명시해 보충하는 동작으로 검증한다. daemon 재부팅이나
실제 네트워크 단절을 시험했다고 해석하지 않는다. 제품 API·migration·네이티브 구현은 변경하지 않았다.

[서버 회귀](../../services/api/tests/test_recurring.py)에서 기존 실패 주입 시험 하나를
강화하고 커밋 후 응답 실패 시험 하나를 추가했다.

- `test_generation_failure_rolls_back_and_same_key_can_retry`: 두 회차와 두 revision이 실제
  PostgreSQL에 flush됐고 멱등 예약이 pending인 것을 같은 transaction에서 조회한 뒤 예외를
  발생시킨다. HTTP 500 후 별도 session에서 회차·revision·생성 batch/item·멱등 예약·회차 감사가
  모두 0건인 것을 확인한다. 같은 키로 정상 재실행하면 1/31·2/28·3/31 회차가 각각 한 건이고,
  같은 키를 다시 보내도 동일 응답과 배치 하나·revision 세 개를 유지한다.
- `test_generation_committed_before_response_failure_replays_same_result`: 실제 서비스의
  commit 직후, 성공 응답을 반환하기 전에 예외를 발생시켜 HTTP 500을 만든다. 별도 session에서
  완료된 멱등 결과와 회차 세 건의 저장을 확인하고, 같은 키의 두 차례 재전송이 원래 batch와
  회차 ID/version을 반환하며 revision·batch/item·감사를 추가하지 않는지 검사한다.

기존 `test_t10_repeat_generation_and_failure_catchup`은 2월 생성 뒤 2~3월 범위를 반복
재요청하여 누락 월 보충을 검사한다. 위 두 실패 경계와 함께 T-10/T-22의 반복 안전성을 확인한다.

2026-10-18 실행 결과: `test_recurring.py` 전체 **78개 통과**, 66.06초, 실패·건너뜀 0건.
이는 이번에 실행한 실제 PostgreSQL 회귀이며 위의 과거 UI/HTTPS 수치에 더한 전체 시험 수가 아니다.
Alembic upgrade·drift 0·downgrade/upgrade, Ruff 검사·포맷 검사와 `git diff --check`도 통과했다.
기존 Starlette TestClient deprecation warning 1개가 남는다. 합성 데이터와 전용 18745 시험 DB의
일회용 schema만 사용했고 시험 후 schema 제거·db-test 중지·공유 시험 잠금 반환을 확인했다.
실제 HTTPS·Android/웹 화면·실기기 시험은 이번 서버 시험에서 다시 실행하지 않았다.

```bash
uv run --project services/api --frozen python scripts/test_database.py services/api/tests/test_recurring.py -q --tb=short
uv run --project services/api --frozen ruff check services/api/tests/test_recurring.py
uv run --project services/api --frozen ruff format --check services/api/tests/test_recurring.py
git diff --check
```
