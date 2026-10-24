# 공용 소모품 구매 계획·주문·입고

Issue #169 · R-01/R-02/R-16/R-17/R-19/R-22. P16의 계산·기록 경계와 검증을 정리한다.

## 계산과 사용자 동작

구매 계획의 시작은 서버의 서울 오늘이며 종료일은 오늘부터 최대 365일 뒤까지다. 활성 기기·활성 연결의 교체 수요를 같은 소모품 ID별로 먼저 합산한다. 두 기기가 각 1개를 필요로 하고 공용 재고가 1개이면 수요 2개·재고 1개·부족 1개다. SKU를 입력하지 않은 소모품도 ID별로 구분하며 이름만 같다는 이유로 합치지 않는다.

다음 확인일이 오늘 이전이면 이번에 확인할 수요 한 번만 오늘에 놓는다. 지나간 주기를 모두 사용했다고 추정하지 않는다. 이후 선택 기간의 수요는 첫 확인일에 교체하고 현재 주기를 유지한다는 가정의 구매 참고값이다. 직접 확인 주기는 명시한 다음 확인일 한 번만 계산한다. 다음 확인일이 없으면 수요를 0으로 단정하지 않고 날짜 미정 연결 수를 표시한다. 구매 계획 조회는 재고·교체일·주문을 변경하지 않는다.

현재 재고 부족은 `max(기간 수요 - 공용 재고, 0)`이다. 구매 예정·주문 중 수량은 재고와 따로 표시하고, 추가 계획 참고 수량은 부족에서 두 수량을 제외한 0 이상 값이다. 아직 오지 않은 주문이 재고가 되지는 않는다. 같은 소모품에 진행 중 계획·주문이 여러 개면 함께 표시해 중복을 검토한다. 마지막 구매 링크·단가는 취소되지 않은 실제 입고 중 실제 입고일·작성 시각·ID 순으로 가장 최근 기록을 사용한다. 미입력 단가와 0원은 구분한다.

구매 예정 → 주문 중 → 전체 입고 순서로 수동 기록한다. 실제 주문일·입고일은 사용자가 확인하고 오늘 이후 날짜는 받지 않는다. 수량이나 단가·구매 링크는 입고 전에 현재 버전을 확인해 수정할 수 있다. 도착 수량이 다르면 실제로 도착한 묶음에 맞춰 주문을 나눠 기록한다. 구매 예정·주문 중은 이유를 남기고 취소할 수 있다. 입고 완료·취소 이력은 덮어쓰거나 삭제하지 않는다.

실제 입고 명령은 기존 재고 입고 이벤트 생성과 주문 완료를 같은 트랜잭션에서 수행한다. 두 사용자가 동시에 입고하거나 동일 요청을 다시 보내도 한 번만 늘어난다. 주문 버전과 공용 재고 버전을 모두 확인한다. 기존 재고 화면에서 입고를 취소하면 주문 원본에는 입고 취소 상태를 함께 표시하며, 같은 주문을 재입고하지 않는다. 구매·주문 기록은 실제 금융 거래나 납부가 아니며 월 자산·수입·고정 납부를 자동 변경하지 않는다.

## 구현·검증 결과

`0021_consumable_orders`, 계획/주문 API 8개 operation, 생성 TS client, Android 고정 경로/본문/응답 검증,
웹/native 구매 계획·주문·입고 화면을 구현했다. 모든 시험은 합성 자료다.

- `pytest services/api/tests/test_purchase_calculations.py -q`: 공유 수요·월말·윤년·지난 기한·직접 확인·최대 날짜 6개 통과.
- `pnpm test:database services/api/tests/test_consumable_orders.py services/api/tests/test_activity.py -q`: 23개 통과. 권한·충돌·재전송·동시 입고·실패 원자성·날짜/용량·이전 재고 migration 보존/자료가 있는 downgrade 거부·변경자와 현재 이름 포함.
- `pnpm test:database services/api/tests/test_consumable_orders.py services/api/tests/test_homecare_database.py -q`: 48개 통과, migration 왕복·모델 일치 확인.
- `pytest services/api/tests -m 'not database' -q`: 최종 1,029개 통과, DB 미설정 23개 skip은 DB 통과에 포함하지 않는다. 새 이름 검색 두 경로를 명시적 계약 허용 목록에 반영했다.
- 웹/native 신규 주문·기존 생활 관리·작업 이력 회귀는 122개 통과 뒤 선행 홈 호출 기대 2건을 수정해 별도 2개 통과. 이후 신규 주문·native 생활 관리 38개와 임시 합성 화면 캡처 2개가 통과했다. 기간·검색 접기 정리 뒤 `pnpm test:web consumable-orders.spec.ts --workers=4` 22개 통과. 응답 유실 뒤 동일 키·입력 유지, 수량/메모/재고 충돌 비교, 첫 페이지 밖 검색, 날짜 경계, 320px·확대·다크 포함.
- `uv run --project services/api python scripts/test_web_auth.py --homecare`: 실제 API/PostgreSQL/HTTPS 통과. 두 기기 수요 2·공용 재고 1·부족 1 → 예정/주문 중 재고 1 유지 → 실제 입고 2 → 원장 취소 1을 확인하고, 월 자산 snapshot 불변을 대조했다. HTTP mock 없음.
- Android `NativeHomecarePolicyTest`·`NativeConsumableOrderPolicyTest`·`NativeAuditWireTest` 31개, 전체 `pnpm android:build`의 JVM 470개와 debug 빌드 통과. `:app:assembleDebugAndroidTest`는 계측 APK compile 통과이며 실기기 실행 통과와 구분한다.
- 타입·Ruff·ESLint·Prettier·웹 빌드·문서 검사·문서 도구 258개 통과. 기존 Vite 큰 청크·Gradle deprecation 경고는 남는다.

최종 계측 CI와 실제 설치 기기 인수는 별도로 기록한다. 새 기능은 원본 입고 취소를 보존하며 자동 금융 거래·서버 비밀 필드·의존성을 추가하지 않는다.
