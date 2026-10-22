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

Issue #87의 기본 시작/연결 경로는 아래와 같다. `/api/v1` 접두사는 생략했다.

| 메서드·경로 | 입력·응답·권한 |
|---|---|
| GET /household/setup | `{available: boolean}`, no-store; 실제 전용 프록시와 허용된 Serve 사용자, 미등록 설치일 때만 true |
| POST /auth/web/setup | `display_name`, `password`, `device_label`; 허용된 사설망 사용자만, 201 WebLoginResponse+Secure 쿠키 |
| POST /auth/native/setup | 같은 입력; native transport, 201 NativeTokenResponse |
| POST /household/connection-code | 인증된 owner·최근 인증 또는 household.invite step-up; 201 `{code, expires_at}`, code는 8자리 |
| POST /auth/web/connect | `code`, `display_name`, `password`, `device_label`; 201 WebLoginResponse+Secure 쿠키 |
| POST /auth/native/connect | 같은 입력; native transport, 201 NativeTokenResponse |

첫 시작은 사용자/구성원 기록이 있으면 409 SETUP_COMPLETE, 사설망 사용자/프록시 검증 실패는
403 SETUP_UNAVAILABLE다. 기본 로그인 이름은 첫 사용자 owner, 연결한 배우자 partner다.
새 가계 이름은 우리 가계이며 기존 빈 가계는 보존한다. 계정/구성원/기기/세션은 함께 commit한다.
연결 코드 불일치·만료·사용·폐기는 400 INVALID_CONNECTION_CODE, 설치 단위 15분/5회 한도는
429 RATE_LIMITED다. Origin/native transport와 두 계정 제한을 서버에서 검사한다.
로그인·재인증·첫 시작·초대/연결 수락의 비밀번호 작업이 프로세스 한도(동시 2개)를 넘으면 429 `AUTH_BUSY`다.
RATE_LIMITED와 달리 실패 횟수를 늘리지 않으며 클라이언트는 같은 입력으로 잠시 뒤 다시 시도할 수 있다.
구체적인 신뢰 경계는 [모바일 직접 시작 ADR](adr/mobile-first-start.md)에 기록한다.

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

비밀번호 변경은 `POST /auth/password`에 `current_password`와 `new_password`(15–128자)를 보낸다.
다른 기기 모두 로그아웃은 `POST /devices/revoke-others`에 `password`를 보낸다. 두 경로는 웹(Origin·CSRF)과
native(전용 transport) 공용이다. 성공하면 200 `{"revoked_devices": n}`을 돌려주고, 현재 기기를 뺀 본인의
활성 기기를 모두 폐기한다. 폐기한 기기의 access·refresh·웹 세션은 기기 상태 검사에서 거부된다. 현재 세션은
유지하고 최근 인증 시각을 갱신한다. 오류는 `403 REAUTHENTICATION_FAILED`, `422 VALIDATION_ERROR`(현재와 같은 새 비밀번호·형식),
`429 RATE_LIMITED`·`AUTH_BUSY`(재인증과 같은 시도 제한), 401이다. If-Match·Idempotency-Key는 쓰지 않는다.
비밀번호 변경은 현재 비밀번호가 사실상의 버전이라 같은 요청을 다시 보내면 403이 되고, 다른 기기 로그아웃은
다시 보내도 같은 상태(0대 폐기)이며, 둘 다 본인 계정만 바꾼다. 등록한 패스키는 바꾸지 않는다.

기존 `POST /auth/invitations/accept`는 긴 일회성 초대로 계정을 만들고 로그인은 별도로 수행한다.
기존 API 계약은 유지하며 새 기본 시작/연결 경로만 등록과 로그인을 한 번에 완료한다.
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
등록 옵션의 `excludeCredentials`에는 본인의 **미폐기** 패스키만 넣는다. 폐기한 인증기는 같은 기기에서 다시 등록할 수 있다.

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
생성·수정·종료에서 보유 종료일은 서울 기준 오늘보다 늦을 수 없으며 `422 ASSET_END_IN_FUTURE`로 거부한다. 이미 저장된 미래 종료일은 그대로 읽고 다른 필드를 고칠 수 있으며, 종료일을 다른 날짜로 바꾸는 쓰기만 검사한다(비우기는 허용).
metadata에는 잔액·평가액·가전 가격·미래 연금액 필드를 받지 않는다. 실제 월 평가액은 후속 API다.
PATCH에서 생략한 필드는 유지한다. null로 지울 수 있는 필드는 `owner_member_id`, `ended_on`, `note`뿐이며
OpenAPI와 생성 TS 타입도 같은 선택 입력·null 규칙을 제공한다.

### 7) 금융계좌 (SB-011)

`POST /api/v1/accounts`, `GET /api/v1/accounts`, `GET/PATCH /api/v1/accounts/{account_id}`,
`POST /api/v1/accounts/{account_id}/reveal`, `DELETE /api/v1/accounts/{account_id}`를 구현했다.
생성 시 기존 금융 자산 `asset_id` 또는 새 자산 입력 `asset` 중 하나만 받는다. 자산 1건에 계좌는 1건이다.
생성·상세·목록·수정 응답에는 `masked_number`, `has_number`와 연결 자산을 제공하며 번호 원문·암호문은 없다.
번호는 생성/PATCH의 선택 입력이고 PATCH에서 명시적 null로 지울 수 있다. 키 설정이 없어도 번호 없는 metadata 조회·저장과 번호 제거는 가능하다.
전체 보기는 서버 재인증 또는 해당 계좌 UUID에 바인딩한 `account.reveal` 증명을 요구하며, 감사 commit 후 원문과 `display_for_seconds=30`을 반환한다.
계좌 PATCH에는 계좌 version의 `If-Match`를 사용한다. 자산 소유·종료 변경은 자산 API와 자산 version을 사용한다.
목록은 유형·소유자·active/closed/all 및 UUID cursor를 지원한다. 개설일과 자산 종료일을 양쪽 수정 경로에서 검증한다.
`DELETE /accounts/{account_id}`는 계좌 version의 `If-Match`만 받아 오등록 계좌와 연결 자산을 한 트랜잭션에서 함께 지우고 204를 반환한다. 카드 결제계좌·수입·고정 납부·월 기록·문서·대출 규칙 같은 참조가 하나라도 있으면 둘 다 남기고 `409 ACCOUNT_IN_USE`를 반환한다. 재전송은 지울 행이 없어 404가 되며 다른 행을 지우지 않는다. 계좌·자산 각각 `delete` 감사가 남는다.
금액·잔액은 받지 않으며 계좌의 종료일과 상태는 자산에서 파생한다. 웹 전용 번호 컴포넌트와 Android 네이티브 입력/전체 보기 화면을 연결했다. Android 실기기 보안 검증은 별도 출시 조건이다.

### 8) 월간 자산 확인·정정 (SB-012)

아래는 `/api/v1` 아래 실제 구현된 계약이다. 월은 `YYYY-MM`, 금액은 음수 없는 정수 원 문자열 또는 null이다.

