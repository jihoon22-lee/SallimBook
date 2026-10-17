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

## 8. 앱 잠금 상태 (Refs #18, #38)

`SallimBookAuth.getAppLock()`은 `{locked}`만 반환하고 `lockApp()`은 인자 없이 즉시 잠근다.
`appLockChanged` 이벤트의 `{locked}`는 JS 화면과 입력 폐기·세션 재조회 안내용이다.
해제 메서드나 성공 bool 입력은 없다. 실제 해제는 네이티브 가림 화면의 OS 인증 또는 검증된 서버 재인증만 수행한다.
`getSession`을 포함한 보호 명령은 잠긴 동안 `APP_LOCKED`로 거절하고 JS가 웹 HTTP로 우회하지 않는다.
잠금 이벤트를 받으면 AuthProvider는 세대·멤버·CSRF 참조를 지우고 하위 화면을 제거한다.
해제 이벤트 후 새 native 세션 조회를 통과해야 금융 화면이 다시 만들어진다. 이전 입력을 자동 복원하지 않는다.

Activity가 아닌 프로세스 공통 네이티브 정책이 요청 세대를 관리한다. 토큰 접근, 전송 직전,
인증 본문 쓰기, HTTP 응답, bridge 전달에 같은 정책을 적용한다.
잠금 전 만들어져 대기 중이던 요청도 생성 시점 세대를 유지하므로 나중의 해제로 되살아나지 않는다.
로그인·초대·현재 계정 재인증·명시 로그아웃 경로의 제한된 예외로 일반 metadata를 조회할 수 없다.
서버 로그인과 앱 잠금, 카드 CryptoObject 인증은 계속 별개다.

## 9. 자산·계좌 메타데이터와 계좌번호 (SB-010/011)

`SallimBookAuth`의 별도 typed 메서드가 자산·계좌 API를 호출한다. 입력 DTO는 생성 API client에서
가져오고 Kotlin은 필드·UUID·버전·쿼리·허용 경로를 다시 검사한다. `request`의 범위를 임의 본문이나
금융 API 전체로 확장하지 않는다. JS auth facade는 웹의 CSRF·step-up grant 값을 feature에 반환하지 않는다.

| 메서드 | JS 입력 | 반환 경계 |
|---|---|---|
| `listAssets`, `listAccounts` | 허용된 타입·소유자·상태·cursor·limit 쿼리 | 필드별 검증을 거친 메타데이터 페이지 |
| `getAsset`, `getAccount` | 해당 UUID | 공개 메타데이터 |
| `createAsset`, `createAccount` | 생성 DTO; 계좌번호 제외 | 생성한 메타데이터 |
| `updateAsset`, `updateAccount` | UUID, 변경 DTO, ifMatch | 최신 메타데이터; 계좌번호 제외 |
| `archiveAsset` | 자산 UUID, 종료일, ifMatch | 과거 기록을 보존한 종료 자산 |
| `deleteAsset` | 자산 UUID, ifMatch | 상태만; 현재 UI는 삭제 대신 사용 종료 제공 |
| `editAccountNumberUI` | accountId, ifMatch | saved/deleted/cancelled |
| `showAccountNumberUI`, `showAccountNumberWithPasskeyUI` | accountId | completed/cancelled |

계좌번호 입력·조회는 `NativeAccountNumberActivity` 내부에서만 처리한다. 전체 번호, 키, HTTP 본문,
step-up grant를 JS로 전달하지 않는다. 입력 화면은 번호를 미리 채우지 않으며 Android 보안 화면과
최대 30초 표시 정책을 사용한다. 취소·인증 실패·버전 충돌도 메타데이터를 다시 확인하므로 서버 반영 후
응답 취소를 이전 값으로 오해하지 않는다. 오류는 허용된 `AuthCode`만 전달한다.
패스키 확인 버튼은 별도로 제공하며 인증 scope는 `account.reveal`과 정확한 계좌 ID에 고정한다.

