# 보험 계약·사건·비용·청구·수령 화면 검증

SB-019~SB-022, Issues #28~31, R-07/R-13/R-14/R-15/R-18/R-22.
보험 계약·보장·보험료 연결, 독립 사건과 진료 트리, 의료비·환불, 다중 청구,
실제 보험금 수령·사건별 배분·반환·사유 있는 정정을 웹과 Android adapter에 연결했다.
생성 API 계약을 사용하며 이번 client 변경은 서버 API·DB migration·네이티브 정책을 새로 수정하지 않는다.

## 계약·사건·진료

계약·보장·납입 기간은 각각 입력한다. 보장금액 미입력과 명시적 0원을 구분하며 확인한 환급·적립 자산만 연결한다.
보험료 편집은 같은 recurring rule 상세/변경 경로를 사용한다. 연결 해제는 규칙이나 과거 납부를 삭제하지 않는다.
사건은 보험계약과 독립이며 치료/정산 상태를 따로 관리한다. 치료 종료에는 종료일을 기록하고 재개방 때 비운다.
사건 변경 사유와 당시 상태·진단·작성자·서울 시각을 이력으로 조회한다. 진단 설명/코드는 사건 목록에 표시하지 않는다.

진료 트리는 모든 페이지를 읽고 외래·입원·수술·처방·약국·추적 외래·그룹을 표시한다.
기본 펼침 깊이와 최대 인라인 깊이를 제한하고 각 노드 상세에서 하위 트리·상위 경로·상위 이동을 제공한다.
드래그 없이 부모 선택으로 이동하며 자신과 자손을 선택 목록에서 제외한다. 서버가 최종 권한·순환·참조를 검증한다.
진료 노드 생성은 금전 이벤트를 만들지 않는다. 처방은 비용 없이 기록하고 약국 결제는 약국 노드의 의료비로 입력한다.
하위 진료/비용이 있는 노드 삭제는 거부한다.

## 실제 금전 원본과 정정

의료비는 실제 본인 지불금만 원본 한 건으로 등록한다. 총진료비·공단 부담액·영수증 참고번호는 설명용이다.
명세를 분해하면 합계가 원본 지불액과 같아야 한다. 분해 행이나 진료 하위 합계를 새 지출로 더하지 않는다.
파일 업로드·문서 연결은 별도 SB-023 구현과 연결할 영역이며 영수증 참고번호를 파일 업로드로 표현하지 않는다.

청구는 같은 사건의 활성 비용 여러 개를 근거로 선택한다. 여러 계약 청구에 같은 비용을 연결해도 원본은 하나다.
청구액·결정액은 미입력과 0원을 구분하고 실제 수령에 더하지 않는다. 청구 종료와 실제 지급 완료를 동일시하지 않는다.
현재 근거 비용에 연결된 의료비를 정정/무효 처리하려면 청구 근거를 먼저 사유와 함께 정정해야 한다.
청구 이력은 당시 비용 연결을 보존한다.

보험금 입금 한 번을 cash 원본 한 건과 사건별 배분으로 기록한다. 배분 합계와 원본 입금액을 문자열/BigInt로 정확히 대조한다.
청구 없이 직접 수령할 수 있고, 나중에 배분의 계약·청구만 연결해도 새 cash를 만들지 않는다.
입금 원본 목록은 여러 사건이 포함된 총액이라고 표시하고 사건별 수령액은 서버 사건 요약에서 읽는다.
병원·약국 환불과 보험사 반환은 다른 분류이며 원본/원래 배분에 연결한다. 모든 페이지의 활성 환불/반환을 확인해
남은 금액을 안내하고 서버가 최종 한도를 검증한다. 의료비·환불·수령·반환 정정은 이전 원본을 무효로 보존하고 새 원본을 만든다.
정정/무효/후발 배분 연결에는 사유가 필요하며 원본·금전 이력·청구/배분 typed 이력으로 이동할 수 있다.

상단 사건 요약은 실제 의료 지불금·환불·순의료비·수령·반환·순보험금·순현금부담과 급부유형별 수령을 표시한다.
음수 부담을 그대로 표시하며 지급 적정성을 판단하지 않는다. 노드 요약에는 하위 의료비/환불만 집계하고 보험금을 임의 배분하지 않는다.
수입 projection은 실제 보험금 원본을 읽으며 월별 계좌/자산 스냅샷을 자동 변경하지 않는다.

