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

## 고정 납부·수입·금전 연결 보완 (M1·M2·M3·M6·L1~L3) — 2026-10-20

검토의 M1(수동 예외 고정 해제), M2(시작 전 예정 버전 철회), M3-a/M3-b(기록 날짜·정정 원본 기준의
결제수단 판정), M6(수입 정정 자기 중복 제외), L1(납부 완료 회차 추가 납부 확인), L2(정밀도 전환의
계좌·메모 보존), L3(회차 이력 action 계약)를 보완했다. 마이그레이션은 `0015_rule_revocation`이고 API 형태
변경은 `ObligationHistoryItem.action`의 `ObligationHistoryAction` enum 하나다. 새 오류 코드는 없다.

추가한 시험:

- DB: `test_manual_override_tracks_only_live_exceptions`, `test_reopen_and_void_clear_manual_override`,
  `test_revocation_is_one_way_and_frees_the_period`, `test_manual_override_must_match_live_exception`,
  `test_upgrade_normalizes_stale_manual_override_rows`, `test_downgrade_refuses_revoked_rule_versions`,
  `test_end_before_pending_version_revokes_it`, `test_change_at_pending_start_replaces_it_once`,
  `test_revocation_refused_when_pending_occurrence_was_handled`(납부·건너뛰기),
  `test_started_or_first_version_cannot_be_revoked`, `test_closed_account_accepts_records_dated_through_its_end`,
  `test_settlement_accepts_closed_account_through_its_end_date`,
  `test_correction_keeps_a_link_that_closed_after_the_original`(의료비·환불·보험금·반환)
- 모듈: `test_revocation_column_reuses_known_audit_field`, `test_history_action_contract_matches_database_check`
- Playwright: 예정 변경 앞 종료·같은 시작일 교체·철회 거부 안내, 종료일 이하 카드·계좌 선택(고정 납부·수입·의료비),
  수입 정정 자기 중복 제외와 다른 월합계 검토 유지, 납부 완료 회차 추가 납부 확인, 정밀도 전환의 계좌·메모
  이어받기와 다른 계좌 안내, 회차 이력의 `regenerate` 라벨
- Playwright(후속): 다른 구성원이 먼저 납부를 마쳐 409가 난 뒤 현재 회차로 계속할 때 추가 납부 확인을
  다시 요구하고, 아직 미납인 회차의 충돌은 확인 없이 계속하는지 확인한다.

실행 결과(합성 데이터, 전용 18745 시험 DB와 HTTPS 시험 환경):

- `pnpm test:database` recurring·income·insurance_events·payment_links·cards·insurance_core·exports·database
  **322개 통과**, Alembic drift 없음과 downgrade/upgrade 왕복 통과
- `pytest -m 'not database'` 911개 통과, Ruff·Prettier·typecheck 통과, `pnpm api:generate` 후 생성 client 변경 없음
- Playwright 고정 납부·수입·보험 사건·카드·결제수단 종료·업무 흐름·모델·native UI/bridge **214개 통과**
- Android JVM `FixedCostPolicyTest` 15, `CashflowPolicyTest` 9, `NativeAuditWireTest` 10 통과(정책 변경 없음 확인)
- 실제 HTTPS `test_web_auth.py --cashflow`, `--insurance` 통과

배포 메모: 수정 전 코드로 이미 종료·변경된 규칙의 미래 회차 중 `manual_override`가 남아 대체되지 않은 행은
마이그레이션이 플래그를 정규화한 뒤에도 그대로다. 배포 직후 "고정 납부 > 예정 회차 생성"을 오늘이 포함된 월부터
이미 생성한 마지막 월까지(요청당 최대 366일) 다시 실행하면 미납·예외 없는 미래 회차가 현재 규칙대로 갱신된다.
운영 DB의 정규화 대상 건수와 Android 실기기 확인은 미실행이다.

