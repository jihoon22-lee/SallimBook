# API 계약

상태: 구현 명세. SB-001~002에서 health/readiness와 공통 오류·타입 기반을 구현했다. 아래 업무 API는 후속 Issue 대상이다.
기본 경로 `/api/v1`, JSON UTF-8, 원화는 정수 문자열, ID는 UUID.
FastAPI OpenAPI를 구현 시 단일 계약으로 관리하고 TS client를 생성한다([S11](references.md)).

### 현재 구현된 기반 API

`GET /api/v1/health`는 미인증으로 `200 {"status":"ok"}`를 반환한다.
프로세스 생존 확인이며 DB 준비·로그인·가계 데이터 상태를 뜻하지 않는다.
`GET /api/v1/ready`는 PostgreSQL 연결 및 요구하는 Alembic revision 확인 후 같은 200 응답을 반환한다.
DB 미설정·접속 실패·스키마 미준비는 503이며 내부 연결 정보는 반환하지 않는다.
업무 API 응답은 서버가 생성한 `X-Request-ID`, `Cache-Control: no-store`를 포함한다.
422 검증 오류는 오류 코드와 body/query 등 요청 위치만 포함한다. 동적 객체 key·추가 필드명·
입력값·검증 context·SQL을 노출하지 않는다.
개발 OpenAPI는 `/api/openapi.json`, 운영 환경에서는 대화형 문서·OpenAPI HTTP 공개를 끈다.
`pnpm api:generate`로 구현에서 OpenAPI와 TypeScript client를 생성한다.

## 1. 공통 규약

모든 가계 자원은 인증 사용자 membership에서 가계를 결정한다.
클라이언트의 household_id를 신뢰하지 않는다. 같은 가계의 다른 구성원 소유 자산도 공동 정책에 따라 읽고 수정한다.
PATCH에는 `If-Match: "7"`처럼 version을 보내며 최신 버전이 아니면 409.
원본 금전 기록/지급/교체/회차 생성 POST에는 `Idempotency-Key`가 필요하다.
같은 key+payload는 같은 결과를 반환하고 다른 payload는 409.
민감 API는 `Cache-Control: no-store`, 오류 응답에 입력 원문·SQL·토큰을 넣지 않는다.
목록은 cursor pagination, 기본 50개/최대 200개. 날짜/금액/문자열 필터를 명시적으로 whitelist한다.

### 오류 예시

```json
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "다른 기기에서 수정했습니다. 최신 내용을 확인해 주세요.",
    "request_id": "example-request-id",
    "current_version": 8
  }
}
```

400 malformed, 401 unauthenticated, 403 forbidden, 404 inaccessible/not-found,
409 conflict/idempotency/stock, 422 business validation, 429 rate limit.
객체 존재 자체가 민감하면 다른 가계의 ID에는 404를 반환한다.

## 2. 엔드포인트 목록

