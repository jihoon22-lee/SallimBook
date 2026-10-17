# API 계약

상태: 구현 명세. health/readiness·공통 계약, SB-005/007 계정·가계 권한과 SB-006 패스키 서버 API를 구현했다.
패스키의 PC/Android 인증 UI와 금융·보험·재고·보관함 업무 API는 후속 구현 대상이다.
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

### 계정·세션 구현

웹은 `POST /auth/web/login`, `GET /auth/web/csrf`, `POST /auth/web/logout`을 사용한다.
로그인은 `login_name`, `password`, `device_label`을 받고 HttpOnly/Secure/SameSite=Strict
`__Host-sallimbook_session` 쿠키와 메모리 전용 CSRF 토큰을 발급한다. 변경 요청은 정확한 Origin과
`X-CSRF-Token`을 요구한다. 재로딩 후 CSRF를 새로 받으며 이전 토큰은 무효화된다.
네이티브는 `POST /auth/native/login`, `/refresh`, `/logout`으로 분리한다. native 전용 transport는
`X-SallimBook-Native: 1`을 요구하고 Cookie/Origin을 거부한다. 이 헤더를 기기 신뢰 증거로 사용하지 않는다.
native access/refresh 응답은 Kotlin 인증 adapter에서만 처리한다. refresh 회전 재사용은 세션을 폐기한다.

로그인 상태에서 `POST /auth/web/reauthenticate` 또는 `POST /auth/native/reauthenticate`에
`{"password":"..."}`를 보내 현재 계정의 비밀번호를 확인한다. 응답은 `MemberResponse`이며 웹은 CSRF,
native는 현재 access token과 전용 transport 규칙을 적용한다. 기존 세션·기기·쿠키/토큰·절대 만료를
유지하고 최근 인증 시각만 갱신한다. 비밀번호 실패는 `403 REAUTHENTICATION_FAILED`, 시도 제한은 429이며
기존 세션을 파기하지 않는다. 만료·폐기된 세션/기기는 401로 거부한다.

`POST /auth/invitations/accept`는 일회성 초대 코드로 계정을 만들고 로그인은 별도로 수행한다.
인증된 `GET /me`, `GET /household/members`, `POST /household/invitations`,
`GET /devices`, `DELETE /devices/{device_id}`를 제공한다. 기기 폐기에는 `If-Match`가 필요하다.
초대와 기기 폐기는 최근 5분 내 실제 로그인 또는 아래 목적·대상별 step-up 증명을 요구한다.
기기 폐기 후에는 연결된 access/refresh 모두 기기 상태 검사에서 거부한다.
일반 개인정보나 토큰 원문을 오류·서버 로그로 출력하지 않는다.

### 패스키 서버 구현 · SB-006

다음 10개 경로의 상세 입력·응답은 생성된 OpenAPI를 기준으로 한다. 경로의 `/api/v1`은 생략했다.

| 메서드·경로 | 입력·동작 |
|---|---|
| POST /auth/passkeys/register/options | 인증된 사용자의 `label`; 최근 5분 로그인 필요 |
| POST /auth/passkeys/register/verify | `challenge_id`, 표준 등록 `credential`; 최근 로그인과 동일 세션·기기 확인, 201 메타데이터 |
| POST /auth/web/passkeys/options | `login_name`, `device_label`; 브라우저 로그인 challenge와 HttpOnly 기기 바인딩 쿠키 |
| POST /auth/web/passkeys/verify | `challenge_id`, 서명된 `credential`; 바인딩 쿠키 확인 후 웹 세션 쿠키·CSRF 발급 |
| POST /auth/native/passkeys/options | `login_name`, `device_label`; challenge와 네이티브 전용 `device_binding` |
| POST /auth/native/passkeys/verify | `challenge_id`, 서명된 `credential`, `device_binding`; native access/refresh 발급 |
| POST /auth/step-up/options | 인증된 세션의 `purpose`, UUID `target_id`; 해당 사용자의 등록된 패스키로 인증 요청 |
| POST /auth/step-up/verify | `challenge_id`, 서명된 `credential`; 2분 유효 `grant_token`, 목적·대상·만료 반환 |
| GET /auth/passkeys | 본인 미폐기 패스키 메타데이터 `items`, `next_cursor`; 기본 50/최대 200 |
| DELETE /auth/passkeys/{credential_id} | 본인 패스키 폐기; 최근 로그인과 `If-Match` 필요, 204 |

options 응답은 `challenge_id`, 라이브러리가 생성한 `public_key`, `expires_at`이다.
challenge는 5분 유효·일회성이며 서버에는 해시만 저장한다. 등록/step-up은 사용자·가계·세션·기기에,
로그인은 새 기기 ID와 바인딩 비밀에 연결한다. 웹 바인딩 쿠키는
`__Host-sallimbook_passkey`(Secure/HttpOnly/SameSite=Strict, 5분)이며 로그인 성공 후 지운다.
native의 바인딩 비밀·토큰은 Kotlin 인증 adapter에서만 처리하며 JS·URL·일반 저장소에 두지 않는다.
알 수 없거나 비활성화된 계정에도 동일한 discoverable 옵션 형태를 반환하고, 실제 검증은 실패한다.