```bash
TMPDIR="$HOME/.cache/sallimbook-tmp" pnpm test:database services/api/tests/test_recurring.py services/api/tests/test_income.py services/api/tests/test_insurance_events.py services/api/tests/test_payment_links.py services/api/tests/test_cards.py services/api/tests/test_insurance_core.py services/api/tests/test_exports.py services/api/tests/test_database.py -q
pnpm --filter @sallimbook/client exec playwright test tests/fixed.spec.ts tests/income.spec.ts tests/insurance-events.spec.ts tests/cards.spec.ts tests/payment-closure.spec.ts tests/task-journeys.spec.ts tests/cashflow-model.spec.ts tests/cashflow-native-ui.spec.ts tests/cashflow-native-bridge.spec.ts tests/insurance-events-native-bridge.spec.ts
uv run --project services/api python scripts/test_web_auth.py --cashflow
uv run --project services/api python scripts/test_web_auth.py --insurance
```

## Issue #144 · 변동액 납부 확인과 재조회

예정액 미정(null) 회차도 유효한 실제 납부가 있으면 `paid`(납부 확인)다.
예정액과 차액은 null 그대로이며 추가 납부는 기존 추가 확인을 거친다.
마지막 유효 납부를 무효로 하면 다시 `unpaid`다. 0원 실제 납부 이벤트를 만들지 않으며
0원 예정의 수동 완료, 건너뛰기·대체 회차의 우선순위는 유지한다.

화면의 unpaid는 예정일이 미래면 '납부 예정', 오늘이면 '오늘 예정 · 납부 확인 전',
과거면 '예정일 지남 · 확인 필요'다. 미기록만으로 실제 연체라고 단정하지 않는다.
월 요약·목록·달력·회차 상세를 재조회하는 동안 기존 내용과 갱신 상태를 함께 표시한다.
월이 달라지면 요약·달력 조회 상태를 새로 시작하여 이전 월의 값을 새 월 제목 아래
표시하지 않는다. 재조회 중 새 상세 작업은 잠시 비활성화하며 열려 있는 입력을 지우지 않는다.

`test_variable_unknown_zero_skip_complete_reopen`은 미정액의 분할 납부·수동 완료/재개·
각 납부 무효 후 상태와 null 차액을 검증한다. `fixed-status.spec.ts`는 웹/native 모의의
예정일별 문구·추가 납부 확인과 재조회 중 DOM 유지·월 구분을 검사한다.
`FixedCostPolicyTest`는 미정 예정액·null 차액의 paid와 무효 후 unpaid 응답을 받으며,
예정액 미정인데 차액만 0인 잘못된 응답은 거부한다. 실행 결과는 PR에 기록한다.

## Issue #146 · 예정 준비와 반복 납부 입력

규칙 등록·적용기간 저장 뒤 기존 `generate` 명령으로 이번 달 1일과 적용 시작일 중
늦은 날부터 그 달을 포함한 12개월 말일까지 예정 회차를 준비한다. 조회만으로는
생성하지 않는다. 규칙 저장 응답을 받은 뒤 준비가 실패하면 입력을 잠그고 저장된 규칙을
안내하며, 준비 요청만 같은 키·기간으로 재전송한다. 생성 건수가 0이어도 확인한 기간과
결과를 표시한다. 기존 규칙·다른 월은 ‘이달 예정 준비’ 또는 기간 지정 생성으로 보충한다.
이 흐름은 기존 API 두 명령의 조합이며 실제 납부나 계좌·자산 스냅샷을 만들지 않는다.

월별 화면에서 납부 목록을 규칙 관리·상세 합계보다 먼저 보여 준다. 개별 납부는
유효 납부가 아직 없는 양수 예정액을 제안하지만 실제 납부일은 비워 둔다. 오늘·과거
예정일은 사용자가 직접 선택할 수 있다. 부분·추가 납부 금액은 비워 두고, 대출 원금·이자도
직접 확인한다. ‘저장하고 다음 미기록 회차’는 성공한 납부를 닫고 같은 예정 월의 다음
미기록 회차를 읽는다. 다음 조회 실패 시 읽기만 다시 수행하고 납부를 재전송하지 않는다.