| 메서드·경로 | 동작 |
|---|---|
| POST /asset-months/{month}/draft | `copy_previous`; 멱등키 필수, 새 작성본의 불변 참조 반환 |
| GET /asset-months/{month} | 현재 revision·전체 합계·확인 건수·범위 변경 상태와 최대 200행 cursor 조회. 값은 자산 → 부채, 이름, 자산 ID 순 |
| PATCH /asset-months/{month}/values/{asset_id} | `revision_id`, `value_id`, 입력 금액 또는 `unchanged`, 기준일·사유; 값 행 If-Match 필수 |
| POST /asset-months/{month}/sync-scope | `revision_id`, revision If-Match; 현재 자산 범위를 명시 반영하고 변경된 행을 미확인으로 돌림 |
| POST /asset-months/{month}/confirm | `revision_id`, revision If-Match·멱등키; 미확인 거부, 날짜/비교 범위 변화 확인 필요 |
| POST /asset-months/{month}/reopen | `revision_id`, 필수 `reason`, revision If-Match·멱등키; 이전 확정본을 보존한 새 revision |
| POST /asset-months/{month}/carry-previous | `revision_id`, revision If-Match·멱등키; 전월 최신 확정본의 금액을 손대지 않은 미입력 행(사유 없음·출처 없음·기준일 없음)에만 미확인 값으로 채움. 금액 입력 기준이 다르면 건너뜀. 전월 확정본이 없으면 `409 PREVIOUS_MONTH_UNCONFIRMED`, 확정한 월은 `409 MONTH_CONFIRMED`. 채울 행이 없으면 버전·감사 변화 없는 200 |
| GET /asset-months/{month}/revisions | 정정 사유·확정 시각을 포함한 revision 목록 |
| GET /asset-months/{month}/revisions/{revision_no} | 해당 변경본의 당시 범위·금액 조회 |

서울 기준 이번 달 이후의 월 작성본은 `422 MONTH_IN_FUTURE`로 거부한다. 검사는 멱등 실행 안에 있어 거부된 요청의 키는 그 달이 시작된 뒤 다시 쓸 수 있고, 이미 저장된 미래 월 작성본의 조회·수정은 막지 않는다. 금액 입력 기준을 바꿔 범위 반영으로 금액을 비운 행은 출처도 `manual`로 돌린다.
draft·confirm·reopen·carry-previous 응답은 `month`, `revision_id`, `revision_no`, 원래 `version`만 가진다. 이후 편집해도 같은 멱등키는
같은 참조를 반환한다. 값 PATCH는 수정 행·현재 revision version·전체 합계를 반환한다.
필수 버전·멱등 헤더와 성공 응답의 `ETag`·`Location`도 OpenAPI 및 생성 client에 명시한다.
월 GET의 `version`은 현재 revision version이고 값 행마다 별도 version이 있다. 부모 revision이 바뀌면
`REVISION_CONFLICT`, 범위 재생성으로 행 UUID가 바뀌면 `VALUE_CONFLICT`, 기존 행 버전 충돌이면 `VERSION_CONFLICT`로 409를 반환한다.
포함된 항목이 미입력이면 해당 합계는 null이다. 전월 복사값은 숫자를 보여도 `provisional=true`이고 확정할 수 없다.
확정할 때 `acknowledge_non_month_end_dates`, `acknowledge_scope_change`로 표시된 차이를 명시 확인한다.
웹과 Android의 월 입력·확정·정정·과거 조회 화면, 비교·추이·홈 요약을 같은 월 기록에 연결했다. Android는 네이티브 인증 adapter를 사용한다.

### 9) 자산 비교·추이 (SB-013)

두 endpoint는 현재 가계의 **현재 월 revision**을 읽는다. 정정 중인 달을 과거 확정본으로 자동 대체하지 않는다.
현재 자산의 이름·소유·지분을 과거 값에 결합하지 않으며 월 기록의 당시 snapshot을 사용한다.

| 메서드·경로 | 조회 |
|---|---|
| GET /asset-comparison?to=YYYY-MM&from=YYYY-MM | 전체/동일 범위 순자산 변화, 각 월 합계·revision·상태, 항목별 전후 값·기준일·범위 영향 |
| GET /asset-trends?from=YYYY-MM&to=YYYY-MM | 양 끝을 포함한 최대 120개월 연속 축, 기록/금액 상태, 관찰값과 확정 차트값 |

비교의 `from`은 생략하면 직전 월이다. 두 API는 `asset_id`, `kind`, `category`, `ownership_kind`,
`owner_member_id` 필터를 지원한다. 필터는 각 월 당시 값에 적용한다. 다른 가계의 자산/소유자 ID는 404다.
공동 소유와 개인 owner ID를 함께 지정하면 422다. 비교는 UUID cursor, limit 1~200을 지원하며
페이지마다 전체 필터 합계와 양쪽 revision 참조를 반환한다. 조회 도중 revision이 바뀐 페이지를 UI에서 섞지 않는다.
항목은 자산 → 부채, 이름, 자산 ID 순이며 이번 달 값이 있으면 그 값, 없으면 비교 달 값의 분류·이름을 쓴다.

비교 `state`는 available/no_previous_month/current_missing/unconfirmed다. 한쪽 기록이 없거나
미확정이면 증감은 null이며, 미입력을 0원으로 바꾸지 않는다. 순자산 합계에는 included 항목만 넣는다.
같은 asset ID·같은 가계 지분인 공통 범위를 별도로 계산한다. 추가/제외/지분 변경 ID와 당시 전후
`MonthValueResponse`를 함께 제공한다. 항목 `amount_delta_krw`는 보유금액의 변화이고,
`net_assets_effect_krw`는 부채 부호와 범위 추가/제외를 반영한 순자산 영향이다.
없는 항목의 전후 값은 null이며 신규 취득/저축으로 추정하지 않는다.

`change_percent`는 두 월이 확정되고 이전 순자산이 양수일 때 Decimal로 계산해 소수 둘째 자리 HALF_UP
문자열로 반환한다. 0원/음수 기준은 null과 zero_previous_total/negative_previous_total 사유를 반환한다.
원 단위 증감은 유지한다. 증감률은 투자 수익률이나 저축률이 아니다.
각 월의 월말 아닌 기준일·미입력 기준일 ID와 혼합 날짜 여부도 반환한다.
일반 조회의 날짜 진단은 필터에 맞는 합계 포함 항목만 대상으로 한다. `asset_id`를 명시하면
모든 필터에 맞는 해당 항목의 합계 제외 관측값도 날짜 진단에 포함한다. 금액 합계에는 계속 제외한다.
날짜 진단은 작성/정정/확정 상태와 무관하게 제공하며, 서로 다른 월의 기준일을 한 달의 혼합 날짜로 묶지 않는다.

추이는 missing/draft/reopened/confirmed 기록 상태와 missing_month/missing_item/outside_filter/
missing_value/unconfirmed/verified 금액 상태를 구분한다. `observed_amount_krw`는 현재 관찰값,
`confirmed_amount_krw`는 확정·검증된 값만 담는다. 차트는 null 구간을 연결하지 않는다.
전체 추이는 순자산, asset_id 추이는 해당 항목의 가계 보유금액이다. 명시적으로 선택한 합계 제외 항목은
참고 금액을 조회할 수 있지만 가계 합계에는 더하지 않는다. 포함 여부도 함께 반환한다.
실제 월 기록에서 필터에 맞는 included 항목이 0개인 합계 0과, 월 기록 자체가 없는 null을 구분한다.

읽기는 기존 household scope 잠금을 사용해 현재 revision 선택과 행/합계를 일관되게 조회한다.
새 migration이나 금액 저장 필드는 추가하지 않는다. 성공·오류 모두 기존 no-store 정책을 적용한다.

### 9) 수동 수입과 반환 (SB-014)