## 충돌·재전송·보호 화면

금전 동작은 생성 계약의 Idempotency-Key와 자원 If-Match를 사용한다. 환불/반환 생성에는 부모 의료비/지급의
**domain version**을 보내며 내부 cash version과 혼동하지 않는다. 변경 참조 응답을 현재 상태로 사용하지 않고 GET으로 다시 읽는다.
응답 유실/취소 후 같은 입력은 같은 키로 재시도한다. 늦은 네이티브 응답은 화면에 적용하지 않는다.
409에서는 입력을 보존하고 현재 원본과 비교한 뒤 수정한 필드만 유지한다. 현재 무효 원본은 다시 정정하지 않는다.
멱등키가 없는 metadata 생성의 네트워크 결과가 불확실하면 목록 확인을 요구하며 자동 재전송하지 않는다.

Android 증권번호는 네이티브 보호 화면에서만 입력·표시한다. metadata 요청은 policy_number를 포함하지 않는다.
웹에서는 별도 일시 입력 DOM과 출력 DOM만 사용하고 React state/브라우저 저장소에 전체 번호를 넣지 않는다.
표시는 최대 30초이며 blur/pagehide/visibility/unmount/버전 갱신 시 지운다. 늦거나 취소된 응답도 다시 표시하지 않는다.
서버 recent-login 만료 시 재인증을 안내한다. 지원되지 않는 증권번호 전용 패스키 scope를 만들지 않는다.
잠금·세션 만료 시 보호된 진료 입력을 포함한 화면을 내리고 웹 HTTP로 우회하지 않는다.

## 실행한 검증

```bash
pnpm --filter @sallimbook/client typecheck
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp pnpm --filter @sallimbook/client exec playwright test tests/insurance-core.spec.ts --config playwright.insurance.config.ts --workers 1
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp pnpm --filter @sallimbook/client exec playwright test tests/insurance-core.spec.ts tests/insurance-events.spec.ts --config playwright.insurance.config.ts --workers 1
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp pnpm --filter @sallimbook/client exec playwright test tests/insurance-events.spec.ts tests/insurance-native-ui.spec.ts --config playwright.insurance.config.ts --workers 1
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp pnpm --filter @sallimbook/client exec playwright test tests/insurance-native-ui.spec.ts tests/insurance-model.spec.ts --config playwright.insurance.config.ts --workers 1
```

계약/사건 24개, 금전 화면 30개, React native 화면 18개, 모델/계산 12개로 신규 84개를 검증했다.
최초 계약/사건 24개는 통과했다. core+events 54개 중 52개 통과 후 disabled option의 matcher 2개를
실제 disabled property와 직접 처방 경로의 저장 거부로 고쳤다. 별도로 같은 version을 쓰던 형제 컴포넌트의 React key에 구분 접두사를 붙였다.
다음 events+native 48개 중 46개 통과 후 화면 이동 직후 native 목록 호출을 기다리지 않던 assertion 2개를 수정했다.
native+모델 30개를 다시 실행해 모두 통과했다. 이후 전체 브라우저 회귀 **452/452**가 통과했다.
마지막으로 계약·보장·진단·진료 메모 한도를 서버 계약의 2,000자로 맞추고 2,001자 거부 경계를 추가했다.
이 작은 수정 후 관련 core+모델 **36/36**, 전체 workspace typecheck와 production build가 통과했다. 미해결 테스트 실패는 없다.

```bash
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp pnpm --filter @sallimbook/client exec playwright test --config playwright.insurance.config.ts --workers 1
pnpm --filter @sallimbook/client exec playwright test --config playwright.insurance.config.ts --workers 1 tests/insurance-core.spec.ts tests/insurance-model.spec.ts
pnpm typecheck
pnpm build
python3 scripts/refresh_docs_manifest.py
python3 scripts/validate_docs.py
git diff --check
```