‘여러 회차 납부’는 처음에 아무 항목도 선택하지 않는다. 활성·미납·실제액 0·양수 고정액인
소비/자산 이동만 허용하며, 변동액·대출·부분/완료 납부·수동 예외를 제외한다. 사용자에게
실제 납부일과 예정액대로 납부했다는 확인을 받는다. 각 회차의 금액·날짜·수단·버전과
서로 다른 멱등키를 고정하여 기존 납부 API에 전송한다. 성공 행은 재전송하지 않고,
통신/서버 오류와 미요청 행만 같은 키로 다시 확인한다. 409와 입력 거절은 개별 상세에서
검토하도록 남긴다. 저장된 행과 아직 확인할 행을 함께 표시하고 이동 시 미확인 작업을 안내한다.

`fixed-payment-actions.spec.ts`는 웹/native 모의의 준비 단계 재시도, 기본 미선택,
선택 합계의 소비/자산 이동 구분, 일부 응답 유실·충돌, 날짜 명시, 저장 후 다음 조회 실패를
검사한다. 320/390/1280px 어두운 화면의 첫 납부 동작·가로 넘침·입력 패널 포커스도 검사한다.
`cashflow-model.spec.ts`는 윤년·미래 시작일·지원 마지막 연도의 준비 기간을 검사한다.
실제 HTTPS 시나리오는 규칙 저장 직후 현재 월 회차, 명시적 다른 월 준비, 선택 납부의
소비/자산 이동 합계와 월 스냅샷 버전 보존을 검증한다. 실행 결과는 PR에 기록한다.

## Issue #149 · 수입 초안 불러오기와 보험금 전액 배분

새 수입의 구성원은 현재 로그인 구성원을 기본값으로 사용하며 직접 바꿀 수 있다. 지난달의 활성 수동 수입을
모든 페이지에서 읽고, 선택한 한 기록의 종류·구성원·금액·계좌·메모를 이번 달 새 초안으로 가져온다.
월합계/일별 정밀도는 유지하되 실제 입금일은 비워 둔다. 기존 작성 내용이 바뀐다는 안내와 명시 선택을 거친다.
보험금·반환·무효 수입은 대상에서 제외한다. 원본을 변경하거나 불러오기 자체로 수입을 만들지 않는다.

불러온 수입은 저장 전 같은 월·구성원·종류의 활성 기록도 읽어 같은 정밀도인 중복 후보까지 검토한다.
기존 월합계/일별 중복 검토·명시 확인·멱등 저장을 유지한다. 저장 응답 유실 뒤 원래 요청을 다시 확인하며
이전 달 원본을 이번 달 기록으로 바꾸지 않는다. 현재 월과 전월의 합계는 독립이다.
수입 요약의 주 지표는 근로·부수입 순액이고 보험금 순유입과 전체 등록 유입을 구분한다.

보험금 수령의 배분이 한 행일 때, 사건과 양수 실제 수령액을 입력하면 ‘받은 전액을 이 사건에 배분’으로
배분 초안만 채울 수 있다. 여러 배분이 있으면 이 동작을 제공하지 않는다. 최종 입금 한 건/배분 합계 확인은
별도이며 기존 서버의 원 단위 계산·멱등성·권한 검증을 그대로 사용한다. 자동 실제 지급 생성은 없다.

검증은 `income-shortcuts.spec.ts`의 웹/native 초안·중복·날짜·응답 유실·전액 배분과 기존 수입/보험금 회귀,
`insurance-native-ui.spec.ts`의 전용 명령, 실제 HTTPS `--cashflow`·`--insurance`에서 수행한다.
API 스키마·마이그레이션·비밀정보 경계 변경은 없다. 실행 결과와 실기기 미실행 범위는 연결 PR에 기록한다.

이 변경의 로컬 검증: 수입·금전·작업 동선 168개와 Android 보험 UI/bridge 30개, JVM 정책 27개 통과.
실제 HTTPS `--cashflow`에서 초안 단계의 0건과 저장 후 이번 달 1건·전월 합계 보존을 확인했고,
`--insurance`의 단일 사건 전액 배분과 여러 사건 배분·반환·정정 흐름도 통과했다.
`test_income.py`·`test_insurance_events.py`·`test_database.py`의 PostgreSQL 시험 **136개**와 모델/migration 일치·왕복 검사,
TypeScript·lint·서식·빌드·문서 검증 및 문서 도구 258개도 통과했다. 기존 청크 크기와 Starlette/httpx 예고 경고는 남아 있다.