`GET/POST /income`, `GET /income/summary`, `GET /income/duplicates`, `POST /income/convert`,
`GET/PATCH /income/{id}`, `GET /income/{id}/history`, `POST /income/{id}/void`, `POST /income/{id}/returns`를 제공한다.
모든 mutation은 `Idempotency-Key`, 정정·무효·반환은 원본 `If-Match`도 필수다.
각 변경본을 불변 이력으로 저장하므로 재전송은 이후 정정과 무관하게 최초 응답의 버전을 돌려준다.
수입은 급여·상여·기타수입, 반환은 원본 연결이 필요하다. 보험금 입금·반환은 공통 원본에서 읽기 전용으로 집계하며 수입 API에서 복제 생성하지 않는다.
금액은 양수 정수 원 문자열이다. day는 실제 날짜를 요구하고 month는 날짜를 비워 둔다. 실제 날짜는 서울 오늘을 넘을 수 없지만 귀속월은 입금월과 달라도 된다.
같은 월·구성원·종류의 일별/월합계 혼용은 후보 조회와 명시 확인을 요구한다. 정밀도 전환은 해당 범위의 모든 활성 원본과 버전을 받아 합계 보존·원본 무효·대체 기록 생성을 원자적으로 수행한다.
반환 합계는 원본 이하이며, 반환일은 원본 날짜보다 빠를 수 없다(둘 다 일 단위면 실제 날짜, 하나라도 월합계면 귀속 월을 비교하고, 위반은 422 `INVALID_REVERSAL`이다). 환불·보험금 반환도 같은 규칙을 생성과 정정에 적용한다. 활성 반환이 있으면 원본 정정·무효·전환을 막는다. 정정·무효·반환·전환은 사유를 남긴다.
계좌·구성원은 가계 FK와 API 권한을 함께 검증한다. 규칙(계획)에는 사용 중인 계좌/카드·부채만 연결한다. 실제 금전 기록(수입·반환·고정 납부·의료비·환불·보험금·반환)은 기록 날짜(일 단위는 실제 날짜, 월합계는 그 달 1일)가 계좌 자산·카드 종료일 이하이면 종료된 수단도 연결할 수 있고, 정정은 원래 연결을 유지할 수 있다. 계좌 개설일·카드 시작일이 있으면 그보다 앞선 날짜(월합계는 월 단위 비교, 시작일 당일은 허용)는 422 `ACCOUNT_UNAVAILABLE`/`CARD_UNAVAILABLE`이며, 시작일 앞에 이미 있던 기록은 그 날짜 그대로 정정할 수 있지만 정정으로 날짜를 시작일 앞으로 옮길 수는 없다. 수입·반환 입력은 자산 월 스냅샷이나 계좌 잔액을 자동으로 변경하지 않는다.
`editable`/`voidable`은 현재 상세·목록·중복 후보 조회에서 활성 반환까지 반영한 작업 가능 표시다. 반환을 모두 무효화하면 다시 허용된다. 변경 응답(재전송 포함)·전환 결과·과거 이력은 불변 영수증이므로 두 값이 항상 false이며, 작업 전 현재 상세를 조회한다. 현재 조회는 가계 잠금 안에서 원본과 반환 상태를 읽고 목록의 반환 상태는 일괄 조회한다.

목록·이력은 cursor를 지원하고 요약은 근로·부수입과 실제 보험금 유입/반환을 분리한다. 웹/Android 수입 화면은 생성 계약의 10개 동작에 연결되며 변경 후 현재 상세를 다시 조회한다. [수입·고정 납부·카드 UI 검증 기록](testing/cashflow-client.md)을 따른다.

### 10) 카드 일반정보와 결제수단 (SB-017)

`GET/POST /cards`, `GET/PATCH/DELETE /cards/{id}`, `POST /cards/{id}/archive`를 제공한다.
일반 요청·응답에는 소유자·카드사·상품명·별칭·신용/체크·마지막 4자리·결제일·결제계좌·사용 시작/종료일만 있다.
PAN·유효기간·CVC·암호문 필드는 일반 입력에서 거부한다. 카드 전체 정보 보관함과 Android 로컬 CVC는 별도 보안 경로에서 구현한다.
수정·종료·삭제는 `If-Match` 필수다. 소유자는 가계 구성원이며 같은 가계의 두 계정이 모두 관리할 수 있다.
다른 가계의 소유자·계좌·카드 ID는 404이며 DB 복합 FK도 거부한다. 참조 없는 오등록은 삭제할 수 있고 사용 이력이 있으면 `CARD_IN_USE`로 거부한다.
종료는 과거 금전 기록과 결제계좌 연결을 보존한다. 종료된 계좌를 새 활성 카드에 연결하거나 종료 계좌를 유지한 채 카드를 재활성화할 수 없다.
이미 연결된 계좌가 종료되면 `settlement_account_status=closed`로 안내하며 자동 연결 해제/대체는 하지 않는다.
목록은 소유자·카드유형·결제계좌·활성/종료와 UUID cursor를 지원한다. 카드 결제일은 전체 명세서나 월 출금 합계가 아니다.
공통 cash 원본/이력에는 실제 카드 FK가 추가됐으며 계좌와 카드를 동시에 연결할 수 없다. 수입/보험금 유입·반환은 카드 결제수단을 받지 않는다.
종료된 카드도 종료일 이하 날짜의 실제 금전 기록과 원래 연결을 유지하는 정정에는 연결할 수 있다(§11).

### 11) 반복 규칙·예상 회차·실제 납부 (SB-015/016)

`/recurring-rules`의 생성·목록·상세·새 적용일 변경·종료, `/obligations/generate`, 월별 회차 목록/요약/상세/이력,
회차 날짜 변경·건너뛰기/복원·수동 완료/재개, 실제 납부 등록·목록·무효 API를 제공한다.
정기 규칙/회차 mutation은 멱등키와 해당 자원의 If-Match를 사용하고, 납부 무효는 원본 cash version을 사용한다.
규칙·회차 변경 응답은 최초 `id`/`version`의 불변 참조다. 납부 응답은 해당 cash 변경본을 포함하여 재전송으로 최신 상태가 섞이지 않는다.
월/연/N일 주기는 원래 anchor에서 계산하고 짧은 달은 그 달만 말일로 보정한다. 주말·공휴일을 자동 이동하지 않는다.
생성 기간은 명시적으로 최대 366일이며 같은 규칙/명목일은 중복 생성하지 않는다. 실패한 생성은 rollback하고 같은 키로 재시도할 수 있다.
규칙 변경은 새 적용일의 기간 이력을 만들고 이미 요청한 생성 기간의 미래 미납 회차를 갱신한다. 과거·실납부·수동 예외 회차를 보존한다. 최초 등록 또는 종료 API로 미래 종료일을 정한 규칙도 마지막 적용 시작일 이후·오늘 이후(오늘 포함)·원래 종료일 이전에는 금액·결제수단·주기를 변경할 수 있다. 새 변경본은 기존 종료일을 유지하며 종료 사유도 보존한다. 종료일 연장이나 재개방은 지원하지 않는다.
아직 시작하지 않은 예정 변경이 있으면 그 시작일과 같거나 앞선 날짜의 변경·종료가 같은 요청에서 그 예정 변경을 철회(`revoked_at`)한다. 기준 날짜는 오늘 이전에 시작한 마지막 버전(없으면 첫 버전)의 시작일보다 뒤여야 한다. 철회한 버전은 규칙 응답과 결제수단 연결 조회에서 빠지고, 이미 시작한 버전과 가장 이른 활성 버전은 철회하지 않는다. 철회할 버전의 회차에 실제 납부나 수동 예외가 있으면 `OBLIGATION_HAS_PAYMENT` 409다. 철회는 규칙의 기존 update/archive 감사에 `revoked_at` 변경 필드로 남는다.
`manual_override`는 건너뛰기·수동 완료·예정일 변경이 실제로 남아 있을 때만 true다(DB CHECK). 되돌리거나 납부를 무효로 하면 이후 규칙 변경·종료를 다시 따른다.
회차 이력의 `action`은 `ObligationHistoryAction` 9개 값(create, regenerate, reschedule, skip, unskip, complete, reopen, settle, void_settlement) 중 하나다.
최초 등록에는 종료일/사유 한 쌍으로 과거 종료 계약도 기록할 수 있다. 기존 과거 규칙을 뒤늦게 덮어쓰지는 않는다.
실제 납부액은 분할 기록을 합산하며 예정액과 더하지 않는다. 미확인 예정액 null과 명시적 0은 다르며 0원 cash 이벤트는 만들지 않는다.
대출은 실제 원금+이자 합계를 검사하고 이자만 소비로, 연금 등 자산 이동은 소비 0으로 구분한다. 수동 납부·취소로 자산 스냅샷을 바꾸지 않는다.
외화 통화/금액은 참고 쌍으로만 기록하며 KRW 예정액·실제 납부액과 자동 환산하지 않는다.
규칙(계획)에는 사용 중인 계좌/카드·부채만 연결한다. 실제 금전 기록(수입·반환·고정 납부·의료비·환불·보험금·반환)은 기록 날짜(일 단위는 실제 날짜, 월합계는 그 달 1일)가 계좌 자산·카드 종료일 이하이면 종료된 수단도 연결할 수 있고, 정정은 원래 연결을 유지할 수 있다. 계좌 개설일·카드 시작일이 있으면 그보다 앞선 날짜(월합계는 월 단위 비교, 시작일 당일은 허용)는 422 `ACCOUNT_UNAVAILABLE`/`CARD_UNAVAILABLE`이며, 시작일 앞에 이미 있던 기록은 그 날짜 그대로 정정할 수 있지만 정정으로 날짜를 시작일 앞으로 옮길 수는 없다. 카드 승인 예정일과 계좌의 실제 카드대금 출금을 같은 일정으로 표시하지 않는다.