등록/서명 검증은 challenge·RP ID·정확한 origin·UP/UV·credential 소유권·서명 카운터를 검사한다.
설정이 없으면 ceremony는 `503 PASSKEYS_DISABLED`, 부정확한 설정은
`503 PASSKEY_CONFIGURATION_INVALID`로 거부한다. 허용 origin 위반은 403,
만료·재사용·다른 요청 범위의 challenge 또는 검증 실패는 인증 오류로 처리한다.
PC의 WebAuthn UI와 Android Credential Manager·Digital Asset Links·실제 서명 인증서 연결은 아직 완료하지 않았다.

### 목적별 step-up 소비

현재 실제 소비 경로는 다음 두 가지다. 증명 발급 자체는 대상 자원의 접근 권한을 부여하지 않는다.

| 보호 동작 | options의 purpose | target_id | 최종 요청 |
|---|---|---|---|
| 파트너 초대 | `household.invite` | 현재 가계 UUID | POST /household/invitations |
| 본인 기기 폐기 | `device.revoke` | 폐기할 기기 UUID | DELETE /devices/{device_id}, `If-Match` 유지 |

1. 현재 세션으로 `/auth/step-up/options`를 호출하고 반환된 challenge를 패스키로 서명한다.
2. 같은 세션·기기에서 `/auth/step-up/verify`를 호출한다.
3. 반환된 `grant_token`을 해당 변경 요청의 `X-Step-Up-Token` 헤더로 한 번 전달한다.

서버는 가계·사용자·세션·기기·purpose·target·만료와 패스키/세션/기기의 활성 상태를 검사한다.
초대의 소유자·인원·로그인 이름 검사, 기기 소유권·버전 검사를 통과한 뒤 같은 트랜잭션에서 증명을 소비한다.
실패한 트랜잭션은 소비도 되돌린다. 성공한 증명은 재사용할 수 없고 다른 목적·대상·세션으로 옮길 수 없다.
헤더를 생략하면 기존 최근 로그인 검사를 사용한다. 헤더를 전달했다면 로그인 시각이 최근이어도 유효성을 검사한다.
step-up이나 refresh는 세션의 `authenticated_at`을 갱신하지 않는다.
다른 enum 목적(계좌 열람·내보내기·패스키 관리·보관함)은 소비 동작을 연결하기 전까지 권한을 부여하지 않는다.

### 자산 식별 정보 구현

`GET/POST /assets`, `GET/PATCH/DELETE /assets/{asset_id}`, `POST /assets/{asset_id}/archive`를 제공한다.
목록은 UUID cursor와 최대 200건, 자산/부채·분류·소유자·소유 방식·합산 여부·활성/종료 상태 필터를 사용한다.
응답의 `household_share`는 정확한 십진 문자열이고 생성·수정 응답은 `ETag`, 생성은 `Location`도 반환한다.
수정·종료·삭제는 `If-Match`가 필요하며 다른 가계의 자산/소유자는 404, 버전 충돌은 409다.
생성 계약에도 `If-Match` 필수 여부와 `ETag`·`Location` 응답 헤더를 명시한다. 누락된 버전 헤더는 `400 VERSION_REQUIRED`로 반환한다.
종료는 행과 과거 참조를 보존한다. 참조 중인 자산 삭제는 `409 ASSET_IN_USE`로 거부한다.
metadata에는 잔액·평가액·가전 가격·미래 연금액 필드를 받지 않는다. 실제 월 평가액은 후속 API다.
PATCH에서 생략한 필드는 유지한다. null로 지울 수 있는 필드는 `owner_member_id`, `ended_on`, `note`뿐이며
OpenAPI와 생성 TS 타입도 같은 선택 입력·null 규칙을 제공한다.

### 7) 금융계좌 (SB-011)

`POST /api/v1/accounts`, `GET /api/v1/accounts`, `GET/PATCH /api/v1/accounts/{account_id}`,
`POST /api/v1/accounts/{account_id}/reveal`을 구현했다.
생성 시 기존 금융 자산 `asset_id` 또는 새 자산 입력 `asset` 중 하나만 받는다. 자산 1건에 계좌는 1건이다.
생성·상세·목록·수정 응답에는 `masked_number`, `has_number`와 연결 자산을 제공하며 번호 원문·암호문은 없다.
번호는 생성/PATCH의 선택 입력이고 PATCH에서 명시적 null로 지울 수 있다. 키 설정이 없어도 번호 없는 metadata 조회·저장과 번호 제거는 가능하다.
전체 보기는 서버 재인증 또는 해당 계좌 UUID에 바인딩한 `account.reveal` 증명을 요구하며, 감사 commit 후 원문과 `display_for_seconds=30`을 반환한다.
계좌 PATCH에는 계좌 version의 `If-Match`를 사용한다. 자산 소유·종료 변경은 자산 API와 자산 version을 사용한다.
목록은 유형·소유자·active/closed/all 및 UUID cursor를 지원한다. 개설일과 자산 종료일을 양쪽 수정 경로에서 검증한다.
금액·잔액은 받지 않으며 계좌의 종료일과 상태는 자산에서 파생한다. Android 번호 입력/전체 보기 화면 연결과 실기기 검증은 후속 client 변경에서 완료한다.