네이티브 화면 검사는 공개 업무 54개와 보호된 증권번호 화면 2개의 호출을 실제 React 동작으로 확인한다.
웹 요청 0건, 원문 증권번호 인수 없음, 잠금·인증 만료·네트워크 실패, 취소 후 늦은 반영 무시와 같은 키 재시도를 검사한다.
이 검사는 네이티브 JVM 정책·Keystore·생체인증·실기기 검증을 대신하지 않는다.

```bash
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp uv run --project services/api python scripts/test_web_auth.py --insurance
```

실제 HTTPS/API/PostgreSQL 검사는 첫 실행에 통과했다. HTTP mock 없이 계약/보장/보호 번호·동일 보험료 규칙을
연결하고 독립 사건과 8개 진료 노드를 만들었다. 공유 T-12~T-16의 의료비 원본 5건 960,000원,
입원 명세 600,000+260,000원, 같은 영수증의 2개 청구, 실제 입금 600,000+200,000원,
병원 환불 10,000원과 보험사 반환 50,000원으로 순부담 200,000원을 확인했다.
이후 입금 500,000원을 사건별 300,000/200,000원으로 배분하고 음수 부담을 확인했다.
네 금전 원본 종류의 정정/무효와 후발 청구 연결, 두 사건 상태/이력을 거친 뒤에도 확정 자산의 revision/version/금액이
그대로였으며 수입 보험금 projection 1,250,000원, no-store·멱등키·브라우저 저장소 비사용을 대조했다.
임시 DB schema·키·개인 브라우저 산출물을 폐기하고 DB 중지를 확인했다.

18753 포트 하나를 사용하며 Docker 시험 DB 수명주기와 브라우저 검사를 순차 실행한다.
production build는 성공하며 Vite의 500KB 초과 단일 chunk 경고가 남는다. Android 실기기 실패 시나리오·운영 키·서명 배포는 실행하지 않았다.

최신 main의 부모 우선 진료 정렬과 카드 종료일 보완을 통합한 뒤 보험 core/events/model/native UI 및
카드 회귀 104개를 다시 통과했다. 실제 보험 HTTPS 흐름도 CI의 별도 명령으로 유지한다.

PR 리뷰 보완: 청구 상세의 수령 목록에서 추가할 때도 사건·계약·청구를 모두 이어받는다.
해당 경로에서 저장한 원본이 청구 목록에 나타나는 회귀를 포함해 금전 화면 32개를 통과했다.

## 사후 청구·청구별 금액·사건 목록 부담 — 2026-10-20

종료 계약의 사후 청구·직접 배분([ADR 0009](../adr/late-insurance-records.md)), 사건 목록 순현금부담,
청구별 실제 수령·반환·순수령, 비용의 인용 청구, 환불·반환 정정의 사유 보존, 진료 형제 순서를 추가했다.
마이그레이션은 없다. 새 API 필드는 `CaseListItem.net_burden_krw`, `ClaimResponse.received_krw`·`returned_krw`·
`net_received_krw`이고 `GET /insurance/claims`에 `expense_id` 조건을 더했다. 새 오류 코드는 없다.

| 범위 | 시험 |
|---|---|
| 서버 DB | `test_inactive_policy_accepts_late_claim_and_direct_allocation`, `test_case_list_shows_each_case_net_burden_with_constant_queries`, `test_claim_detail_counts_only_its_own_allocations_and_returns`, `test_claims_can_be_listed_by_cited_expense`, `test_reversal_correction_keeps_its_original_reason`, `test_node_pages_follow_tree_order_with_date_and_creation_ties`, `test_same_transaction_siblings_fall_back_to_uuid` |
| 서버 단위 | `test_claim_balance_counts_only_its_allocations_and_their_returns` |
| Android JVM | `caseListCarriesSignedNetBurden`, `claimMoneyMustBeExactDifference`, `claimListAcceptsExpenseFilter` |
| 브라우저 | 종료 계약 선택·안내, 환불 정정 사유 안내, 청구별 금액, 사건 요약 5개 수치 순서, 인용 청구·규칙 409 비교 미제공, 사건 목록 음수 부담, 서버 형제 순서·새 노드 기본 순서 |