## 1. 공통 규약

모든 가계 자원은 인증 사용자 membership에서 가계를 결정한다.
클라이언트의 household_id를 신뢰하지 않는다. 같은 가계의 다른 구성원 소유 자산도 공동 정책에 따라 읽고 수정한다.
PATCH에는 `If-Match: "7"`처럼 version을 보내며 최신 버전이 아니면 409.
원본 금전 기록/지급/교체/회차 생성 POST에는 `Idempotency-Key`가 필요하다.
같은 key+payload는 같은 결과를 반환하고 다른 payload는 409.
민감 API는 `Cache-Control: no-store`, 오류 응답에 입력 원문·SQL·토큰을 넣지 않는다.
목록은 cursor pagination, 기본 50개/최대 200개. 날짜/금액/문자열 필터를 명시적으로 whitelist한다.

목록 순서는 업무 기준이며 id 순서가 아니다. `cursor`는 직전 페이지 마지막 항목의 UUID다. 서버는 그 행의 정렬 값을 다시 읽어 다음 페이지를 잇고, 같은 값은 같은 방향의 id로 나눈다. cursor 행이 없거나 다른 가계의 것이면 404 `NOT_FOUND`다. 기기·패스키는 본인 행만 cursor가 된다. 페이지 사이에 정렬 값이 바뀐 행(사건 시작일, 회차 예정일)은 중복되거나 빠질 수 있으므로 클라이언트는 id로 중복을 거른다.

| 목록 | 순서 |
|---|---|
| 가전·소모품·기기 연결·오늘 소모품, 문서·문서 연결, 보험 계약·납부 연결, 청구, 자산·계좌·카드, 기기·패스키, 고정 납부 규칙 | 등록 최신순 |
| 보장 | 등록 순서(계약서 순서대로 입력) |
| 사건 | 시작일 최신순 → 등록 최신순 |
| 재고 기록 / 교체 이력 | 발생일 / 교체일 최신순 → 등록 최신순 |
| 의료비·환불·보험금 수령·반환, 고정 납부 실제 납부 | 실제 날짜 최신순 → 등록 최신순 |
| 수입(한 달) | 실제 날짜 최신순, 날짜 없는 월합계는 마지막 → 등록 최신순 |
| 예정 회차 | 예정일 → 등록 순 |
| 결제 연결: 규칙 / 회차 / 카드 | 적용 시작일 → 등록 순 / 예정일 → 등록 순 / 등록 최신순 |
| 월 기록 값, 비교 항목 | 자산 → 부채, 이름, 자산 ID |
| 이력·감사·진료 노드·보관함 공유 | 기존 순서 유지 |

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
| 비밀번호 | POST /auth/password | 현재·새 비밀번호, 다른 기기 모두 폐기, 같은 트랜잭션 감사 |
| 초대·기기 | POST /household/invitations, GET /devices, DELETE /devices/{id}, POST /devices/revoke-others | 최근 로그인 또는 X-Step-Up-Token, 기기 세션 폐기. 다른 기기 모두 로그아웃은 비밀번호 확인 |
| 홈 | GET /asset-comparison?to=YYYY-MM&limit=1, GET /asset-trends?from=...&to=..., GET /homecare/status | 별도 dashboard API 없음. 자산은 선택 월 비교 또는 최근 24개월에서 연속 확정 두 달의 비교, 소모품은 서버 오늘 |
| 자산 | GET/POST /assets, GET/PATCH/DELETE /assets/{id} | 종료/삭제 의미 구분 |
| 계좌 | GET/POST /accounts, GET/PATCH/DELETE /accounts/{id} | 자산 원본과 1:1, 참조 없을 때만 삭제(`ACCOUNT_IN_USE`) |
| 계좌번호 | POST /accounts/{id}/reveal | 서버 재인증, no-store, 반환 audit |
| 월 기록 | POST /asset-months/{month}/draft | 전월확정 복사; 반복 호출 중복 없음 |
| 월 기록 | GET /asset-months/{month}, PATCH /asset-months/{month}/values/{assetId} | 행 상태·기준일·version |
| 월 확정 | POST /asset-months/{month}/confirm, /reopen | 미확인 거부, 새 revision |
| 월 기록 | POST /asset-months/{month}/carry-previous | 손대지 않은 미입력 행만 전월 확정값으로 채움(`PREVIOUS_MONTH_UNCONFIRMED`) |
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

아래는 초기 설계의 합성 예시이며 구현된 API가 아니다. 홈은 위 표의 비교·추이·소모품 API를 각각 호출한다.

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

SB-023은 PDF/JPEG/PNG 파일을 파일당 **20MiB(20,971,520바이트)**까지 지원하며 PDF는 최대 **5쪽**이다.
JPEG는 웹·Android 클라이언트가 EXIF 방향을 적용하고 긴 변을 3,072px 이하로 줄이며 위치 등 사진 정보와
꼬리 데이터를 뺀 사본을 만들어 그 bytes로 해시·업로드한다. 서버는 받은 bytes를 바꾸지 않고 그대로 검사·보관한다.
`POST /documents`에 파일명·MIME·실제 크기·SHA-256·typed target·`contains_no_card_data: true`를
제출하면 pending 문서와 최초 연결을 같은 트랜잭션으로 만든다. 생성은 Idempotency-Key를 요구하고
201 Location 및 불변 `{id, version}` 참조를 반환한다. 파일명은 경로·제어문자·방향 제어문자를
허용하지 않으며 확장자도 선언 MIME과 일치해야 한다. 카드 사진·번호·CVC 첨부는 지원하지 않는다.

`PUT /documents/{id}/content`는 `application/octet-stream` 원본과 문서 If-Match/Idempotency-Key를
받는다. 크기·해시·실제 형식·악성 내용·카드 정보 검사를 모두 통과한 원본만 암호화해 ready로 전환한다.
본문을 읽기 전부터 프로세스당 업로드 한 개로 제한하며 초과는 503 `DOCUMENT_UPLOAD_BUSY`다.
HTTP 취소 후에도 시작한 worker가 끝날 때까지 처리 슬롯을 유지한다. 본문 수신은 120초로 제한하며 408, 크기 초과는 413, 잘못된 파일은 422, 검사기/키/저장소 장애는
503이다. 422에는 지원하지 않는 사진 정보·꼬리 데이터의 `DOCUMENT_IMAGE_UNSUPPORTED`와 쪽수·픽셀·검사 시간
초과의 `DOCUMENT_TOO_COMPLEX`가 포함된다. 검사 중에는 가계·세션 DB 잠금을 유지하지 않고 완료 후 현재 세션·기기·연결·버전을 다시 검증한다.
검사한 내용을 재전송하면 처음의 성공 참조를 반환하며 삭제·연결 해제된 내용을 복원하지 않는다.

