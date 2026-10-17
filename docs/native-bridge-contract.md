# Android 네이티브 bridge 계약

대상: `plugins/sallimbook-security`. 구현 전 Kotlin/TypeScript 양쪽 계약을 이 문서에 맞춰 검토한다.
SB-003의 `src/definitions.ts`는 아래 8개 메서드의 안전한 TypeScript 경계를 정의한다.
실제 보안 구현 전에는 Android 동작을 `AUTH_UNAVAILABLE`, 웹·그 외 플랫폼을
`UNSUPPORTED_PLATFORM`로 거부한다. capability의 미확인 기기 상태는 `null`이며 보안 상태를 추정하지 않는다.
Gradle `validateBundledRuntimeConfig`가 번들 설정의 원격 URL·비어 있지 않은 `server.allowNavigation`·cleartext·mixed content를 빌드 전에 거부한다.
`allowNavigation`은 원격 페이지를 네이티브 bridge가 있는 WebView 안에 유지할 수 있으므로 와일드카드를 포함한 모든 허용 항목을 차단한다.
`pnpm android:sync` 후 `python3 scripts/test_android_runtime_config.py`로 실제 Gradle 검사 task를 시험한다. 시험은 생성된 설정을 임시 변경하고 원래 바이트로 복원한다.
Android 뒤로가기는 `@capacitor/app` adapter를 사용한다. 보안 bridge의 암호 처리 구현은 후속 Issue 대상이다.

## 1. 책임

JS는 카드 ID와 사용자가 원하는 행동만 전달한다.
네이티브가 승인된 계정 세션·대상 카드·API origin을 확인하고 시스템 인증/키 접근/입력/표시를 수행한다.
암호문 전송과 key wrapping 처리는 검증된 native crypto 서비스가 수행한다.
반환값에는 성공/취소/오류와 안전한 메타데이터만 포함한다.

| 메서드 | 입력 | 출력 |
|---|---|---|
| getCapabilities | 없음 | 지원 생체수단·device secure·vault 등록 여부 |
| openCardSecretEditor | cardId, create/edit | saved/cancelled, cardId, lastFour, version |
| showCardSecrets | cardId, includeLocalCvc | completed/cancelled/expired; 평문 없음 |
| editLocalCvc | cardId | saved/cancelled; 코드 없음 |
| deleteLocalCvc | cardId | deleted/notFound |
| enrollDeviceVault | 명시적 사용자 동작 | enrolled/cancelled |
| lockVault | 없음 | locked |
| forgetDeviceVault | 재인증된 명시 동작 | forgotten |

이 메서드는 OS 생체정보 원문, CVC, HVK, 전체 PAN, 비밀번호, refresh token을 JS로 반환하지 않는다.
`decrypt(ciphertext)` 같은 임의 복호화 API를 만들지 않는다.

## 2. 호출 검증

cardId의 형식·가계 권한과 사용 상태를 검증한다.
production 앱은 번들된 웹 자산만 bridge 사용을 허용한다. `server.url` 개발 설정이 release에 남으면 빌드 실패.
외부 사이트·도움말·구매 링크는 bridge 없는 외부 브라우저로 연다.
네이티브 API host는 배포 allowlist에서 고정하며 호출 인자로 임의 host/token/URL을 받지 않는다.
확인 없는 JS 호출이 인증 prompt를 무한히 띄우지 않도록 foreground·사용자 동작·동시 요청을 제한한다.

## 3. 상태 전이

`idle → target_check → awaiting_auth → decrypting → visible → locked`.
취소·타임아웃·백그라운드·회전/재생성·기기잠금·세션만료는 locked로 복귀한다.
기존 비밀 화면이 열려 있을 때 다른 카드 요청은 기존 표시를 닫고 다시 인증한다.
복호화 전에 표시 UI는 빈값 또는 마스킹이어야 한다.

## 4. 오류