브라우저 mock은 청구 이력에서 청구 금액 필드를 제거해 실제 `ClaimRevisionResponse`와 같게 맞췄다.

```bash
pnpm typecheck
uv run --project services/api ruff check services/api/src services/api/tests services/api/migrations
uv run --project services/api pytest services/api/tests -m 'not database' -q
TMPDIR="$HOME/.cache/sallimbook-tmp" pnpm test:database services/api/tests/test_insurance_events.py services/api/tests/test_insurance_core.py services/api/tests/test_income.py services/api/tests/test_exports.py -q
pnpm --filter @sallimbook/client exec playwright test tests/insurance-core.spec.ts tests/insurance-events.spec.ts tests/insurance-model.spec.ts tests/insurance-native-ui.spec.ts tests/insurance-native-bridge.spec.ts tests/insurance-events-native-bridge.spec.ts tests/design-refresh.spec.ts
uv run --project services/api python scripts/test_web_auth.py --insurance
```

결과: typecheck·ruff 통과, DB 미사용 pytest **912 passed**(10 skipped), DB 시험 **162 passed**와 `alembic check` 변경 없음,
브라우저 **158 passed**, JVM `InsurancePolicyTest` 16·`InsuranceEventPolicyTest` 16·`AuthPolicyTest` 12 통과,
`pnpm api:generate` 후 생성 client 변경 없음, 실제 HTTPS 보험 흐름 종료 코드 0.
Android 실기기에서 새 목록·청구 필드 표시는 확인하지 않았다(미실행).

## Issue #141 · 비로그인 가족

`test_household_people.py`는 같은 이름의 별도 가족, 멱등 재시도와 최초 버전 참조,
가계 격리·외부 cursor, 계정 행 보호·두 슬롯 유지, version 충돌, 보관/복구,
가족 환자/피보험자·계약자 경계, 구 클라이언트 변경 거부, 보관 후 기존 사건 재개방,
감사 페이지 SQL 필터와 cursor 모드, 0018 기존 revision 보존·비활성 구성원 backfill,
가족 생성 후 downgrade 거부를 검사한다.
`household-people.spec.ts`는 웹과 native bridge 모의에서 등록 응답 유실 후 같은 키 재시도,
충돌 시 입력 보존, 보관/복구, 환자/피보험자 선택과 계약자 제한을 검사한다.
`HouseholdPeoplePolicyTest`는 이름 있는 명령·필드 제한·version/키·응답 가계/중복/cursor와
계정/가족 구분을 검증한다. 구 APK 감사 제약은 [ADR](../adr/household-people.md)에 기록한다.
검사 목록은 실제 실행 통과를 뜻하지 않는다. 실행 결과는 PR에 기록한다.

## 전체 청구 작업과 기존 수령 연결 (#153, 2026-10-25)

R-13/R-14/R-15/R-18/R-19. `/insurance/claims`는 모든 페이지의 청구를 읽고 추가 서류를
우선 표시한다. 접수일·상태·사건·계약·환자·실제 수령 여부·정렬 조건은 URL에 남는다.
청구 접수일이 없는 항목은 날짜 조건에서 제외하며 수령 기록이 있어도 지급 완료로
해석하지 않는다. 요청·결정 금액과 실제 수령·반환·순수령을 각각 표시한다.

`ClaimListItem`에 `received_krw`·`returned_krw`·`net_received_krw`를 추가했다. 상세와
같은 서버 계산으로 활성 입금의 해당 청구 배분과 활성 반환만 집계한다. DB migration은
없다. 생성 OpenAPI/TS와 Android 응답 허용 필드·차액 검증을 함께 갱신한다. 이전 Android
앱의 응답 projection은 추가 필드를 제외하며, 새 목록 기능은 업데이트한 앱에서 사용한다.

청구 상세 → 이미 받은 보험금 연결에서 같은 사건의 활성 원본과 해당 사건 배분만 찾는다.
원본 총액과 선택 배분액을 구분하고 기존 계약·다른 청구의 연결도 확인한다. 선택 후 명시적
확인과 정정 사유를 입력해 기존 `linkPayoutAllocation`을 호출한다. 배분 ID·버전과 같은
요청의 멱등키를 유지하며 409에서는 최신 연결을 비교한 뒤 다시 확인한다. 입금 원본·다른
사건 배분·실제 입금일·금액은 바꾸지 않는다.