| 동작 | 경로·버전 기준 |
|---|---|
| 목록/상세 | GET /documents, GET /documents/{id}; 목록은 target_kind와 target_id를 함께 지정 가능 |
| 업로드한 파일 다운로드 | GET /documents/{id}/download; 현재 가계 권한과 ready 상태 확인 후 인증 응답으로 전달 |
| 문서 삭제 | POST /documents/{id}/delete; 사유·문서 If-Match·멱등키, 연결도 함께 종료 |
| 연결 추가 | POST /document-links; document_id/target·문서 If-Match·멱등키 |
| 연결 이력 | GET /documents/{id}/links; 활성·종료 이력을 모두 반환 |
| 연결 종료 | POST /document-links/{id}/end; 사유·연결 If-Match·멱등키, 문서 버전도 증가 |

target.kind는 policy/case/medical_node/expense/claim/appliance/asset 중 하나이며 같은 가계의
실제 대상을 검증한다. 카드 대상은 없다. 목록은 UUID cursor와 limit 1~200을 사용한다.
응답에는 저장소 경로·암호화 키·nonce가 없으며 다운로드는 no-store/nosniff/CSP sandbox와
attachment 헤더를 사용한다. 공개 URL이나 장기 유효 링크를 만들지 않는다.
pending 유효기간은 24시간이다. 연결이 모두 종료된 ready 문서는 사용자의 명시적 삭제 전까지 보존한다.
업로드 저장 전에 가계·전체 byte/count 한도를 영속 예약하며 한도 초과는
413 `DOCUMENT_STORAGE_QUOTA_EXCEEDED`, 디스크 여유 부족은 503 `DOCUMENT_STORAGE_CAPACITY_UNAVAILABLE`다.
예약에는 암호문 tag·실패 업로드·삭제 후 유예 파일도 포함하며 물리 정리 확인 뒤 용량을 반환한다.
정리 명령·기본 한도·설정·검증 범위는 [첨부 서버 검증](testing/documents-server.md)을 따른다.
7개 부모 상세의 공유 패널·원본 전송·응답 유실 재시도·Android 보호 화면 연결은 [첨부 UI 검증](testing/documents-client.md)을 따른다.


기존 금융 자산에 새 계좌를 연결할 때는 사용 중인 자산만 허용한다. 자산 선택 뒤 다른 기기에서 종료해도 저장 시 잠금 안에서 다시 확인하며 422 `ASSET_UNAVAILABLE`을 반환한다. 기존에 연결된 계좌의 종료 이력은 유지한다.

### SB-018 결제수단 연결 조회와 종료 확인

`GET /api/v1/cards/{resource_id}/payment-links`와 `GET /api/v1/accounts/{resource_id}/payment-links`는 현재·미래 규칙 버전, 미납/부분 납부 회차와 연결 카드를 각각 count/cursor 페이지로 반환한다. `as_of_date`는 기본 서울 오늘이며 종료 화면에서는 선택한 종료일을 전달한다. 카드 승인 계획과 계좌 직접 납부 계획을 구분하고, 응답은 `registered_recurring_only` 및 `account_withdrawal_total_available=false`로 전체 카드대금 출금액을 알 수 없음을 명시한다. 세 목록은 위 순서로 나뉘며 digest도 이 순서의 전체 목록으로 계산한다.

카드 PATCH/archive 및 계좌에 연결된 자산 PATCH/archive에서 새 종료일을 저장할 때 서버는 가계 잠금 안에서 연결을 다시 읽는다. 영향이 있으면 `closure_ack=true`와 조회에서 받은 `usage_digest`가 필요하며, 누락은 409 `PAYMENT_LINK_CONFIRMATION_REQUIRED`, 조회 이후 내용·버전·종료일 변경은 409 `PAYMENT_LINKS_CHANGED`다. digest는 페이지 밖의 연결까지 포함하며 권한 증명이 아니다. 종료일을 바꾸면 다시 조회한다. 확인 필드만 보낸 PATCH는 거부한다. 확인 필드는 DB·감사 변경 필드 목록에 저장하지 않는다.

기존에 종료된 항목의 일반 메타데이터 수정에는 다시 확인을 요구하지 않는다. 종료일을 다른 날짜로 바꾸면 다시 확인한다. 과거 규칙·회차·현금 기록은 자동 이동하거나 삭제하지 않으며, 결제수단 교체는 사용자가 규칙 변경 또는 카드 납부계좌 수정으로 명시한다.

웹/Android 화면은 종료일 기준 모든 페이지를 읽고 같은 digest·자원 버전·총건수를 확인한 뒤 명시 확인을 요구한다. 연결 변경409에서는 작성한 종료일을 유지하고 내역을 다시 읽으며 이전 확인을 재사용하지 않는다. Android 네이티브 경로도 확인 여부와 digest를 함께 전달한다.

### SB-019/SB-020 보험계약·독립 사건·진료 트리

보험계약은 `/api/v1/insurance/policies`의 생성/목록과 `/{policy_id}`의 상세/PATCH로 관리한다. 계약·보장·납입 시작/종료일을 각각 저장하고, 보장은 `/{policy_id}/coverages` 목록/생성 및 `/{coverage_id}` PATCH로 관리한다. 금액 미입력과 0원을 구분한다. 정책 상태는 active/ended/lapsed이며 과거 계약은 보존한다.

`/{policy_id}/premium-links` 목록/생성과 `/{link_id}` PATCH(active)로 기존 고정비 규칙에 연결한다. 한 계약은 여러 규칙을 가질 수 있고 한 규칙은 한 계약에 귀속한다. 연결 해제는 이력을 남기며 규칙·납부를 삭제하거나 금액을 복제하지 않는다. 연결 응답의 보험료·주기·결제수단은 현재와 과거의 동일한 recurring rule version에서 읽으며 금액 수정도 기존 고정비 규칙 변경 API를 사용한다. 납부 누계로 자산을 자동 생성하지 않는다. 확인된 평가액용 금융 자산을 선택해 연결할 수 있다.

증권번호는 create/PATCH의 `policy_number`로 저장하되 일반 응답은 `masked_number`/`has_number`만 반환한다. `/policies/{policy_id}/reveal` POST는 현재 세션의 최근 로그인 검증·가계 권한·감사와 no-store를 거쳐 30초 표시용 값을 반환한다. 서버 필드 키 파일이 없어도 번호 없는 메타데이터와 번호 삭제는 사용할 수 있다. Android 원문 입력/표시는 네이티브 보호 화면으로 연결했으며 JS 메타데이터 bridge에 번호를 포함하지 않는다. 웹은 별도의 일시 입력·30초 표시 화면을 사용한다.

사건 `/insurance/cases`와 `/{case_id}`는 계약에 종속되지 않는다. 환자·실제 날짜·치료 상태(ongoing/ended)와 정산 상태(open/settled)를 독립 관리한다. PATCH에는 If-Match와 사유가 필요하며 변경 전후 내용은 삭제 불가능한 typed 이력으로 보존한다. `/{case_id}/history`는 version cursor를 제공한다. 목록에는 진단명/코드를 포함하지 않는다. 치료 종료에는 종료일이 필요하며 재개방 시 종료일을 비운다.

