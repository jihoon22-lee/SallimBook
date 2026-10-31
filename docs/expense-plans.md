# 월 지출 계획과 실제 납부

R-08, R-09, R-18 / Issue #189.

기존 고정 지출 안에서 날짜 없는 월 계획을 먼저 저장한다. 납부일 확인이나 월 마감은 등록 조건이 아니다. 계획 저장·수정만으로 거래, 납부, 연체, 자산 잔액을 만들거나 변경하지 않는다. 실제 납부는 기존 예정 회차 화면에서 별도로 기록한다.

## 데이터와 계산

`recurring_rule_versions`가 기존 일정과 새 계획의 단일 원본이다. `tracking_mode`는 `plan_only`/`scheduled`, `plan_kind`는 `recurring`/`budget`, `budget_treatment`는 `included`/`external_support`/`payroll`/`reference_only`다. 기존 행은 scheduled/recurring/included로 유지한다. 관련 구성원은 결제수단 소유자와 별개의 household-scoped `subject_member_id`다. 급여 관련 표시는 별도 집계 이유이며 급여 차감 사실을 단정하지 않는다.

금액 미입력과 0원은 구분한다. 연간 원금액을 보존하고 `amount / (12 * interval)`을 원 단위 반올림(ROUND_HALF_UP)한 행별 월 환산액을 합산한다. 월간은 `amount / interval`이다. 일 단위 주기는 임의 월 환산을 하지 않고 환산 불가 건수를 반환한다. 변동 예산은 월간·간격 1·계획 전용이다. 대출 총 납입액과 저축 이체는 소비액으로 단정하지 않고 경제적 성격별로 구분한다. 합성 공통 예제는 `packages/test-fixtures/expense-plans.json`이다.

기준일에 유효한 버전만 하나씩 집계하며 관리방식 전환으로 중복 또는 누락하지 않는다. 과거 버전 내용은 불변이다. 회차 참조가 전혀 없는 계획은 등록 당일도 이전 버전을 철회하고 새 버전을 추가할 수 있다. 종료 시에도 이력을 보존한다. 일정 변경은 기존 납부·수동 조정·지난 회차를 보존한다.

## API와 이전 앱 호환

- `GET/POST /api/v1/expense-plans`, `GET/PATCH/DELETE /api/v1/expense-plans/{plan_id}`, `POST /{plan_id}/end`.
- `GET /api/v1/expense-plan-summary?as_of=YYYY-MM-DD`: fixed/budget/combined/excluded 알려진 금액, 미입력·환산 불가 건수, 분류·합계 처리·경제적 성격별 소계. 모든 KRW는 십진 문자열.
- 목록은 cursor/limit/q 및 account_id/card_id 연결 필터를 제공한다.
- `POST /api/v1/expense-plan-payment-switch/preview`, `POST /api/v1/expense-plan-payment-switch/{plan_id}`: 기존 서비스의 수단만 변경하는 동작을 새 계획 DTO로 제공한다.

쓰기에는 기존 가계 잠금·권한·CSRF·Idempotency-Key·If-Match/409·감사를 적용한다. 일괄 등록은 commit 없는 생성 함수를 공유한다. 변경 필드명만 감사에 남기고 금융 금액이나 메모를 감사 로그에 복제하지 않는다.

기존 일정 DTO에는 nullable 납부일이나 새 키를 추가하지 않는다. 기존 목록과 결제수단 연결 DTO는 일정만 투영한다. 계획 이력이 있는 항목의 이전 API 쓰기는 `PLAN_CLIENT_REQUIRED`로 거부한다. 이전 API에서 순수 일정 수정 시 새 메타데이터를 유지한다. 결제수단 종료 영향 검사는 응답 버전과 무관하게 계획도 포함한다. 이전 실제 납부 집계 의미는 바뀌지 않는다. 생성 OpenAPI/TypeScript 계약은 같은 변경에서 갱신한다.

## 마이그레이션과 운영 경계

0026은 기존 규칙에 계획 메타데이터와 nullable anchor를 추가한다. DB CHECK/FK는 API와 동일한 조합 및 가계 범위를 보장한다. 새 계획/메타데이터가 존재하면 downgrade를 거부한다. 이 데이터를 등록한 이후에는 0026을 이해하는 API를 유지해야 한다. 웹/APK 되돌리기와 DB/API 되돌리기를 구분하며, 이전 API로 자동 복귀하거나 데이터를 지워 복구하지 않는다.

실자료는 공개 소스·fixture·CI에 포함하지 않는다. 배포 전에 전체 검사와 실제 HTTPS 검증을 끝내고, 배포 전후 암호화 백업 및 격리 복원에서 신규 행/열 보존을 확인한다.