AUTH_CANCELLED, AUTH_UNAVAILABLE, AUTH_LOCKED_OUT, KEY_INVALIDATED,
VAULT_NOT_ENROLLED, SESSION_EXPIRED, ACCESS_DENIED, CIPHER_INVALID,
NETWORK_UNAVAILABLE, UNSUPPORTED_PLATFORM.
오류 메시지에는 카드 원문이나 암호 파라미터 값을 과도하게 노출하지 않는다.
JS는 '키 무효화'를 단순 재시도로 우회하지 않고 복구 안내로 이동한다.

## 5. 인증 역할 분리

서버 로그인은 별도의 auth adapter가 Credential Manager/비밀번호 경로와 세션을 관리한다.
보관함 prompt의 성공을 서버 로그인 토큰으로 바꾸지 않는다.
서버가 공개키 challenge를 검증하는 passkey와 로컬 CryptoObject의 키 해제는 서로 다른 절차다.

## 6. PC adapter

일반 UI는 같은 의도를 호출하되 PC는 web vault controller로 PAN/유효기간을 다룬다.
CVC 관련 명령은 비지원 상태를 명확히 반환하고 브라우저 로컬 저장으로 몰래 대체하지 않는다.
web vault에서도 secret component에만 평문을 한정하고 일반 상태관리·URL·분석 SDK에 노출하지 않는다.


## 7. 계정 인증 bridge (SB-005/006)

계정 인증은 위 보관함과 별개인 `plugins/sallimbook-auth`다.
[실제 TypeScript 정의](../plugins/sallimbook-auth/src/definitions.ts)를 기준으로 Kotlin 경계를 함께 검증한다.
모든 호출은 `{ok: true, value}` 또는 허용한 오류 코드만 반환한다. 네이티브 화면에서 로그인 이름·비밀번호·
패스키 이름·초대 입력을 처리하며 WebAuthn challenge·assertion·device binding·step-up grant·세션 토큰은
호출 인자와 반환값에 포함하지 않는다.

| 메서드 | JS 입력 | 성공 값 |
|---|---|---|
| `getSession` | 없음 | available, authenticated |
| `loginUI`, `passkeyLoginUI` | 없음 | authenticated/cancelled |
| `reauthenticateUI` | 없음 | authenticated/cancelled; 기존 세션·기기 유지 |
| `registerPasskeyUI` | 없음 | registered/cancelled |
| `revokePasskeyUI` | credentialId, If-Match 형식의 ifMatch | revoked/cancelled |
| `revokeDeviceUI` | deviceId, If-Match 형식의 ifMatch | revoked/cancelled |
| `acceptInvitationUI` | 없음 | accepted/cancelled; 로그인은 별도 동작 |
| `createInvitationUI`, `createInvitationWithPasskeyUI` | 없음 | created/cancelled; 초대 코드는 네이티브에 최대 30초 표시 |
| `logout` | 없음 | signedOut, serverRevoked |
| `request` | 허용된 method/path/ifMatch | status와 검증된 공개 메타데이터 |

`request`는 GET `/me`, `/household/members`, `/devices`, `/auth/passkeys`와 버전을 지정한
DELETE `/devices/{UUID}`만 허용한다(공통 `/api/v1` 접두사). 쿼리·ID·응답 필드도 제한하며,
일반 API 메타데이터의 TS 타입은 생성 API client를 사용한다. 임의 본문·헤더·URL을 받아 전송하지 않는다.

`revokeDeviceUI`와 `createInvitationWithPasskeyUI`는 각각 대상 기기와 현재 가계에 고정한 scope로
Credential Manager 인증을 수행하고 같은 네이티브 작업 안에서 grant를 소비한다. 패스키 등록·폐기는
최근 계정 로그인 조건을 별도로 만족해야 한다. 단순 로컬 생체 인증 콜백으로 서버 인증을 대신하지 않는다.
비밀번호 재인증 실패는 기존 로그인 정보를 지우거나 새 기기를 만들지 않는다.