진료 노드의 목록/생성은 `/{case_id}/nodes`, 상세/수정/삭제는 `/{case_id}/nodes/{node_id}`다. 외래·입원·수술·처방·약국·재진·그룹을 표현하고 노드 자체에 금액을 저장하지 않는다. 동일 사건 부모만 허용하며 가계 잠금 안에서 전체 부모 관계를 검사해 순환과 동시 교차 이동을 막는다. 자식/비용/문서가 연결된 노드 삭제는 409다. 상세 갱신·삭제에는 해당 자원의 If-Match가 필요하다. 목록은 깊이 우선으로 부모 바로 뒤에 그 하위 항목을 읽고 같은 부모의 항목은 sort_order·start_on(날짜 없음은 뒤)·created_at·UUID 오름차순으로 정렬한다. UUID cursor는 해당 사건 노드의 현재 트리 위치를 가리키며 다른 사건/가계의 cursor는 404다. 트리 수정 후에는 첫 페이지부터 다시 읽는다.

### SB-021/SB-022 의료비·청구·실제 보험금

다음 경로는 `/api/v1/insurance` 아래에 있으며 생성 OpenAPI가 요청·응답의 기준이다.

| 경로 | 동작 |
|---|---|
| `/medical-expenses` | GET 목록, POST 실제 의료비 등록 |
| `/medical-expenses/{id}` | GET 상세; `/correct`, `/void` POST; `/history` GET |
| `/medical-expenses/{id}/refunds` | GET 환불 목록, POST 실제 환불 |
| `/medical-refunds/{id}` | GET 상세; `/correct`, `/void` POST; `/history` GET |
| `/claims` 및 `/claims/{id}` | GET/POST 목록·등록(목록은 `case_id`·`policy_id`·`claim_state`·`expense_id` 조건), GET/PATCH 상세·사유 있는 정정 |
| `/claims/{id}/history` | GET 당시 비용 연결까지 포함한 청구 이력 |
| `/payouts` 및 `/payouts/{id}` | GET/POST 목록·실제 수령, GET 상세; `/correct`, `/void` POST; `/history` GET |
| `/payouts/{id}/returns` | GET 반환 목록, POST 실제 반환 |
| `/returns/{id}` | GET 상세; `/correct`, `/void` POST; `/history` GET |
| `/payout-allocations/{id}` | GET 상세, PATCH 사유 있는 청구·계약 연결 변경; `/history` GET |
| `/cases/{id}/summary` | GET 원본 기준 사건 의료비·실제 수령/반환·순부담 |

사건 목록(`GET /insurance/cases`)의 각 행은 `net_burden_krw`(부호 있는 원 문자열)로 사건 요약과 같은 순현금부담을 함께 준다. 페이지 크기와 무관하게 같은 수의 조회로 계산한다.
| `/cases/{case_id}/nodes/{node_id}/summary` | GET 하위 노드를 포함한 의료비·환불 합계 |

기존에 종료된 항목의 일반 메타데이터 수정에는 다시 확인을 요구하지 않는다. 종료일을 다른 날짜로 바꾸면 다시 확인한다. 과거 규칙·회차·현금 기록은 자동 이동하거나 삭제하지 않으며, 결제수단 교체는 사용자가 규칙 변경 또는 카드 납부계좌 수정으로 명시한다.
기존 금융 자산에 새 계좌를 연결할 때는 사용 중인 자산만 허용한다. 자산 선택 뒤 다른 기기에서 종료해도 저장 시 잠금 안에서 다시 확인하며 422 `ASSET_UNAVAILABLE`을 반환한다. 기존에 연결된 계좌의 종료 이력은 유지한다.
의료비는 같은 사건의 진료/약국 노드에 실제 지출 하나를 연결한다. 처방 노드에는 비용을 입력할 수 없고 비용 이력이 있는 노드를 처방으로 바꾸는 것도 거부한다. 영수증 상세를 입력하면 상세 합계와 실제 지출이 같아야 한다. 총진료비·공적 부담 참고액은 실제 지출과 구별하며 상세 행을 별도 지출로 합산하지 않는다.

청구는 사건 하나·계약 하나와 같은 사건의 비용 여러 개를 연결한다. 같은 비용을 여러 계약에 청구해도 의료비 원본은 하나다. 해지·만기·실효된 계약에도 새 청구와 청구 없는 직접 배분을 기록할 수 있다([ADR 0009](adr/late-insurance-records.md)). 다른 가계의 계약은 404다. `GET /claims?expense_id=`는 그 의료비를 현재 근거로 인용한 청구만 돌려주며 다른 가계의 의료비 ID는 404다. 청구 응답의 `received_krw`·`returned_krw`·`net_received_krw`는 이 청구에 연결된 활성 배분과 그 활성 반환만 합한 실제 금액이며 `net_received_krw = received_krw - returned_krw`다. 요청액·결정액·접수/심사 상태는 실제 수령이 아니다. 청구에 연결된 비용의 정정/무효는 현재 청구 근거를 사유와 함께 먼저 정정한 뒤 수행하며 과거 청구 근거는 보존한다.

실제 보험금은 cash 원본 하나와 사건별 배분 여러 개를 같은 트랜잭션으로 저장한다. 배분 합계는 원본 수령액과 정확히 같아야 한다. 청구 없이 직접 수령을 등록할 수 있으며 나중에 청구를 연결해도 새 입금이 생기지 않는다. 기존 청구에는 계약 종료 뒤 늦게 받은 보험금도 기록할 수 있다. 사건·배분 금액·보장 성격을 잘못 입력했다면 원본 지급의 무효와 대체 지급 생성을 원자적으로 수행한다. 배분 PATCH는 계약·청구 연결만 바꾸며 typed 이력을 남긴다.

환불과 반환은 원본을 참조하는 별도 실제 금전 기록이다. 환불·반환을 정정하면 금액·날짜·결제 연결만 바뀌고 처음 기록한 사유는 그대로 남는다. 요청의 `reason`은 정정 사유로 현금 이력에 기록된다. 사유 자체가 틀렸다면 무효 후 새로 기록한다. 환불은 원래 의료비 한도, 보험금 반환은 원래 배분 한도를 초과할 수 없다. 활성 환불/반환이 남아 있으면 원본 정정/무효를 거부한다. 정정/무효 이력은 삭제하지 않는다. 사건 순부담은 음수가 될 수 있으며 실손·정액·기타 실제 수령을 구분한다. 노드별 집계에 사건 보험금을 임의 배분하지 않는다.

금전 생성·정정·무효·환불·반환·배분 연결 변경은 Idempotency-Key를 요구한다. 기존 대상에 적용하는 명령은 If-Match도 요구하며 환불/반환 생성에는 부모 의료비/지급의 버전을 사용한다. 결과는 변경 당시 `{id, version}` 참조이고 재전송해도 변하지 않는다. 최신 상태와 가능한 후속 동작은 GET으로 다시 조회한다. 청구 메타데이터 수정은 If-Match와 사유를 요구한다. 청구 생성(`POST /claims`)은 선택적 Idempotency-Key를 받는다. 키를 보내면 같은 키·같은 내용의 재전송은 새 청구를 만들지 않고 처음 저장한 버전의 청구 응답(같은 ETag·Location)을 돌려준다. 그 사이 청구가 수정됐어도 생성 당시 버전으로 응답하고, 수령·반환 합계만 현재 값이다. 같은 키에 다른 내용은 409 `IDEMPOTENCY_CONFLICT`다. 키가 없는 이전 클라이언트는 전처럼 요청마다 청구를 만든다. 웹과 Android는 같은 미저장 청구의 재시도에 같은 키를 보낸다. 소득 화면은 실제 보험금 원본을 읽기 전용으로 투영하며 계좌 잔액이나 자산 스냅샷을 자동 변경하지 않는다.

보험 계약·사건·금전 화면의 생성 client/Android adapter 연결과 실제 HTTPS 검증은 [보험 UI 검증 기록](testing/insurance-client.md)을 따른다.

### SB-024~SB-027 가전·공용 재고·교체