웹 전체 번호는 전용 `AccountNumber` 컴포넌트만 받는다. 일반 계좌 DTO·React state·브라우저 저장소에
넣지 않고 제한된 output DOM에 최대 30초 표시한다. blur/pagehide/숨김/화면 이탈/계좌 버전 변경 시
입력과 표시를 지우고, 취소된 요청의 늦은 응답을 표시하지 않는다. 웹 캡처 차단이나 JS 메모리의 완전한
영점화는 보장하지 않는다. 계좌번호는 서버 필드 암호화 대상이며 카드 보관함 E2EE와는 별개다.


## 10. 월별 자산 메타데이터 (SB-012)

`nativeFinance`는 생성 DTO를 사용하는 8개 이름 있는 명령을 제공한다.
`getAssetMonth`, `getAssetMonthRevision`, `listAssetMonthRevisions`는 제한된 월·변경본·페이지 인자만 받는다.
`createAssetMonthDraft`, `updateAssetMonthValue`, `synchronizeAssetMonthScope`, `confirmAssetMonth`,
`reopenAssetMonth`는 해당 입력 DTO와 필요한 `ifMatch`·`idempotencyKey`만 받는다.
일반 `request`의 허용 경로는 늘리지 않는다. 네이티브 HTTP는 이름 있는 명령에서 만든 고정 경로와
본문·버전·중복 방지 키 조합을 다시 검증하며 다른 경로에 `Idempotency-Key`를 붙일 수 없다.

금액은 최대 20자리 정수 십진 문자열을 유지한다. 미입력 null, 0원, 전월값 미확인을 구분하고
값 변경에 필요한 `revision_id`·`value_id`를 생략할 수 없다. 응답의 월·변경본·자산·값 행 식별자를
요청과 대조하며 중첩 필드와 페이지 크기도 제한한다. 계산과 권한의 최종 판단은 서버가 수행한다.
오류는 허용한 코드와 로컬 고정 메시지만 전달한다. 서버 원문 메시지·상세 정보는 전달하지 않는다.
앱 잠금과 세대 검사는 토큰 접근부터 HTTP 응답·bridge 전달까지 기존 보호 경로를 사용한다.

## 11. 수입 메타데이터 (SB-014)

생성 DTO를 사용하는 `listIncome`, `incomeSummary`, `incomeDuplicateCandidates`, `getIncome`,
`incomeHistory`, `createIncome`, `correctIncome`, `voidIncome`, `returnIncome`, `convertIncomePrecision`도
같은 보호된 네이티브 실행 경로를 사용한다. 조회는 허용된 월·구성원·종류·정밀도·페이지 인자만 받는다.
모든 쓰기에는 `idempotencyKey`, 기존 기록 정정·무효·반환에는 `recordId`와 `ifMatch`가 필요하다.
전환은 중복 없는 원본 ID·버전과 최대 100개의 대체 입력을 전달하며 합계 일치의 최종 검증은 서버가 한다.
반환 입력은 구성원을 새로 선택하지 못한다. 수입 API에서 보험·진료 기록을 임의 생성하는 경로는 없다.

금액 문자열·명시 null·날짜 정밀도를 보존한다. 기록 조회·이력은 요청한 기록 ID와 대조하고,
반환 결과는 원본 ID를, 합계 결과는 조회 월을 확인한다. 응답은 중첩 합계·기록·페이지를 검증한 뒤
반환하며 오류에는 서버 원문 메시지·본문을 보관하지 않는다. 앱 잠금·네이티브 미지원 오류 뒤에
웹 API를 호출하는 우회는 없다. 계좌·월별 자산 스냅샷을 자동 가감하지 않는다.

검증: `pnpm android:sync`, `pnpm typecheck`, Gradle
`:app:testDebugUnitTest :app:compileReleaseKotlin` 통과. 월별 9개·수입 10개 경계 시험과
패스키 대상 페이지 3개를 포함한 JVM 97개가 통과했다.
`pnpm --filter @sallimbook/client exec playwright test cashflow-native-bridge.spec.ts --config playwright.finance.config.ts --workers=2`는
18개 명령의 DTO·헤더 값 전달, 웹 HTTP 미사용, 잠금·중복 충돌·미지원 오류 경계를 두 화면 크기에서
8개 시험으로 확인했다. 이 시뮬레이션은 실제 Android 기기 보안을 검증하지 않으며 실기기 시험은 미실행이다.
