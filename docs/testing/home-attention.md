# 홈 확인할 일과 보증 임박 (P13)

R-02/R-03/R-05/R-08/R-15/R-17/R-19,
[Issue #165](https://github.com/jihoon22-lee/SallimBook/issues/165).

홈 상단의 월간 자산과 오늘 소모품은 그대로 우선한다. 그 아래 확인할 일은 지난 예정일의
미납·부분 납부(이전 달 포함), 지난달 미확정/미작성/정정본, 추가 서류 필요 청구, 어느 청구에도
연결하지 않은 활성 비용이다. 원본 상세 링크로 처리하고 재조회하며 별도 완료 체크는 없다.
자산 선택 월이 바뀌어도 현재 할 일과 지난달은 바뀌지 않는다.

목록의 모든 페이지를 읽으며 처음 3건 이후는 펼쳐 볼 수 있다. 조회 실패는 이전 항목/건수를
숨기고 재시도를 제공한다. 예정과 실제의 금액 판단은 서버 원 단위 계산을 사용한다.
기존 보조 타일은 선택 월의 수입·보험금 순유입·예정/실제 납부 요약과 원본 링크로 줄였다.
기록 없음과 명시적 0원, 예정액 미정을 구분한다.

가전 보증은 서버가 제공한 서울 기준일과 상태를 사용한다. 오늘부터 30일 이내(양끝 포함)에
끝나는 활성 보증의 개수를 펼치기 전에도 표시한다. 31일 이후·이미 만료·미입력·사용 종료 가전은
임박 개수에서 제외한다. 실제 보증 범위는 구매 문서로 확인한다.

새 저장소/DDL은 없다. [API 계약](../api-contract.md)의 홈 확인할 일 항목에 기한 지난 납부와
전체 계약 기준 미연결 비용 조회 조건을 기록했다. 실제 기기 인수는 사용자가 직접 수행하는
기존 결정과 구분한다. 실행 결과는 이 문서와 해당 PR에 남긴다.

## 검증 결과

- `pnpm test:database services/api/tests/test_overdue_obligations.py services/api/tests/test_home_claim_attention.py services/api/tests/test_insurance_events.py::TestInsuranceEventCorrections::test_expense_claim_filter_is_policy_scoped_and_preserves_one_original -q`:
  5개 통과, migration no-op 및 base/head 왕복 통과. 서울 자정·전전월·미정/0/일부/초과 납부,
  완료/재개방/건너뜀/대체, 페이지 제한 전 필터, 타가계 404·미인증 401·조합 오류 422를 확인했다.
  첫 시험의 완료 fixture는 실제 납부가 필요하다는 기존 조건에 맞춰 일부 납부 후 완료하도록 고쳤다.
- `pnpm test:web home-attention.spec.ts homecare-ui.spec.ts refresh-and-navigation.spec.ts --workers=2`:
  최종 80개 통과. 원본 상태 변경 후 해소·실패를 0건으로 표시하지 않음·모든 페이지·서울 날짜
  변경·자산 선택 월 독립·30일 경계와 상단 우선순위·네이티브 HTTP 우회 부재를 포함한다.
  기존 보험 사건 링크는 보존했으며 기존 보증/홈 시험의 청구 fixture는 추가 서류 상태로 바꿨다.
  상위 공동 수정자 표시의 로그인 상태 전환 수정 이후 신규 홈 시험 10개도 다시 통과했다.
- Android `testDebugUnitTest --tests '*FixedCostPolicy*' --tests '*InsuranceEventPolicy*'`:
  37개 통과. 새 고정 GET/boolean query와 응답 날짜·상태 검증을 포함한다. 잘못된 응답의
  거절 코드 기대값을 `ACCESS_DENIED`로 맞췄다.
- `uv run --project services/api python scripts/test_web_auth.py --cashflow`: 실제 HTTPS/API/DB
  통과. 이전 월 미납 3건이 홈에 나타나고 원본 납부 후 해당 회차가 빠져 2건이 되는 것을 확인했다.
  기존 수입·계좌 스냅샷 독립·원리금/연금·종료/재생성 흐름도 유지됐다.
- API 단위 1,023개 통과, 기존 DB 미설정 23개 skip, 653개 DB 대상 제외. 문서 도구 258개,
  TypeScript·ESLint·Prettier·Ruff·생성 계약·빌드·로컬 링크/manifest 검증 통과.
  기존 500kB 번들 경고는 남는다. 새 데이터 마이그레이션은 없다.
