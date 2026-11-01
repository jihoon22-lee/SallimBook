# 등록 기록 기반 살림 현황 홈 검증 (#195)

R-02/R-03/R-07/R-08/R-13/R-15/R-22,
[Issue #195](https://github.com/jihoon22-lee/SallimBook/issues/195),
[대시보드 우선 ADR](../adr/dashboard-first-household-status.md).

홈 상단은 서버 현황 조회 `GET /api/v1/household-overview` 한 번으로 등록 기준 순자산·분류 타일·보험·카드·가전과
월 계획 기준 여유를 그린다. 항목마다 마지막으로 입력·확인한 금액과 기준 월을 쓰고, 금액 미입력·오래된 금액은
알림으로만 둔다. 예정·실제 납부 요약과 월별 자산 변화·월 기록 관리는 펼칠 때만 불러온다. 여러 영역이 함께
실패하면 다시 불러오기 하나로 묶는다. 보험 첫 화면은 같은 조회로 진행 중인 사건·청구를, 자산·계좌 목록은 그 달
금액이 없을 때 최근 입력 금액을 참고로 보인다. 예상 수입 화면의 성과연도 합계는 서버
`GET /api/v1/income-planning/bonus-summary`가 계산한다. 웹은 홈만 첫 번들에 두고 다른 화면은 처음 열 때 받는다.

새 저장소·DDL·마이그레이션은 없다. 현황 조회는 월 기록을 만들거나 바꾸지 않고 스냅샷을 자동 가감하지 않는다.

## 검증 결과

결과는 아래 명령을 실제로 실행한 것만 적는다.

- `pnpm test:database services/api/tests/test_household_overview.py services/api/tests/test_income_planning.py services/api/tests/test_expense_plans.py services/api/tests/test_expense_plan_import.py`:
  44개 통과, 새 마이그레이션 없음. 항목별 최근 입력 금액과 기준 월, 이어 온 뒤 확인하지 않은 값 제외, 금융·대출의
  3개월 기준, 계좌 한 번 합산, 월 계획 기준 여유, 다른 가계 제외와 성과연도 합계(미확인 건수·비활성 제외·현금 기록
  미생성)를 확인했다.
- `pnpm android:sync` 후 Gradle `:app:testDebugUnitTest :app:compileReleaseKotlin`: JVM 495개 통과(실패·오류·건너뜀 0).
  새 `HouseholdOverviewPolicyTest` 4개와 상여 합계 시험 1개를 포함한다.
- 전체 Playwright(데스크톱·Android 크기) 1,884개 중 1,871개 통과, 13개 실패.
  - 네이티브 홈 시험 2개는 홈이 더 이상 월 비교를 바로 읽지 않는 바뀐 동작을 반영하지 못했다. 선택 월의 현황 조회와
    펼칠 때만 읽는 월 비교·예정 납부를 확인하도록 고쳤고, 네이티브 mock을 쓰는 5개 사양 92개가 다시 통과했다.
  - 나머지 11개는 다른 작업으로 장비 부하(load average 23~27)가 높을 때 시간 제한을 넘었다. 같은 시험을 따로 다시
    실행해 30개가 모두 통과했다(`name-search.spec.ts:184` 4개 포함).
- 화면별 코드 분할: `pnpm build` 기준 첫 화면 JavaScript가 1,254kB(gzip 330kB)에서 540kB(gzip 165kB)로 줄었다.
  `error-screen.spec.ts`는 이전 빌드 파일이 없을 때 한 번만 새로고침하고, 다시 없으면 오류 화면을 보이며, 오프라인에서는
  새로고침하지 않는 것을 확인한다.
- `pnpm typecheck`, `pnpm lint`, `pnpm format:check`, Ruff check·format 통과. `pnpm api:generate` 뒤 생성 계약 diff 없음
  (경로 2개와 스키마 추가만, 기존 경로·스키마 변경 없음). API 단위 1,100개 통과(DB 미설정 46개 skip, DB 대상 709개 제외),
  저장소 도구 264개와 `scripts/validate_docs.py` 통과. `pnpm build`에서 500kB chunk 경고가 사라졌다.
- 실제 HTTPS+PostgreSQL: `TMPDIR=~/.cache/sallimbook/test-tmp uv run --project services/api python scripts/test_web_auth.py`의
  기본·`--onboarding`·`--finance`·`--months`·`--comparison`·`--cashflow`·`--expense-plans`·`--homecare`·`--insurance` 9개 모드
  모두 통과. 실제 서버의 새 현황 조회와 화면별 코드 분할을 포함한 빌드로 홈·자산·생활비·보험 흐름을 확인했다.
- 실기기 화면·네이티브 동작 확인은 사용자가 따로 수행한다. 위 시험은 실제 Android 기기 보안을 검증하지 않는다.