`/api/v1/appliances`와 `/consumables`는 POST/목록 GET, `/{id}`는 GET/PATCH를 제공한다.
목록의 `status`는 active/ended/all이며 기본 active다. 가전 구매일·보증기한·구매액 미입력과 0원은 구분한다.
금액은 십진 문자열, 수량은 0~1,000,000 범위의 엄격한 정수다. 가전 구매액과 재고 입고액은 자산·현금 기록을 자동 생성하지 않는다.
수정은 `If-Match`, 상태 종료는 `ended_on` PATCH를 사용하며 이력을 실제 삭제하지 않는다.
참조 없는 오등록은 DELETE /appliances/{id}, /consumables/{id}, /appliance-consumables/{id}로
삭제한다. 해당 metadata If-Match가 필요하고 성공은 204다. 연결·재고·취소된 교체 이력이나 문서
참조가 있으면 409 `APPLIANCE_IN_USE`/`CONSUMABLE_IN_USE`/`APPLIANCE_CONSUMABLE_IN_USE`이며
사용 종료 또는 연결 비활성화를 사용한다. 다른 가계 ID는 404다.

`/appliance-consumables`의 POST/GET와 `/{link_id}` GET/PATCH가 기기별 호환·주기·교체 수량·다음 확인일 override를 관리한다.
동일 가계의 가전/소모품 조합은 하나이며 중지한 연결은 같은 행을 다시 활성화한다. 소모품 규격이 있으면 가계 안에서 유일하다.
구매일·입고일을 교체일로 추정하지 않으며, 교체 이력이 없으면 다음 확인일은 unknown이다.

`/consumables/{id}/stock-movements` POST/GET 및 `/{movement_id}` GET, `/{movement_id}/cancel` POST가
입고(receipt), 반품 입고/출고(return_in/return_out), 사유 있는 조정(adjustment)과 원본의 완전 취소를 제공한다.
`/appliance-consumables/{link_id}/replacements` POST/GET 및 `/{replacement_id}` GET, `/{replacement_id}/cancel` POST가 교체·취소를 제공한다.
재고 쓰기는 `If-Match: "현재 소모품 version"`과 `Idempotency-Key`를 함께 요구한다. 교체에는 현재 `link_version`과
`clear_next_check_override` 선택이 추가로 필요하다. 교체와 재고 감소는 같은 트랜잭션이며, 부족하면 409 `INSUFFICIENT_STOCK`이다.
응답은 원본 실행 당시 `stock_version`, movement ID와 선택적 replacement ID의 불변 참조다. 재전송 뒤에는 현재 자원을 다시 조회한다.
취소도 새 반대 동작을 기록하며 취소되지 않은 가장 최근 교체를 다시 선택한다. 그 교체가 `clear_next_check_override`로 해제한 직접 지정일은 해제 직후의 연결 version이 그대로일 때만 되살리고 연결 version을 1 올린다. 응답 형태는 같으므로 최신 연결은 GET으로 다시 조회한다.

`GET /api/v1/homecare/status`는 Asia/Seoul의 오늘(`as_of`) 기준으로 사용 중인 가전/소모품 연결을 반환한다.
`replacement_due`는 날짜 미확인일 때 null, `purchase_needed`는 공용 재고가 기기별 교체 수량보다 적을 때 true이며
`low_stock`은 별도의 재고 부족 임계와 비교한다. 자산의 선택 월은 입력으로 받지 않는다. 모든 목록은 UUID cursor와 최대 200개 limit로 나눈다.
곧 교체는 클라이언트가 `as_of`·`next_check_on`·`replacement_due`로 계산하며 별도 응답 필드는 없다.
첨부파일의 연결·다운로드는 SB-023의 별도 typed 문서 계약을 사용한다.

가전·재고·교체 24개 계약의 웹/Android 화면 연결과 홈의 월/오늘 분리는 [가전·재고 UI 검증](testing/homecare-client.md)을 따른다.


### SB-028~SB-032 보관함 서버

보관함은 클라이언트가 암호화한 opaque envelope만 받는다. 일반 카드 응답에 `has_secret`을 추가하며,
현재 키의 미폐기 비밀 존재 여부를 나타낸다. PAN·유효기간·CVC 평문은 입력/응답 계약에 없다.
정확한 포맷·AAD·KDF와 길이는 [보관함 v1 결정](adr/vault-format-v1.md)을 따른다.

| `/api/v1` 아래 경로 | 동작·버전 기준 |
|---|---|
| `/vault/status` | GET 가계 상태·본인 권한·구성원·회전 필요 여부 |
| `/vault/initialize` | POST 초기 key check/member/recovery bundle; If-Match 없음 |
| `/vault/wrappings/me` | GET 현재 본인 wrapping+key check, PUT 본인 암호 변경; wrapping version |
| `/vault/recovery-wrap` | GET 현재 복구 wrapping+key check; 최근 인증 필요 |
| `/vault/recover` | POST 본인 wrapping+복구 wrapping 동시 교체; vault status version |
| `/vault/members/{member_id}/revoke` | POST 구성원 권한 철회; membership version |
| `/vault/shares` | GET 본인 관련 공유 이력/cursor, POST 공유 생성; vault status version |
| `/vault/shares/{offer_id}/wrapping` | GET 대상 본인만 미만료 wrapping 조회; 최근 인증 필요 |
| `/vault/shares/{offer_id}/accept`, `/cancel` | POST 수락/취소; offer version |
| `/cards/{card_id}/secret-envelope` | GET 현재 암호문, PUT 새 비밀, DELETE 모든 온라인 버전 비밀 폐기; card version |
| `/vault/rotations` | POST 새 버전/원본 manifest 예약; vault status version |
| `/vault/rotations/{rotation_id}` | GET 준비 상태·카드/구성원 manifest |
| `/vault/rotations/{rotation_id}/prepare` | POST 새 key check/전체 member/recovery bundle; rotation version |
| `/vault/rotations/{rotation_id}/cards/{card_id}` | PUT 원본 ID/revision에 해당하는 새 암호문, GET 준비된 암호문; rotation version |
| `/vault/rotations/{rotation_id}/wrappings/me` | GET 준비된 본인 wrapping+key check |
| `/vault/rotations/{rotation_id}/finalize`, `/abort` | POST 전체 원자 전환/회전 중단; rotation version |

모든 mutation은 Idempotency-Key를 요구하며 재전송 응답은 당시 `{id,version}` 참조다.
If-Match는 표의 해당 metadata version을 사용하며 key_version이나 카드 secret revision과 다르다.
공유·복구·rewrap·철회·회전은 최근 5분의 계정 인증 또는 목적/대상에 묶인 일회성 step-up을 요구한다.
구성원 관리는 `vault.membership`과 대상 member ID, 회전은 `vault.key_rotation`과 household ID다.
토큰과 평문 비밀을 멱등 해시·감사 원문에 넣지 않는다. 모든 응답은 no-store이며 일반 가계 가입이
보관함 권한을 주지 않는다. `key_check_confirmed`는 client 동의 기록이며 서버 인증 증거가 아니다.

회전은 종료 카드까지 현재 모든 미폐기 비밀과 활성 구성원을 고정한다. 진행 중인 공유는 종료하고
준비 중 비밀/권한/rewrap 변경을 동결한다. 현재 키 읽기는 가능하며 모든 새 암호문과 wrapping이
완성된 뒤 DB에서 current를 한 번에 전환한다. abort 버전과 nonce는 다시 쓰지 않는다.
철회된 구성원은 즉시 opaque 조회가 막히고, 남은 구성원도 새 비밀 쓰기/재공유 전에 HVK 회전이 필요하다.
비밀 DELETE는 현재·retired·aborted 암호문을 NULL로 폐기하지만 nonce·원본 참조·감사·카드 metadata는 남긴다.
온라인 폐기가 이전 백업/기기 사본까지 회수하지는 않는다. 실제 검증 범위는 [서버 기록](testing/vault-server.md)에 있다.

