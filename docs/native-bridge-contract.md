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

패스키 제공자의 불투명 화면이 네이티브 Activity를 중단하거나 상태 저장을 요청해도,
현재 제공자·ceremony·요청 세대·취소 신호가 일치할 때만 메모리의 요청을 잠시 유지한다.
첫 포커스/화면 이탈부터 최대 60초 또는 challenge 만료 중 더 이른 시각에 취소한다.
반복 pause/stop/save는 기한을 연장하지 않는다. 제공자 응답 후에는 1초 안에 resumed·포커스·
기기 잠금 해제 상태가 모두 돌아와야 서버 검증을 시작하며, 이후 화면 이탈은 전송도 취소한다.
Home 등으로 계속 이탈한 경우 응답을 사용하지 않으며 위 고정 기한 안에 폐기한다.
화면 꺼짐·명시 취소·앱 잠금·Activity 파괴는 제공자 취소 신호와 ceremony를 함께 폐기한다.
상태 Bundle·WebView·bridge에 인증 응답을 저장하지 않는다.

현재 고정된 AndroidX Credential Manager 1.6.0의 패스키 controller가 사용하는
`androidx.credentials.playservices.controllers.identityauth.HiddenActivity`는 같은 task의
현재 제공자 요청이 있을 때만 앱 잠금 중 화면 전환을 허용한다. 실제 manifest에서 non-exported임을
다시 확인하며, 일반 API 권한이나 앱 잠금 해제를 부여하지 않는다. 다른 SDK Activity는 허용하지 않는다.
이 예외는 [Android Activity 생명주기](https://developer.android.com/guide/components/activities/activity-lifecycle)와
[고정 버전의 공식 소스](https://dl.google.com/dl/android/maven2/androidx/credentials/credentials-play-services-auth/1.6.0/credentials-play-services-auth-1.6.0-sources.jar)를 확인해 제한했다.

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


## 12. 카드 일반정보 (SB-017)

`listCards`, `getCard`, `createCard`, `updateCard`, `archiveCard`, `deleteCard`는 생성 API DTO에
대응하는 이름 있는 명령이다. 목록은 소유자·종류·결제계좌·상태·cursor·limit, 단건은 `cardId`,
수정·종료·삭제는 강한 버전 문자열 `ifMatch`만 추가로 받는다. 서버 경로와 HTTP 헤더는 네이티브가
고정하며 이 명령으로 PAN·유효기간·CVC·암호문·보관함 API를 호출할 수 없다.

입력 필드를 정확히 제한하고 마지막 네 자리는 ASCII 숫자 네 자리만 허용한다. 응답도 정확한 필드·
식별자·페이지 크기와 `masked_number`의 마지막 네 자리 일치를 검증한다. 결제계좌의 종료 상태를
보존하며 계좌를 자동 교체하거나 연결을 지우지 않는다. 카드 전체 비밀 보관함과 로컬 CVC 구현은
이 메타데이터 작업의 범위에 포함되지 않는다.

공통 `CashResponse.card_id`는 UUID 또는 null로 검증한다. 수입 생성·반환·정밀도 전환 입력의
`card_id`는 생략 또는 null만 허용하고, 수입 정정 입력에는 해당 필드 자체를 허용하지 않는다.
따라서 공통 cash 응답 확장이 수입의 카드 결제 입력 경로를 만들지 않는다.

카드 명령 8개 경계 시험과 cash 계약 회귀 시험 1개를 추가해 JVM **106개**가 통과했다.
`pnpm android:sync`, Gradle `:app:testDebugUnitTest :app:assembleDebug :app:compileReleaseKotlin`이
통과했고 개발 APK가 생성됐다. `cashflow-native-bridge.spec.ts`는 앞 절의 같은 명령으로
24개 명령의 전달과 오류 경계를 두 화면 크기에서 **8개** 시험으로 검증한다.
finance Playwright 설정은 전용 18748 포트만 시작해 다른 작업의 18743 서버와 분리한다.
독립 코드 검토를 마쳤으며 실제 Android 기기 실행은 아직 수행하지 않았다.


## 13. 자산 비교·추이 조회 (SB-013)

`getAssetComparison({query})`와 `getAssetTrends({query})`는 각각 생성 API의 query와 응답 DTO를
사용한다. 네이티브는 고정 GET 경로만 만들며 body·버전·중복 방지 키·임의 헤더를 받지 않는다.
월·자산·소유자·종류·분류 필터를 검증하고 공동 소유와 개인 소유자 조건의 혼용을 거부한다.
비교의 이전 월은 확인 월보다 앞서야 하며, 추이는 시작·종료 월을 포함해 최대 120개월이다.
비교의 페이지는 최대 200행이고 중복·역순 행과 잘못된 cursor를 거부한다.

응답의 월·변경본 참조·필터·자산 ID가 요청과 맞는지 확인하고 기존 월별 DTO 검증을 재사용한다.
확정/재개방/초안/없는 월, provisional, 미입력 null, 0원, 증감률 계산 불가 사유를 보존한다.
금액과 두 자리 소수 증감률은 문자열만 허용하며 네이티브에서 다시 계산하거나 float로 바꾸지 않는다.
추이에는 요청한 모든 월이 순서대로 있어야 하고, 미확정 관측값을 확정 금액으로 승격한 응답은 거부한다.
전체 범위의 변경·기준일 ID 목록은 페이지 행 수와 별개이며 기존 3 MiB 전송 상한 안에서 검증한다.
일반 `request` 경로는 확장하지 않고 기존 앱 잠금·세대 검증을 그대로 적용한다.

검증: 공식 `pnpm api:generate`로 병합한 router 계약을 재생성하고 `pnpm android:sync`를 통과했다.
Gradle `:app:testDebugUnitTest :app:compileReleaseKotlin --max-workers=2`는 **130개** JVM 시험
(실패·오류·건너뜀 0)을 통과했다. 이 중 비교·추이 경계 시험 12개와 제공자 생명주기 시험 12개가 포함된다.
`cashflow-native-bridge.spec.ts`는 앞 절의 같은 Playwright 명령으로 **26개** 명령의 전달을
두 화면 크기에서 **8개** 시험으로 확인했다. 이 단계에서 실기기 시험은 수행하지 않았다.


## 14. 고정 납부 규칙·회차·실제 납부 (SB-015/016)

생성된 `fixed-costs` 계약의 18개 명령을 네이티브에 연결했다. 규칙 목록·생성·조회·적용 변경·종료,
회차 생성·목록·요약·조회·이력·이동·건너뜀·복원·완료·재개, 실제 납부·납부 목록·납부 취소를
각각 이름 있는 메서드로 호출한다. 모든 쓰기는 `idempotencyKey`, 기존 자원 변경은 강한 `ifMatch`가
필요하다. 일반 HTTP 경로·임의 헤더·본문은 입력받지 않는다.

`RuleCreate`의 최초 종료일과 종료 사유는 한 쌍이며 시작일 뒤여야 한다. `RuleChange`는 부분 수정이
아니라 새 적용일의 조건 전체와 사유를 요구한다. 규칙의 과거 적용본과 불변 `MutationReference`의
`id`·`version`을 보존한다. 회차 변경에는 회차 버전을, 실제 납부 취소에는 `cash.version`을 사용한다.
회차 생성 범위는 양 끝을 포함해 최대 366일, 응답 참조는 최대 2,000개다. 목록·이력은 200개 페이지를
검증하며 규칙의 과거 적용본 목록을 페이지 행 수와 혼동하지 않는다.

예상 금액의 null과 0원을 구분하고 실제 납부는 양수 정수 원 문자열만 허용한다. 원금·소비·자산이전
분해값도 문자열 그대로 전달한다. 응답 분해 합계와 현금 원본 금액을 `BigInteger`로 대조하며 금액을
재계산해 덮어쓰지 않는다. T-09의 1,000,000원=원금 700,000원+소비성 이자 300,000원과 T-11의
예상 33,000원/실제 35,000원 예제를 사용했다. 외화 금액·통화는 참고 문자열이고 자동 환산하지 않는다.
반복 날짜 계산·납부 집계·자산이나 계좌 잔액의 최종 판단은 서버에 있으며 네이티브가 스냅샷을 가감하지 않는다.

실제 납부 응답은 해당 회차·납부 ID, `fixed_payment` 현금 변경본, 출금 방향·일 단위 날짜·변경본 상태와
버전을 검증한다. 과거 멱등 응답을 최신 현금 변경본으로 바꾸지 않는다. 정확한 중첩 필드 검증과 앱 잠금·
요청 세대 검사를 사용하며 카드번호·CVC·토큰·서버 원문 오류 메시지는 전달하지 않는다.

공식 계약 재생성(`0009_recurring` 준비 상태), `pnpm android:sync`, Gradle
`:app:testDebugUnitTest :app:compileReleaseKotlin --max-workers=2`를 통과했다. 신규 경계 시험 15개를
포함한 JVM **145개**가 통과했고, `cashflow-native-bridge.spec.ts`는 **44개** 명령의 DTO·키·오류 전달을
두 화면 크기에서 **8개** 시험으로 검증했다. 브라우저 실행은 Docker 상태 변경과 겹치지 않도록 조율했고
임시 파일은 SSD 경로를 사용했다. 실제 Android 기기 시험은 아직 수행하지 않았다.

공통 `ASSET_KIND_IN_USE` 오류 보완을 병합한 뒤 타입 검사와 위 Gradle 검사를 다시 실행해
JVM **146개**(실패·오류·건너뜀 0)가 통과했다. 자산 종류 변경 제한을 일반 버전 충돌로 바꾸지 않는다.


## 15. 결제 연결 조회와 종료 확인 (SB-018)

`getCardPaymentLinks({resourceId, query})`와 `getAccountPaymentLinks({resourceId, query})`는
생성된 `PaymentLinksResponse`를 반환한다. 선택 종료일 `as_of_date`, 규칙·미납 회차·카드의 개별
cursor와 최대 200개 limit만 받는다. 네이티브는 고정 GET 경로를 만들고 대상 종류·ID·버전,
계좌의 연결 자산 ID, 선택 날짜, 64자리 소문자 hex digest와 세 페이지의 필드·순서·cursor를 검증한다.
계좌에 연결된 카드가 다른 페이지에 있어도 해당 카드의 납부 규칙은 누락시키지 않는다.

조회 범위는 `registered_recurring_only`, 전체 계좌 출금 합계 제공 여부는 false로 제한한다.
카드 승인 계획과 계좌 납부 계획을 구분하고 마지막 네 자리만 전달한다. 미입력 예상값 null·0원·
실제 납부 문자열과 선택 종료일 당일의 카드 활성 상태를 그대로 보존한다. 계좌번호·PAN·CVC·
암호문이나 임의 추가 필드는 반환하지 않는다.

기존 `updateAsset`, `archiveAsset`, `updateCard`, `archiveCard`의 생성 입력 DTO에는
`closure_ack`와 `usage_digest`를 허용한다. true 확인에는 digest와 명시한 종료일이 모두 필요하고,
false/생략 확인에는 non-null digest를 허용하지 않는다. 확인 명령 필드만 있는 PATCH도 거부한다.
생성 입력·일반 자산/카드 응답·계좌 기본정보 PATCH의 허용 필드는 확장하지 않는다.
`PAYMENT_LINKS_CHANGED`와 `PAYMENT_LINK_CONFIRMATION_REQUIRED`는 별도 오류로 보존한다.
Digest는 연결 변경 확인 값이며 인증 수단이 아니고, 실제 종료 권한·최종 digest 대조는 서버가 수행한다.

생성 TS의 필수 기본값과 맞추기 위해 기존 AssetEditor·AssetPages·AccountPages 호출은
`closure_ack:false`를 명시한다. 변경 없는 수정 거부는 유지하며 사용자 확인을 자동 승인하지 않는다.
종료 영향 확인 UI는 별도 화면 변경과 함께 연결한다.

공식 계약 병합·재생성(`0009_recurring`) 뒤 `pnpm android:sync` 및 Gradle
`:app:testDebugUnitTest :app:compileReleaseKotlin --max-workers=2`가 통과했다. 신규 경계 시험
12개를 포함한 JVM **158개**가 실패·오류·건너뜀 없이 통과했고 독립 코드 검토도 완료했다.
`TMPDIR=/home/jihoon/.cache/sallimbook pnpm --filter @sallimbook/client exec playwright test cashflow-native-bridge.spec.ts assets.spec.ts accounts.spec.ts accounts-native.spec.ts --config playwright.finance.config.ts --workers=2`는
46개 명령 전달·4개 종료 명령 확인값·기존 자산/계좌 흐름을 포함해 **54개**를 통과했다.
브라우저는 DB 시험 컨테이너 정지 확인 후 실행했고 실제 Android 기기 시험은 미실행이다.

## 16. 보험계약·사건·진료 트리와 증권번호 (SB-019/020)

생성 API의 보험 메타데이터 20개 operationId를 같은 이름의 네이티브 명령으로 연결했다.
보험계약 목록·생성·상세·수정, 보장 목록·생성·수정, 보험료 규칙 연결 목록·생성·수정,
독립 사건 목록·생성·상세·수정·이력, 진료 노드 목록·생성·상세·수정·삭제를 제공한다.
TS 입력·응답은 공식 생성 DTO를 참조하고 기존 자원 수정·삭제에는 강한 `ifMatch`가 필요하다.
계약 생성·수정의 TS 입력은 `policy_number`를 제외하며 JS와 Kotlin 모두 해당 키를 null까지 거부한다.
일반 `request` 명령과 임의 경로·헤더·원문 본문 입력은 확장하지 않는다.

계약/보장/납입 날짜를 각각 검증하고 보장금액은 null·0원·최대 20자리 정수 원 문자열을 보존한다.
보험료 연결은 기존 `RuleResponse` 검증을 재사용하며 계약·규칙·가계 ID를 대조한다.
사건의 치료 상태와 정산 상태는 독립이고, 치료 종료일과 시작일 관계를 검증한다.
사건 목록에는 진단 메모·코드를 허용하지 않으며 상세와 typed 변경 이력에서만 길이를 제한해 전달한다.
진료 노드는 종류·부모·정렬 순서·실제 날짜와 요청 사건 ID를 검증한다. 전체 트리의 순환·가계 권한과
최종 계산은 서버가 판단한다. 일반 목록의 ID/이력 version은 내림차순·중복 없음·cursor/limit을 검증한다.
진료 노드는 서버의 부모 우선·형제 정렬 순서를 보존하고 UUID cursor를 위치로 취급하며,
ID 중복·마지막 행 cursor·limit·사건 ID를 검증한다.
네이티브는 진료 노드에 금액을 추가하거나 보험료를 자산 스냅샷에 자동 합산하지 않는다.

`editInsurancePolicyNumberUI({policyId, ifMatch})`와
`showInsurancePolicyNumberUI({policyId})`는 별도의 비공개 native Activity를 연다.
`nativeFinance`에서는 각각 `editInsurancePolicyNumber`와 `showInsurancePolicyNumber`로 호출한다.
원문은 native 입력/HTTP/표시 내부에서만 사용하고 JS에는 saved/deleted/completed/cancelled 상태 또는
고정 오류 코드만 반환한다. 증권번호 전용 PATCH/POST reveal 경로는 계좌번호 경로와 분리해 검증한다.
계약 번호를 지울 때는 네이티브 화면에서 명시적으로 확인하며 기존 번호는 마스킹으로만 미리 읽는다.

이 화면은 FLAG_SECURE, 저장 상태·자동완성·content capture·문맥 메뉴 차단을 적용하고
최대 30초의 monotonic 표시 시간을 사용한다. focus 상실·pause·화면 꺼짐·앱 잠금·닫기·파괴 시
요청을 취소하고 입력/표시 버퍼를 지운다. 늦은 응답은 foreground gate와 앱 잠금 세대로 차단한다.
서버는 현재 세션의 최근 비밀번호 인증을 확인한다. 재인증 필요 시 화면을 닫고 기존 native 비밀번호
재인증을 사용하도록 안내하며 증권번호용 passkey scope나 우회 버튼은 추가하지 않는다.
서버 필드 암호화와 카드 보관함 E2EE는 다른 경계다.

공식 계약 재생성(`0010_insurance_core`) 및 `pnpm android:sync`를 통과했다.
`JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ANDROID_HOME=/home/jihoon/Android/Sdk apps/client/android/gradlew -p apps/client/android --no-daemon --max-workers=2 testDebugUnitTest compileReleaseKotlin`은
신규 보험 경계 15개를 포함한 JVM **173개**를 실패·오류·건너뜀 없이 통과했고 release Kotlin을 컴파일했다.
`TMPDIR=/home/jihoon/.cache/sallimbook pnpm --filter @sallimbook/client exec playwright test insurance-native-bridge.spec.ts cashflow-native-bridge.spec.ts accounts-native.spec.ts --config playwright.finance.config.ts --workers=2`는
보험 브리지 14개와 기존 금융/계좌 브리지 20개, 총 **34개**를 통과했다.
브라우저 결과는 두 화면 크기의 JS 전달 모의시험이며 실제 Android 보호 화면·암호화·서버 권한의 증명이 아니다.
이 작업에서는 APK 조립과 실제 기기 시험을 실행하지 않았다. 운영 키 설정과 실기기의 화면 캡처·
Home/화면 꺼짐·30초 만료·앱 잠금·늦은 HTTP 응답 시나리오는 별도 검증 항목으로 남는다.
