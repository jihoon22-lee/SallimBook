# 공유 합성 테스트 fixture

SB-004 · R-22. [테스트·인수 기준](../../docs/testing-and-acceptance.md)의 T-01부터
T-24까지를 Python과 TypeScript에서 같은 JSON으로 읽기 위한 데이터다.
실제 금융·의료정보, 로그인 비밀, 카드번호나 보안코드는 없다.

- `identities.json`: H1의 부부 A/B와 권한 거부 시험용 별도 H2의 C/D,
  각 가계에 속한 자원 식별자. ID는 고정 namespace와 합성 이름으로 만든 UUIDv5다.
- `catalog.json`: 공통 보험 원본 graph, 24개 입력/기대 결과, 보충 경계 예제.
  `schema_version`은 이 fixture 포맷 버전이며 API 계약 버전이 아니다.

각 vector의 `kind=calculation_vector`는 순수 계산 예제이고,
`integration_scenario`는 저장·권한·중복·동시성·화면 같은 통합 수용 시나리오다.
계산 예제에도 실제 API와 양 플랫폼 검증은 필요하다. 모든 vector의
`implementation_status=pending`은 실제 제품 인수 증거가 아직 연결되지 않았다는 뜻이다.
`required_validation`에 필요한 계층을 기록한다. fixture 검사 성공을 제품 구현이나
T-01~T-24 인수 성공으로 보고하지 않는다.

금액은 필드 이름 끝에 `_krw`를 붙인 십진 정수 문자열이다. 금액 목록도 같은 규칙이다.
`null`은 미입력/비교 불가이고 `"0"`과 다르다. 지분·비율도 문자열이며,
수량·버전·상태코드는 JSON 정수다. Python은 `int`/`Decimal`, TypeScript는
`BigInt` 또는 정확한 십진 연산을 사용해야 한다. `Number`/float로 금액을 변환하지 않는다.
보충 예제에는 JavaScript의 안전한 정수 범위 밖 금액과 numeric(20,0) 경계를 포함한다.
`invalid_money_json`은 잘못된 JSON 값 자체를 **문자열로 인코딩**한 예제다.
fixture의 표준 금액 문자열은 앞쪽 0, `+`, `-0`, 공백을 사용하지 않는다.

T-12~T-16의 `*_fixture`는 `fixtures` 아래 객체를 가리킨다.
예를 들어 `medical_case.refund`는 병원 환불 원본이다.
의료비는 `medical_case.cash_records`의 실제 지불 원본만 합산한다.
`expenses`는 해당 원본과 진료 노드를 연결하고, `expense_lines`는 원본의 설명용 분해다.
`claim_expenses`는 같은 영수증을 두 청구에 연결하므로 합계에 추가하면 안 된다.
보험금 월 유입은 `insurance_receipts`의 원본 금액, 사건별 수령은 그 `allocations`를 사용한다.
직접 지급을 나타내는 `claim_id=null`은 허용한다. 환불과 보험사 반환은 원본 ID를 보존하는
별도 기록이다. 이 graph는 DB seed나 API 요청 스키마가 아닌 계산 검증용 자료다.

T-10의 평년은 2025년으로 고정했다. T-24는 고정 UTC 시각을 Seoul 날짜로 변환하므로
실행일에 따라 결과가 바뀌지 않는다. T-21은 어느 요청이 이기는지 지정하지 않고
성공·실패 수와 최종 재고를 지정한다. T-19/T-21/T-22/T-23에 대한 DB 트랜잭션,
잠금, 멱등키와 HTTP 처리가 구현됐다는 뜻은 아니다.
T-21의 초기 재고는 명시한 공용 `consumable_id` 한 개에 속한다. 서로 다른 두 기기의
`appliance_consumables` 관계와 각 요청의 관계 ID를 함께 제공해 같은 재고 행을 두 구성원이 경합하도록 정의한다.

검사 명령:

```bash
uv run --project services/api pytest services/api/tests/test_fixture_catalog.py
```

이 검사는 문서 ID의 누락, 금액 표현, UUID/가계 관계, 보험 원본 연결,
계산 예제의 산술·날짜 일관성을 확인한다. 실제 DB/API·Android·웹 기능 시험을 대체하지 않는다.
