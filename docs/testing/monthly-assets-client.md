# 월간 자산 입력 클라이언트 검증

SB-012 / Issue #21 / R-05·R-19의 웹 입력·확정·정정 화면이다. 서버가 가진 월 기록과 생성 API client를 사용한다.

## 동작

`/assets/months/:month`에서 현재 월 작성본을 읽고, 없으면 전월 마지막 확정 금액을 복사하거나 빈 작성본을 만든다.
복사값은 미확인이고 기준일은 비어 있다. 미입력은 null이며 0원과 다르다. 변동 없음도 실제 확인한 새 기준일을 요구한다.
기준일은 선택 월 안의 실제 날짜이고 미래 날짜를 입력할 수 없다. 가계 지분 적용 참고 계산은 BigInt의 정수 연산으로
HALF_UP 처리하며 최종 금액과 전체 합계는 서버 응답을 표시한다.

월 기록의 이름·소유 관계·지분·금액 입력 기준·합계 포함 여부·기간은 당시 snapshot이다. 현재 자산 기본정보와
자동 결합하지 않는다. 범위 반영은 별도 검토와 명시 확인 후 수행하며 변경된 행은 다시 확인해야 한다.
whole/owned 기준이 달라진 금액은 추정 변환하지 않고 미입력으로 돌아간다.

미입력·미확인 포함 항목은 확정을 막는다. 확정 전 월말이 아닌 기준일과 전월 대비 포함 대상·지분 변화를 보여준다.
정정은 사유를 요구하고 새 기록을 만들며, 과거 확정본의 범위를 유지한다. 현재 범위를 반영하지 않아도 과거 범위로
정정을 확정할 수 있다. `?revision=N`은 선택 기록의 읽기 전용 화면이다.

행 저장은 `revision_id`, `value_id`, 행 `If-Match`를 함께 보낸다. 409나 제거된 행은 작성한 금액·날짜·사유를 보존하고
최신 기록과 비교한다. 범위가 달라지면 이름·분류·소유·지분·금액 기준·기간의 변경을 확인한 뒤에만 내 값을 재사용한다.
새 정정본·재생성된 행의 version이 우연히 1이어도 기존 편집을 그대로 저장하지 않는다.
페이지를 이어 읽는 중 revision ID나 version이 바뀌면 부분 데이터를 합쳐 표시하지 않고 다시 확인하도록 한다.

작성본 생성·확정·정정의 같은 요청은 취소/연결 오류/응답 유실 뒤에도 같은 Idempotency-Key를 사용한다.
본문이나 대상 revision version을 바꾸면 새 키를 사용한다. 자동 재전송은 하지 않으며 사용자가 재시도하거나
서버 상태를 다시 확인한다. 폼을 떠나면 현재 서버 기록을 다시 조회하며 완전한 오프라인 편집/재전송 큐는 제공하지 않는다.

## 검증 명령

```bash
pnpm api:generate
pnpm typecheck
pnpm --filter @sallimbook/client exec playwright test --config playwright.months.config.ts
uv run --project services/api python scripts/test_web_auth.py --months
```

UI 서버는 전용 loopback 18749 포트를 사용한다. 실제 HTTPS 검사는 전역 DB 잠금을 사용해 일회용 db-test(18745)에
고유 schema와 실제 migration/API를 띄운다. 기존 서버·신뢰 저장소·운영 설정은 변경하지 않는다. 합성 계정의 비밀번호와
브라우저 산출물은 mode 0700 임시 디렉터리 안에 두며 종료 시 폐기한다. 실패 출력은 고정 단계와 소스 위치로 제한한다.

## 검증 결과

- 생성 client와 TypeScript 검사 통과.
- 신규 월 UI 28개 통과: desktop/Android 크기에서 null·0·복사·변동 없음, 정확한 큰 정수와 HALF_UP, 기본값 미생성,
  동일 요청 멱등키·payload 변경 시 새 키, 취소/응답 유실, 행/revision ID 교체 충돌, 확정 확인란, 역사 보존,
  명시 범위 반영, 혼합 페이지 거부를 확인했다.
- 공통 fixture `catalog.json`의 T-01과 지분 반올림 예제를 UI 표시/참고 계산에 대조했다.
- 실제 HTTPS 1개 전체 흐름 통과: desktop 첫 월 등록·확정에서 Android 폭의 다음 월 복사·지분 변경·정정·과거 조회까지
  실제 PostgreSQL과 API로 실행했다. 1억 1원의 50%가 50,000,001원, 75%가 75,000,001원으로 저장되며,
  과거 75% 범위를 유지한 정정 금액과 이전 확정값이 서로 보존됨을 확인했다. 성공 응답 no-store도 확인했다.
- 해당 실행 후 DB 서비스 중지와 전역 잠금 반환을 확인했다.

초기 웹 UI 전체 회귀는 **190개 통과**(기존 162 + 신규 월 입력 28)했다. SB-013 통합에서 Android 월 전용
adapter 8개를 연결했다. 월·revision 조회, 이력, 작성본 생성, 값 변경, 범위 반영, 확정·재개방을
네이티브 전용 메서드로 실행하며 WebView HTTP로 우회하지 않는다. 취소 후 늦게 도착한 결과는 버리고,
서버 처리 가능성을 표시한 뒤 동일 멱등키로 명시적 재시도를 허용한다. 통합 결과는
[비교·추이 검증](assets-comparison-client.md)을 참조한다.
실제 Android 잠금/생체인증/기기 전환·운영 배포는 이 웹 검사로 검증했다고 간주하지 않는다.
비교·추이·홈 연결은 SB-013에서 같은 월 기록을 조회한다.

## 미래 월·전월 미확정 경고·전월 확정값 불러오기 — 2026-10-20

- 서버: `test_future_month_draft_is_rejected_until_the_seoul_month_starts`, `test_carry_previous_fills_only_untouched_missing_rows_once`, `test_carry_previous_requires_a_confirmed_previous_month_and_an_open_revision`, `test_basis_change_clears_carried_origin_with_the_amount`, OpenAPI 헤더 시험.
- 브라우저: `a future month offers no draft and a server future-month rejection is explained`, `starting a month after an unconfirmed previous month needs an explicit acknowledgment`, `carry-previous fills only untouched missing rows and reuses its key after an ambiguous failure`, `carry candidates mirror the server rule for untouched missing rows`, `carried notes follow the verification state, including legacy cleared carried rows`.
- Android 정책·bridge: `CashflowPolicyTest.nineMonthlyCommandsRoundTripOnlyTheirAllowedRoutesAndHeaders`, `carryPreviousNeedsRevisionVersionAndKeyAndEchoesTheRevision`, `AuthPolicyTest.assetMonthAndAccountErrorsKeepTheirCode`, `native carry-previous keeps the revision version and one key across an ambiguous retry`, `47 named metadata commands retain DTO values and mutation keys without web HTTP`.

검증 결과(2026-10-20): `pnpm typecheck`·ruff(check/format)·`pnpm format:check` 통과, DB 미사용 pytest **912 passed**,
`test_assets`·`test_accounts`·`test_asset_months`·`test_asset_comparison`·`test_exports` DB 시험 **232 passed**와 `alembic check` 변경 없음,
브라우저 10개 spec **262 passed**, JVM `AuthPolicyTest` 13·`CashflowPolicyTest` 10·`FinancePolicyTest` 13·`ComparisonPolicyTest` 12 통과,
`pnpm api:generate` 후 생성 client 변경 없음, 실제 HTTPS `--finance`·`--months`·`--comparison` 각각 종료 코드 0.
Android 실기기 화면 확인은 미실행이다.