### 8) 월간 자산 확인·정정 (SB-012)

아래는 `/api/v1` 아래 실제 구현된 계약이다. 월은 `YYYY-MM`, 금액은 음수 없는 정수 원 문자열 또는 null이다.

| 메서드·경로 | 동작 |
|---|---|
| POST /asset-months/{month}/draft | `copy_previous`; 멱등키 필수, 새 작성본의 불변 참조 반환 |
| GET /asset-months/{month} | 현재 revision·전체 합계·확인 건수·범위 변경 상태와 최대 200행 cursor 조회 |
| PATCH /asset-months/{month}/values/{asset_id} | `revision_id`, `value_id`, 입력 금액 또는 `unchanged`, 기준일·사유; 값 행 If-Match 필수 |
| POST /asset-months/{month}/sync-scope | `revision_id`, revision If-Match; 현재 자산 범위를 명시 반영하고 변경된 행을 미확인으로 돌림 |
| POST /asset-months/{month}/confirm | `revision_id`, revision If-Match·멱등키; 미확인 거부, 날짜/비교 범위 변화 확인 필요 |
| POST /asset-months/{month}/reopen | `revision_id`, 필수 `reason`, revision If-Match·멱등키; 이전 확정본을 보존한 새 revision |
| GET /asset-months/{month}/revisions | 정정 사유·확정 시각을 포함한 revision 목록 |
| GET /asset-months/{month}/revisions/{revision_no} | 해당 변경본의 당시 범위·금액 조회 |

draft·confirm·reopen 응답은 `month`, `revision_id`, `revision_no`, 원래 `version`만 가진다. 이후 편집해도 같은 멱등키는
같은 참조를 반환한다. 값 PATCH는 수정 행·현재 revision version·전체 합계를 반환한다.
필수 버전·멱등 헤더와 성공 응답의 `ETag`·`Location`도 OpenAPI 및 생성 client에 명시한다.
월 GET의 `version`은 현재 revision version이고 값 행마다 별도 version이 있다. 부모 revision이 바뀌면
`REVISION_CONFLICT`, 범위 재생성으로 행 UUID가 바뀌면 `VALUE_CONFLICT`, 기존 행 버전 충돌이면 `VERSION_CONFLICT`로 409를 반환한다.
포함된 항목이 미입력이면 해당 합계는 null이다. 전월 복사값은 숫자를 보여도 `provisional=true`이고 확정할 수 없다.
확정할 때 `acknowledge_non_month_end_dates`, `acknowledge_scope_change`로 표시된 차이를 명시 확인한다.
Android/웹 월 입력·비교·홈 화면 연결은 후속 client 변경에서 진행한다.

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
| 인증 | POST /auth/web/login, /auth/web/logout; GET /auth/web/csrf | 웹 보안 쿠키·CSRF |
| 인증 | POST /auth/native/login, /auth/native/refresh, /auth/native/logout | native 전용 토큰 응답·회전 |
| 재인증 | POST /auth/web/reauthenticate, /auth/native/reauthenticate | 현재 계정 비밀번호 확인, 같은 기기·세션 유지 |
| 등록 | POST /auth/invitations/accept | 최초/파트너 초대 일회성 등록, 자동 로그인 없음 |
| 패스키 등록 | POST /auth/passkeys/register/options, /auth/passkeys/register/verify | 현재 계정·최근 로그인·challenge/RP ID/origin/UV |
| 패스키 로그인 | POST /auth/web/passkeys/options, /auth/web/passkeys/verify; POST /auth/native/passkeys/options, /auth/native/passkeys/verify | transport별 기기 바인딩·기존 세션 발급기 공유 |
| 패스키 관리 | GET /auth/passkeys, DELETE /auth/passkeys/{credential_id} | 본인 메타데이터 목록·최근 로그인/If-Match 폐기 |
| 재인증 | POST /auth/step-up/options, /auth/step-up/verify | 짧은 목적 제한 인증 상태 |
| 사용자 | GET /me, GET /household/members | 허용된 공동 가계만 |
| 초대·기기 | POST /household/invitations, GET /devices, DELETE /devices/{id} | 최근 로그인 또는 X-Step-Up-Token, 기기 세션 폐기 |
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