청구 근거 선택은 의료기관·실제 지불일·영수증 참고와 선택 지불금 합계를 표시한다. 합계는
환불·보장 조건을 계산한 청구액이 아니며 청구액에 자동 복사하지 않는다. 사건·계약 선택에
가족과 사건 시작일 문맥을 추가한다. 사건 목록만으로 진료 원문을 노출하지 않는다.

검증 시나리오는 `claim-workbench.spec.ts`, `insurance-https.spec.ts`,
`test_claim_detail_counts_only_its_own_allocations_and_returns`,
`claimListKeepsExactMoneyAndRejectsMissingOrMismatchedAmounts`에 연결한다. 기존 입금을
다른 사건과 나눈 상태에서 연결·충돌·응답 유실 재전송을 검사하고, 추가 서류와 가족·날짜
조건을 여러 페이지에 걸쳐 확인한다. 공통 URL 필터는 이전 탐색의 늦은 완료가 새 조건을
덮지 않도록 마지막 요청을 추적하며, 뒤로/앞으로 탐색은 실제 URL 조건을 복원한다.
실행 결과와 CI/Android 계측 결과는 PR에 기록한다.


## 진료 연속 입력·계약별 비용 연결·오등록 삭제 (#155, 2026-10-25)

R-13/R-14/R-15/R-18/R-19. 진료 저장 후 같은 부모의 다음 진료를 입력하고,
선택 진료의 같은 단계 기록으로 이동한다. 의료기관·종류는 계승하되 새 이름·날짜·메모는
확인한다. 비용 입력은 진료의 기관을 기본값으로 쓰며 직접 수정한 기관을 덮지 않는다.
진료일 제안은 명시적으로 선택해야 실제 지불일에 들어가며 저장 전에는 지출을 만들지 않는다.

의료비 목록의 계약별 청구 연결 필터는 서버에서 페이지를 나누기 전에 적용한다.
초안·철회 포함 현재 근거 연결 여부와 실제 지급 완료를 구분한다. 계약 목록에는
피보험자, 납입 종료, 계약 만기와 보장 종료가 별도로 표시된다.

계약·사건 삭제는 확인 후 가계·version·참조를 검사한다. 수정된 기록과
비활성 보장/보험료/문서 연결, 철회 청구, 무효 지급도 보존한다.
`0020_insurance_misregistration`과 준비 상태 점검의 요구 revision을 함께 변경했다.
[삭제 설계](../adr/insurance-misregistration.md)의 생성 스냅샷 예외를 제외하고
사건 이력 UPDATE/DELETE 금지와 금전 원본 보존은 유지한다.

검증 위치:

- `insurance-core.spec.ts`: 연속 형제 진료·순서·기관 계승, 기간 구분, 삭제 확인과 참조 거부.
- `insurance-events.spec.ts`: 기관 수동 변경 보존, 날짜 제안의 명시적 적용, 계약별 비용 필터와 URL 복원.
- `insurance-native-ui.spec.ts`, `insurance-native-bridge.spec.ts`: 이름 있는 삭제 명령·강한 버전, 웹 HTTP 우회 없음.
- `test_insurance_core.py`, `test_insurance_storage.py`: 가계/버전/참조/감사, 최초 스냅샷의 제한 삭제와 수정 기록 직접 SQL 삭제 차단.
- `test_insurance_events.py`: 복수 계약·철회 청구·무효 지급 보존, 필터가 의료비 원본 합계를 늘리지 않음.
- `InsurancePolicyTest`, `InsuranceEventPolicyTest`: 삭제 204 응답·허용 경로·강한 버전·계약 UUID/boolean query wire.
- `insurance-https.spec.ts`: 실제 API/DB에서 오등록 삭제, 연속 진료, 기관 계승, 계약별 연결 필터와 기존 합계/청구/수령/정정 흐름.

실행 결과와 원격 CI·Android 계측 결과는 PR에 기록한다. 브라우저 native 모의와
Kotlin 정책 검증을 실기기 사용 시험으로 표현하지 않는다.