| 도메인 | 메서드·경로 | 주요 계약 |
|---|---|---|
| 인증 | POST /auth/login, /auth/logout, /auth/refresh | 웹 쿠키와 native token 응답 분리 |
| 패스키 | POST /auth/passkeys/options, /auth/passkeys/verify | challenge/RP ID/origin/UV 검증 |
| 재인증 | POST /auth/step-up/options, /auth/step-up/verify | 짧은 목적 제한 인증 상태 |
| 사용자 | GET /me, GET /household/members | 허용된 공동 가계만 |
| 초대·기기 | POST /household/invitations, GET /devices, DELETE /devices/{id} | 재인증, 기기 세션 폐기 |
| 홈 | GET /dashboard?month=YYYY-MM | 자산은 선택 월, 소모품은 서버 오늘 |
| 자산 | GET/POST /assets, GET/PATCH/DELETE /assets/{id} | 종료/삭제 의미 구분 |
| 계좌 | GET/POST /accounts, GET/PATCH /accounts/{id} | 자산 원본과 1:1 |
| 계좌번호 | POST /accounts/{id}/reveal | 서버 재인증, no-store, 반환 audit |
| 월 기록 | POST /asset-months/{month}/draft | 전월확정 복사; 반복 호출 중복 없음 |
| 월 기록 | GET /asset-months/{month}, PATCH /asset-months/{month}/values/{assetId} | 행 상태·기준일·version |
| 월 확정 | POST /asset-months/{month}/confirm, /reopen | 미확인 거부, 새 revision |
| 비교 | GET /asset-comparison?from=...&to=... | 전체와 동일 범위 차이·경고 |
| 수입 | GET /income?month=..., POST /income | 보험금 원본은 지급 API에서만 생성 |
| 수입 정정 | PATCH /income/{id}, POST /income/{id}/void | 월확정 범위와 별개 감사 |
| 고정비 | GET/POST /recurring-rules, PATCH /recurring-rules/{id} | 적용 시작일·새 version |
| 납부 회차 | GET /obligations?month=..., POST /obligations/generate | 반복 안전, 미래 회차 갱신 |
| 납부 확인 | POST /obligations/{id}/settlements, /skip | actual 금액·수단·분할 |
| 카드 | GET/POST /cards, GET/PATCH/DELETE /cards/{id} | metadata only, 영향 확인 |
| 보관함 | GET /vault/status, GET /vault/wrappings/me | 암호문과 키 파라미터만 |
| 보관함 | GET/PUT /cards/{id}/secret-envelope | PAN/expiry 암호문만, CVC schema 없음 |
| 키 관리 | POST /vault/enroll-member, /vault/rotate, /vault/recovery-wrap | 계정 step-up, 원자적 버전 전환 |
| 계약 | GET/POST /insurance/policies, GET/PATCH /insurance/policies/{id} | 보험료는 연결 규칙 참조 |
| 사건 | GET/POST /insurance/cases, GET/PATCH /insurance/cases/{id} | 치료·정산 상태 분리 |
| 진료 노드 | POST /insurance/cases/{id}/nodes, PATCH/DELETE /insurance/nodes/{id} | 트리 순환·동일 사건 검사 |
| 의료비 | POST /insurance/cases/{id}/expenses, POST /insurance/expenses/{id}/refunds | 실제 지불 원본 1건 |
| 청구 | POST /insurance/cases/{id}/claims, PATCH /insurance/claims/{id} | 비용 N개 연결 |
| 지급 | POST /insurance/payouts, POST /insurance/payouts/{id}/returns | 현금 원본+배분; 청구ID 선택 |
| 정산 | GET /insurance/cases/{id}/summary | 비용/환불/실수령/반환/부담 |
| 가전 | GET/POST /appliances, GET/PATCH /appliances/{id} | 제품·호환 소모품 |
| 소모품 | GET/POST /consumables, POST /consumables/{id}/stock-movements | 재고 조정 사유 |
| 교체 | POST /appliance-consumables/{id}/replacements | 재고와 이력 원자적 갱신 |
| 첨부 | POST /documents, POST /document-links, GET /documents/{id}/download | 타입/크기/권한/검증 상태 |
| 감사 | GET /audit-events | 가계·필요 필드만, 비밀 제외 |
| 내보내기 | POST /exports | 재인증, 기본 카드비밀·CVC 제외 |

보험료 금액 편집은 별도 독립 API가 아니라 recurring-rules의 적용일 변경 서비스를 재사용한다.
CVC의 업로드/동기화/다운로드 API는 **존재하지 않는다**.

## 3. 홈 응답 설계

```json
{
  "asset_month": "2026-10",
  "asset_status": "draft",
  "verified_count": 6,
  "total_count": 8,
  "net_assets_krw": "525000000",
  "comparison": {"delta_krw": "8500000", "scope_changed": false},
  "consumables_as_of": "2026-10-17",
  "consumable_alerts": [],
  "cash_summary": {"earned_income_krw": "7200000", "insurance_received_krw": "800000"},
  "registered_fixed_payments_krw": "2850000"
}
```

모든 값은 합성 예시다. 누락 데이터가 있으면 임시 합계와 경고를 함께 반환한다.

## 4. 보험금 수동 입력 예시

```json
{
  "received_on": "2026-10-17",
  "amount_krw": "800000",
  "receiving_account_id": "00000000-0000-4000-8000-000000000001",
  "allocations": [
    {"case_id": "00000000-0000-4000-8000-000000000002", "claim_id": null, "benefit_type": "reimbursement", "amount_krw": "600000"},
    {"case_id": "00000000-0000-4000-8000-000000000002", "claim_id": null, "benefit_type": "fixed_benefit", "amount_krw": "200000"}
  ]
}
```

800,000원 입금 1건과 배분 2건을 같은 트랜잭션으로 만든다.
입금 계좌의 월 스냅샷은 변경하지 않는다. 월간 수입의 보험금 항목은 원본을 읽는다.
배분 합계가 다르거나 다른 가계 사건이 섞이면 전부 실패한다.

## 5. 비밀 API와 플랫폼 어댑터

일반 카드 응답: card id, 소유자, 카드명, 마지막 4자리, has_secret.
전체 카드번호·유효기간은 일반 응답에 없다. secret-envelope의 ciphertext에는 CVC가 포함되지 않는다.
Android 네이티브 모듈이 별도로 인증된 경로로 암호문을 가져와 로컬 인증 후 표시한다.
PC 웹에서는 별도 vault adapter가 암호문을 복호화하며 일반 Query cache나 URL로 전달하지 않는다.

## 6. 첨부

v1 허용 타입은 PDF/JPEG/PNG, 파일당 기본 20MB, 필요 시 설정값을 명시적으로 변경한다.
확장자·선언 MIME만 믿지 않고 실제 포맷·크기와 악성 내용을 검사한다.
다운로드는 권한 확인 후 스트림 또는 매우 짧은 만료의 목적 제한 링크를 사용한다.
치료명이나 실제 이름을 object storage key에 포함하지 않는다.
카드 앞뒷면 이미지 첨부는 secret 경계를 우회하므로 지원하지 않는다.