## SB-037 사용자 내보내기·감사 조회 구현 계약 (R20)

`POST /api/v1/exports`는 현재 공동 가계의 JSON/CSV와 선택 문서 원본을 하나의 ZIP 응답으로 반환한다. 요청 예시는 `{"formats":["json","csv"],"document_ids":[]}`이며 각 목록은 중복을 허용하지 않는다. `formats` 생략 시 두 형식을 모두 생성한다. 임의 가계 ID, SQL, 저장 경로, 출력 파일명은 받지 않는다. 전체 운영 백업과 서버 복원은 별도 작업이다.

현재 세션의 5분 이내 로그인/재인증 또는 `X-Step-Up-Token`의 `data.export` 증명이 필요하다. 증명 target은 현재 `household_id`이고 사용자·세션·기기·자격증명까지 바인딩한다. 웹 쿠키 요청에는 기존 Origin/CSRF 검증이 적용된다. 먼저 증명을 소비 없이 검사하고, ZIP 준비 이후 새 트랜잭션에서 현재 권한과 선택 문서를 다시 확인한다. 성공 발급과 감사 기록에 한해 같은 트랜잭션에서 증명을 한 번 소비한다. 준비 실패 시 증명은 소비하지 않는다. 각 POST는 새 export ID와 새 스냅샷을 생성하며, 재사용 가능한 다운로드 URL이나 서버 작업 레코드를 만들지 않는다.

데이터 조회는 첫 조회 전에 PostgreSQL `REPEATABLE READ READ ONLY`를 설정한다. 자산·월별 모든 revision/값, 계좌·카드 일반정보, 수입과 현금 원본/정정 이력, 고정비 규칙/회차/분할 납부, 보험 계약/진료 트리/비용/청구/지급/배분/반환, 가전·소모품·재고/교체, 문서 메타데이터/연결 이력을 포함한다. 화면의 200행 페이지 제한으로 잘라내지 않는다. 기록된 null/0/미확인 상태와 연결 ID를 그대로 유지하고 합계를 다시 만들거나 잔액을 자동 가감하지 않는다. 현금 원본은 한 행씩, 청구·배분 등은 참조 행으로 내보낸다. 구성원 이름은 member ID와 연결하며 계정 로그인 ID는 제외한다.

명시적 필드 목록은 `services/api/src/sallimbook/exports/catalog.py`이며 새 테이블/컬럼은 공개 또는 비공개 분류 검사를 통과해야 한다. 보관함 전체, 카드 비밀 envelope/wrapping, 인증·세션·초대·grant·멱등 레코드, 전체 계좌/증권번호 및 암호문·nonce·키 버전, 비공개 파일 경로/암호화 키/예약 저장량은 내보내지 않는다. 선택 문서는 동일 가계의 ready 상태와 유효 연결을 요구하며 최종 발급 직전에 버전·checksum·크기·연결을 다시 확인한다. 파일명은 UUID와 검증된 MIME 확장자로 생성한다. 문서 원본과 업무 메모는 사용자가 입력한 내용을 유지하므로 그 안에 포함된 민감한 텍스트를 자동 삭제한다고 보장하지 않는다.

ZIP의 `manifest.json`은 형식 버전 `sallimbook-user-export-v1`, export ID, 가계 ID, 스냅샷 시각, 발급 시한, KRW/Asia-Seoul 기준, 제외 범주, 각 파일의 크기/SHA-256/행 수를 담는다. 테이블 경로는 `json/{table}.json`, `csv/{table}.csv`, 문서 경로는 `documents/{uuid}.{pdf|png|jpg}`다. ZIP은 메모리에서 완성한 뒤 발급하며 평문 임시 파일을 디스크에 쓰지 않는다. 응답은 `application/zip`, `Content-Disposition: attachment`, `Cache-Control: no-store`, `Pragma: no-cache`, `X-Content-Type-Options: nosniff`, `X-Export-ID`, `X-Export-SHA256`, `Content-Length`를 제공한다.

JSON 금액은 정밀한 십진 문자열, 월은 `YYYY-MM`, 날짜는 ISO 날짜, timestamp는 UTC다. CSV는 UTF-8·CRLF·전체 셀 인용 형식이며 **모든 문자열 앞에 눈에 보이는 `text:`를 붙인다**. 금액도 문자열이므로 이 규칙을 따른다. null은 접두사가 없는 `\N`, 빈 문자열은 `text:`, 실제 문자열 `\N`은 `text:\N`이다. 숫자형 개수와 bool만 접두사 없이 출력한다. 복원 시 문자열 접두사를 정확히 한 번 제거한다. 수식 기호·탭·줄바꿈·전각 기호를 포함한 문자열도 원래 값의 첫 문자로 시작하지 않도록 한다. 다른 CSV 처리기의 임의 재가공까지 보장하지 않으며 원본 문자열 교환에는 JSON을 사용한다.

기본 한도는 전체 100,000행, JSON+CSV+manifest 합산 16MiB, 선택 문서 10개/합산 40MiB, ZIP 64MiB다. 초과 시 413으로 전체 실패하며 일부 자료를 성공 응답으로 내보내지 않는다. 준비/발급 시한은 30초이며 세션·재인증·grant가 먼저 만료되면 먼저 거부한다. 전송은 최대 120초다. API 프로세스당 준비와 전송을 합쳐 한 요청만 허용하고 중복 작업은 503을 반환한다. 취소돼도 실제 동기 작업이 끝나기 전에는 슬롯을 풀지 않는다. 발급 시한은 서버에서 새 파일을 발급할 수 있는 시한이며 이미 저장된 로컬 파일을 만료·회수하지 않는다.

`GET /api/v1/audit-events`는 현재 가계의 감사 메타데이터만 반환한다. `limit` 1..200, `cursor`, `entity_type`, `entity_id`, `actor_member_id`, `action`, timezone을 포함한 `since`/`until` 필터를 지원한다. 기간은 `[since, until)`이다. 시각 내림차순·UUID 내림차순 keyset cursor에 가계/필터 바인딩을 검사한다. 삭제된 엔티티의 감사 이력도 조회할 수 있다. 응답은 ID, actor member ID, 엔티티/동작, 요청 ID, 전후 버전, UTC 시각, 알려진 변경 필드 이름만 제공한다. 원본 `safe_diff`나 전후 값은 반환하지 않으며 잘못된 메타데이터는 503으로 실패한다. 여러 HTTP 페이지 전체를 하나의 DB 스냅샷으로 보장하지 않는다.

계정 보안 동작도 같은 감사 어휘(`core/audit.py`의 `AuditEntityType`·`AuditAction`, 39개·22개)로 기록한다. `registered_device/login`(로그인으로 기기 세션 시작), `registered_device/revoke`(기기 연결 해제·로그아웃·다른 기기 모두 로그아웃으로 실제 세션 폐기, 기기마다 1행), `passkey/create`·`passkey/revoke`, `invitation/create`·`invitation/accept`, `user/update`(비밀번호 변경, 바뀐 필드 이름 `password_hash`만)이다. 비밀번호·토큰·초대 코드·자격증명 원문은 기록하지 않는다.

`user_export/export` 감사는 완성된 파일의 **서버 발급**을 뜻하며 클라이언트 저장 완료를 뜻하지 않는다. 선택 문서 열람 감사도 같은 요청 ID로 기록한다. 일반 audit API에는 최근 재인증을 추가로 요구하지 않지만 현재 세션·기기·활성 가계 구성원 권한은 검사한다. 이 API PR은 Android/웹 내보내기 화면, 운영 백업 스케줄과 실제 새 서버 복원 완료를 의미하지 않는다.
