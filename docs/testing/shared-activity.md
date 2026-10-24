# 공동 작업자 표시와 최근 작업 (P12)

R-01/R-02/R-05/R-19/R-22, [Issue #163](https://github.com/jihoon22-lee/SallimBook/issues/163).

자산·계좌·카드·수입·보험 사건/계약/진료/청구·의료 금전·가전/소모품 상세와 충돌 비교에
기존 수정자 ID와 서울 시각을 표시한다. 월 기록에는 확정자를 표시한다. 구성원 이름은 인증된
가계 구성원 조회를 화면 트리에서 공유하며 실패하면 확인 실패와 재시도를 표시한다.
일반 가족/환자 이름과 실제 편집한 로그인 구성원을 혼동하지 않는다.

고정 납부 규칙/회차처럼 기존 응답에 수정자 필드가 없는 경우, 기존 감사 조회의 최신 이벤트와
화면 버전을 대조한다. 일치하지 않으면 수정자를 추측하지 않고 확인 불가로 표시한다.
원본 재조회나 작업자 조회는 작성 중인 초안을 바꾸지 않는다.

홈의 월간 자산·오늘 소모품 아래와 설정에서 `/activity`로 이동한다. 최근 작업은 현재 이름,
작업자, 서울 시각, 작업 종류, 내부 상세 링크를 표시하고 구성원/기간 필터와 더 보기를 제공한다.
원본을 찾지 못하면 확인 불가를 표시한다. 오류 뒤 이전 결과를 숨기고 명시적으로 재조회한다.
필터·조회 결과를 URL이나 브라우저 저장소에 저장하지 않는다. 별도 활동 이벤트 저장소는 없다.
[API 계약](../api-contract.md)의 가계 업무 최근 작업 조회를 따른다.

검증 결과는 해당 PR에 실행 명령·실패 수정·최종 결과를 기록한다. 합성 데이터만 사용하며
실제 Android 기기 인수는 사용자가 수행하는 기존 결정과 구분한다.

## 실행 결과

- `pnpm test:database services/api/tests/test_activity.py services/api/tests/test_audit.py -q`와
  후속 `pnpm test:database services/api/tests/test_activity.py -q`,
  `pnpm test:database services/api/tests/test_activity.py -k medical_activity -q`를 실행했다.
  신규 14개와 기존 감사 4개가 최종적으로 통과했다. 첫 실행에서 카드 별칭 null의 표시를
  상품명으로 보완했다. 의료 배분 시험은 최초 지급이 아닌 연결 정정에 배분 감사가 생기는
  실제 계약에 맞춰 고쳤고, 누락된 fixture import도 수정했다. 마지막 의료 시험 1개 통과,
  다른 13개 통과와 migration no-op/왕복 검증을 확인했다.
- `uv run --project services/api pytest services/api/tests -m 'not database' -q`:
  1,023개 통과, DB 환경이 없는 기존 23개 skip, 649개 DB 대상 제외. 이 skip은 DB 통과가 아니다.
- `pnpm test:web shared-activity.spec.ts settings-audit.spec.ts settings-audit-native.spec.ts assets.spec.ts --workers=2`:
  76개 통과. 관련 fixed/cashflow-native/insurance-events/homecare/cards 회귀 묶음은 206개 통과.
  최종 `shared-activity.spec.ts homecare-ui.spec.ts --workers=2`는 64개 통과했다.
  고정 납부 신규 시험의 mock 등록 순서가 실제 규칙 요청을 404로 가리던 문제를 수정했다.
- Android `testDebugUnitTest --tests '*NativeAudit*'`: HTTP 4개·wire 12개, 총 16개 통과.
  새 활동 경로와 이름·내부 링크의 검증, 외부 URL·임의 추가 필드·보안 동작 거절을 포함한다.
- `uv run --project services/api python scripts/test_web_auth.py --audit`: 실제 HTTPS/API/PostgreSQL
  통과. 업무 이벤트 52건의 전체 페이지·현재 이름·상세 링크·작업자, 타가계·메모 배제와
  기존 감사의 순수 메타데이터·만료 세션·no-store·저장소 비사용을 확인했다.
- TypeScript, ESLint, Prettier, Ruff, 생성 API 계약, 빌드, 문서 도구 258개와 로컬 링크 검증 통과.
  기존 번들 크기 경고는 남는다. 운영 배포와 실제 Android 기기 인수는 이 PR의 결과와 별도다.
