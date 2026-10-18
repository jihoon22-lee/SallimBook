# Android 보관함 수명주기 — SB-028/029/030/032

관련 R-01/R-09/R-10/R-11/R-12/R-18/R-20, Issue #37/#38/#39/#41.
[암호 포맷과 공통 벡터](native-vault-crypto.md) 위에 네이티브 전용 전송·저장소·보호 화면을 연결했다.
서버 계약은 23개 operation이며 일반 카드의 `has_secret`은 현재의 삭제되지 않은 비밀 존재 여부다.
서버 권한·버전·멱등 계약은 [API 계약](../api-contract.md)을 따르고 아래 native 검증과 구분한다.

## Bridge와 서버 경계

`nativeVault.open({action, ...ID})`는 비공개 `NativeVaultActivity`를 열고
`completed` 또는 `cancelled`만 반환한다. 허용 action은 다음과 같다.

| 인자 | action |
|---|---|
| action만 | manage, setup, register-device, change-password, recover, rotate |
| cardId | view, edit, purge, cvc-view, cvc-edit, cvc-delete |
| memberId | share, revoke-member |
| offerId | accept-share, cancel-share |
| rotationId | resume-rotation, abort-rotation |

TS와 Kotlin은 모르는 인자·URL·헤더·버전·인증 bool을 거부한다. 암호·PAN·유효기간·복구코드·
암호문·wrapping·CVC는 bridge 입력이나 출력 타입이 아니다. 원래 일반 `request` 허용 경로도 확장하지 않는다.
메타데이터 `getVaultStatus`, `listVaultShares`, `getVaultRotation`만 생성 DTO의 엄격한 필드 투영으로
JS에 전달한다. 키 wrapping과 카드 envelope API는 private native 전송으로만 사용한다.
일반 카드 화면·PC 보관함 UI는 이 native 화면의 입력 흐름을 복제하지 않는다.

네이티브는 `/me`, 가계 구성원, 현재 활성 Android 기기, fresh vault status와 카드 metadata를
서버에서 확인한다. JS가 준 household/user/device/version은 받지 않는다. 기기 페이지·카드 목록은
최대 2,000개, 공유 페이지는 최대 200개, 회전 manifest는 카드 최대 2,000개/구성원 최대 2개로 검증한다.
다른 가계·구성원·대상·키 버전, 잘못된 cursor, 중복 ID, 모르는 필드를 거부한다.
서버 권한과 버전 검사가 최종 권한이며 네이티브 검사가 이를 대신하지 않는다.

`NativeVaultWire`는 고정 method/path/body/If-Match/Idempotency-Key를 만든다.
관리 작업은 서버의 최근 계정 비밀번호 재인증 조건을 사용하며 생체 성공을 step-up 증거로 보내지 않는다.
기존 재인증이 만료되면 같은 보호 화면에서 현재 계정 비밀번호를 다시 확인한다. 회전의 검증 위치는
동일한 원본 manifest와 키를 다시 확인한 경우에만 유지하며, 화면을 닫으면 폐기한다.
서버 실패의 원문 메시지·제출값은 표시하거나 반환하지 않고 알려진 코드와 로컬 문구만 쓴다.

처음 설정·암호 변경·복구·공유 생성/수락/취소·접근 철회·카드 변경/purge·회전 시작/준비/중단도
`REAUTHENTICATION_REQUIRED`와 `STEP_UP_REQUIRED`를 같은 native 화면에서 처리한다. 이미 만들어진
변경 요청은 엄격한 wire 검증을 거친 불변 복사본의 body·If-Match·Idempotency-Key만 유지하고,
준비된 raw HVK·새 HVK·복구코드·입력은 재인증 전에 지운다. 재인증 뒤 fresh household/member/user/device가
같은지 확인하고 사용자가 동일 요청을 명시적으로 다시 제출한다. 네트워크 실패 뒤에도 동일 요청을
수동 재시도하며 계정 인증이 다시 만료되면 같은 요청으로 재인증한다. 복구코드 보관 확인이 끝나지
않은 initialize/recover/prepare 요청은 이 경로에 보관할 수 없다.
회전 준비 재전송이 성공하면 staged 본인 wrapping을 기존·새 보관함 암호로 다시 여는 화면으로
이어지고, 지운 키로 다음 카드를 처리하지 않는다. recovery-wrap/share-wrap 등 요청 준비 중 인증이
만료되면 계정 재인증 뒤 원래 폼을 빈 입력으로 다시 열어 필요한 보관함 입력을 명시적으로 받는다.
잘못된 로그인 암호는 보관한 암호화 요청을 버리지 않지만 취소·화면 이탈·계정/기기 변경은 폐기한다.


`NativeVaultHttp`는 고정 HTTPS와 플랫폼 TLS 검증을 사용한다. 쿠키·리디렉션·캐시·HTTP 로그·
자동 인증 응답·자동 재전송이 없다. one-shot 본문과 OkHttp 후속 요청 취소를 함께 적용한다.
bearer는 긴 작업 시작 시 고정하지 않고 각 HTTP 직전에 같은 계정 executor의 private supplier로
확보한다. 남은 유효시간이 20초(HTTP 제한 15초 + 여유) 이하이면 먼저 refresh를 회전한다.
정상 만료가 가까운 토큰 때문에 기기 wrapping을 세션 철회처럼 지우지 않으며, 401 응답을 받은
변경 요청을 자동 재전송하지 않는다. refresh가 발급한 토큰이 이 여유보다 짧으면 유효 refresh는
보존하고 해당 vault 작업을 거절한다.
응답은 1MiB 이하의 strict UTF-8 JSON이며 중복 키·깊이·배열/객체 크기·실수가 포함된 숫자를 거부한다.
이미 Tink 전이 의존성으로 고정한 Gson 2.13.2를 직접 선언해 strict streaming reader를 사용한다.
[공식 Gson 릴리스](https://github.com/google/gson/releases/tag/gson-parent-2.13.2)를 확인했으며
추가 버전이나 별도 암호 라이브러리 그래프를 도입하지 않았다.

## 기기 키와 CVC

Device KEK는 Android Keystore AES-256-GCM, `setUserAuthenticationRequired(true)`,
`setUserAuthenticationParameters(0, AUTH_BIOMETRIC_STRONG)`과 등록 변경 시 무효화를 사용한다.
표준 플랫폼 BiometricPrompt의 **같은 요청에 연결된 동일 Cipher**를 확인하고 실제 `doFinal`이
성공한 뒤에만 HVK를 사용한다. 앱 잠금의 PIN 허용과 보관함 키 인증은 별개다.
키가 없거나 무효화됐다고 무보호 키를 만들지 않는다. 명시적 기기 등록·재등록에는 보관함 암호와
사용자 확인이 필요하다. 강력한 생체인증을 사용할 수 없을 때는 명시적 암호 입력으로 카드를 볼 수 있다.
이 암호 경로는 인증 없는 기기 키나 디스크의 평문 HVK를 만들지 않는다.

재등록·같은 카드의 CVC 수정은 기존 auth-per-use 키를 재사용하고 provider가 새 GCM nonce를
생성한다. prompt 준비·취소·실패는 기존 별칭과 암호문을 지우지 않으며 실제 인증 연산과
AtomicFile 저장이 성공한 뒤에만 기존 암호문을 갱신한다. 일시적 키 조회/초기화 오류에도
새 키를 만들거나 기존 값을 삭제하지 않는다. 영구 무효화된 기기 등록 삭제는 별도의 네이티브
확인을 받고, 플랫폼의 [KeyPermanentlyInvalidatedException](https://developer.android.com/reference/android/security/keystore/KeyPermanentlyInvalidatedException)을
확인한 경우에만 수행한다. 정상 키나 일시 오류에는 이 삭제를 거절한다. CVC는 명시적 로컬 삭제 후
직접 재입력할 수 있다. 이 삭제 작업 자체가 기기 재등록이나 인증 성공을 뜻하지 않는다.

[공식 Keystore Builder 계약](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder)은
Android 12~14의 unlocked-device-required 제약을 설명한다. 추가 `setUnlockedDeviceRequired(true)`는
API 35 이상에서 적용하고, 모든 지원 API에서는 strong auth-per-use 및 foreground/device-lock gate를 유지한다.
[CryptoObject 계약](https://developer.android.com/reference/android/hardware/biometrics/BiometricPrompt.CryptoObject)과
[Android 16 동작 변경](https://developer.android.com/about/versions/16/behavior-changes-all)을 대조했다.
StrongBox나 제조사별 하드웨어 보호 수준이 검증됐다는 뜻은 아니다.

로컬 HVK wrapping은 app ID·고정 origin·household/user/member/device ID·key version에 바인딩한다.
CVC는 별도 키·AAD를 사용하며 card ID와 **현재 secret envelope ID/revision**까지 바인딩한다.
파일은 noBackupFilesDir의 AtomicFile에 형식 byte·nonce·암호문만 저장한다. 키 원문·보관함 암호·
복구코드는 저장하지 않는다. 파일명과 키 별칭은 scope digest를 사용하며 카드 일반 metadata 수정만으로
CVC를 지우지 않는다. PAN 수정·비밀 purge·현재 키 변경은 stale CVC를 폐기한다.

로그아웃·세션/기기 접근 상실 시 전용 보관함 별칭과 파일을 제거하고 앱을 잠근다.
fresh 상태에서 membership 철회·계정/기기/scope 변경을 발견하면 이전 로컬 자료를 폐기한다.
기기 키 원본을 다른 기기로 복사하지 않으며 오프라인 사본의 원격 삭제를 보장하지 않는다.
allowBackup=false, fullBackupContent=false와 cloud/device-transfer 제외 규칙을 유지한다.

CVC는 사용자가 native 화면에서 직접 입력하는 3~4자리만 받는다. HTTP serializer·서버 schema·
웹 입력·백업·내보내기 경로를 만들지 않았다. 입력·열람은 코드의
`LOCAL_CVC_ACCEPTANCE_VERIFIED=false`로 비활성화되어 있으며 JS/Intent/server/설정 저장소의
플래그로 활성화할 수 없다. 기존 로컬 자료 삭제는 별도로 가능하다.
보안 검토와 두 Galaxy 실기기 검증 후 gate를 실제로 완료해야 R-12와 v1 출시를 완료할 수 있다.
현재 gate 미완료를 숨겨 완료로 처리하지 않는다.

## 화면과 작업 수명

Activity는 exported=false, 정확한 action/ID extras, FLAG_SECURE, 자동완성·content capture·
저장 상태·키보드 학습·클립보드/문맥 메뉴 억제를 적용한다. 암호·PAN·복구코드·CVC를 Bundle,
Intent result, 일반 React 상태나 Query cache에 넣지 않는다. 화면 재생성은 기존 작업을 복원하지 않는다.
기기에 등록된 인증수단을 검증하며 특정 구성원의 손가락을 식별한다고 해석하지 않는다.

같은 요청 세대·resumed·focus·기기 잠금·앱 잠금·현재 세션 세대를 확인한다.
일반 초점 이탈·pause·화면 꺼짐·잠금·취소·파괴는 작업을 취소하고 비밀을 지운다.
BiometricPrompt가 초점을 소유하는 동안만 대기 예외가 있으며 성공 후 1초 안의 초점 복귀와
실제 Cipher 연산을 요구한다. prompt 취소는 terminal callback 전까지 새 인증을 막는다.
작업 한도 60초, 보호 정보 표시 최대 30초는 monotonic clock 기준이며 재조회로 연장하지 않는다.

worker가 소유한 입력과 키는 작업 종료 경로에서 지운다. 늦은 KDF/HTTP 결과는 화면에 전달하지 않고
폐기한다. 취소 버튼·Back·앱 잠금은 진행 중 요청에도 적용된다. 생체 사용 후에는 서버의 현재 scope와
key-check/현재 카드 envelope를 다시 확인해 표시·저장 성공을 결정한다.
JCA/Tink·JVM/Android의 내부 복사본과 native 렌더링 문자열의 완전 메모리 소거는 보장하지 않는다.

## 설정·공유·복구·회전

새 보관함 암호는 12 Unicode codepoint 이상, strict UTF-8 1,024byte 이하다. 임의 trim·Unicode 정규화가
없으며 기존 암호 해제에는 원래 bytes를 사용한다. 로그인 암호·짧은 앱 PIN 재사용을 안내하지 않는다.
처음 설정·복구·회전 준비는 새 복구코드를 한 번 표시하고 오프라인 보관을 명시적으로 확인한 뒤
서버 initialize/recover/prepare를 수행한다. 코드가 표시되는 동안에도 30초·이탈 잠금을 적용한다.

공유는 기존 구성원이 신뢰 기기에서 상대의 별도 암호로 wrapping을 준비하고 상대가 본인 계정에서
키 확인 후 수락한다. 공유 취소·구성원 접근 철회를 제공하며 철회 뒤 키 회전 필요 상태를 표시한다.
복구는 계정 접근과 보관함 복구를 구분하고 member/recovery wrapping을 함께 바꾼다.
복구코드 유출 대응에는 HVK 회전도 필요함을 안내한다.

회전은 서버가 예약한 새 버전과 고정된 카드/구성원 manifest를 따른다. 유지할 구성원 모두의 새 암호를
신뢰 기기에서 받아 wrapping·key-check·새 recovery wrapping을 먼저 준비한다. 카드 하나씩 기존 키로
확인한 내용을 새 키로 암호화하고 현재 rotation version을 사용한다. 이미 준비된 카드는 기존/새
평문이 일치하는지 native 내부에서 확인한다. 전체 준비 manifest 확인 뒤 원자 finalize를 요청한다.

한 foreground 작업은 카드 한 개만 확인·준비하고 다음 카드는 새 60초 작업 gate에서 이어간다.
각 단계는 현재 계정·scope·기존/새 키 확인을 반복하며, Activity 안의 검증 cursor는 같은 회전 ID,
키 버전, 카드 원본 envelope/revision/last-four, 구성원 membership version에만 유효하다.
이미 준비된 카드도 한 번씩 대조한 뒤 다음 단계로 전진하므로 카드가 많아도 매 작업마다 앞부분을
처음부터 반복하지 않는다. 마지막 단계는 전체 로컬 검증 완료와 fresh 서버 준비 상태를 모두
요구한다. 취소/화면 종료는 키와 cursor를 폐기한다. 이후 재개는 서버 staged 키로 복원하고 처음부터
검증하되 여러 제한된 작업으로 계속 전진한다. finalize 재시도 성공도 현재 키와 key-check로 확인한다.

서버의 최근 로그인 5분 제한에 걸리면 두 HVK를 즉시 지우고 같은 네이티브 화면에서 현재 계정의
로그인 암호로 기존 `/auth/native/reauthenticate`를 호출한다. refresh를 재인증으로 간주하거나 서버
제한을 연장하지 않는다. 그 뒤 기존·새 보관함 암호를 별도로 다시 입력받아 같은 두 키를 확인한다.
이 동안 원본 manifest에 묶인 카드 검증 cursor, 안전한 계정/기기 식별값, 두 무작위 HVK의 SHA-256
지문, 암호문으로만 된 동일 요청은 native 메모리에 유지할 수 있다. raw HVK·암호는 유지하지 않는다.
키 지문은 같은 키로 재개하는지 대조하는 용도이며 디스크·JS·로그에 저장하지 않고 cursor 폐기 시
지운다. 재인증 후 계정·기기·키 버전·원본 snapshot·두 키가 모두 같아야 앞서 검증한 카드 다음부터
이어가므로 많은 준비된 카드 때문에 5분을 넘긴 경우도 처음부터 반복하지 않고 finalize할 수 있다.
재인증 중 화면 이탈도 예외 없이 전체 진행 정보를 폐기한다.

전송 결과가 불명확하면 Activity가 살아 있는 동안 같은 command body·version·Idempotency-Key를
보관해 사용자의 재시도에 사용한다. 자동 재전송하지 않는다. 프로세스/화면 종료 후에는 서버 상태를
다시 읽고 staged 본인 wrapping·새 암호로 새 HVK를 복원해 재개한다. 새 키를 무조건 다시 만들지 않는다.
abort는 기존 current 키를 유지한다. 현재 키가 바뀌면 이전 기기 wrapping/CVC는 폐기하고 재등록한다.

카드 번호 수정은 새 current envelope로 교체하며 이전 암호문은 서버에 보존될 수 있다.
명시적 purge만 current·retired·aborted·replaced의 모든 해당 카드 ciphertext를 NULL로 폐기한다.
일반 카드·nonce·revision·감사 이력과 이미 만들어진 백업은 별개다.

## 검증과 남은 인수

```bash
pnpm typecheck
pnpm android:sync
JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ANDROID_HOME=/home/jihoon/Android/Sdk apps/client/android/gradlew -p apps/client/android --no-daemon --max-workers=2 :app:testDebugUnitTest :app:assembleDebug :app:compileReleaseKotlin
TMPDIR=/home/jihoon/.cache/sallimbook pnpm --filter @sallimbook/client exec playwright test vault-native-bridge.spec.ts documents-native-bridge.spec.ts --config playwright.vault-native.local.config.ts --workers=2
```

2026-10-18 WSL: typecheck·Android sync·JVM **270개**(실패·오류·건너뜀 0)·debug APK·release Kotlin을 통과했다.
신규 wire 7개·실제 HTTP/JSON 6개·workflow/local AAD 8개를 포함하며, 기존 결제 연결 fixture의
필수 `has_secret`도 함께 맞췄다. debug 병합 manifest의 native Activity가 exported=false이고
공통 시험 fixture가 APK assets에 없음을 확인했다. 이는 실제 Keystore 인증 실행 결과가 아니다.

브라우저 **52개**(신규 vault 28개 + 문서 24개)가 통과했다. 기본 설정의 baseURL/webServer만
18754로 바꾼 임시 config를 사용했고 Vite 중지·포트 반환을 확인한 뒤 config를 제거했다.
브라우저는 status/ID 전달과 실패·취소·무우회만 모의 검증하며 실제 OS/Keystore/보안 화면 증명이 아니다.

독립 검토 후 기기 키 보존 회귀 6개를 추가해 JVM **276개**(실패·오류·건너뜀 0), debug APK,
release Kotlin을 다시 통과했다. 실제 JCA AES-GCM의 기존 키·암호문을 보존한 prompt 폐기,
새 nonce, 일시적 키 오류에서 교체 금지, 정상 키 재설정 거절, 명시적 영구 무효화 삭제 정책을 검사한다.
이 JVM adapter 검사는 Android Keystore나 AtomicFile의 실기기 동작을 대신하지 않는다.
TS 브리지 계약 변경이 없으므로 위 브라우저 52개 결과를 유지하고 이번 Kotlin 수정 후 재실행하지 않았다.

요청별 bearer 유효시간 후속 수정은 fake-clock/지연/401 무재전송/취소 회귀 4개를 포함해
JVM **280개**(실패·오류·건너뜀 0), debug APK, release Kotlin을 통과했다.

회전 진행 분할 후 JVM **287개**(실패·오류·건너뜀 0), debug APK, release Kotlin을 통과했다.
추가 7개는 요청당 1초를 가정한 fake-clock에서 준비/미준비 카드 120개가 전체 60초를 넘겨도
개별 작업 제한을 지키며 finalize 가능한 상태에 도달하는지, 재개 시 재검증, source/member 변경,
완료 전 finalize 거절, 중복/과다 카드와 폐기된 cursor 거절을 검사한다. 실제 지연 네트워크나
Android Activity instrumentation을 실행했다는 뜻은 아니다.

worker 결과의 마지막 소비에서도 완료 시한·foreground를 확인하고 실패하면 callback 전에 결과를
폐기한다. 앞선 유효성 검사와 마지막 완료 사이 정확히 60초 경계를 넘는 fake-clock 및 최종 화면
상태 변경 회귀를 추가해 JVM **289개**, debug APK, release Kotlin을 통과했다(실패·오류·건너뜀 0).

5분 관리 인증 만료 후 연속성 정책을 추가해 JVM **291개**, debug APK, release Kotlin을 통과했다
(실패·오류·건너뜀 0). fake-clock 120개 카드 흐름에서 5분 만료를 반복하고 원본 키 배열을 지운 뒤
계정 재인증·같은 키 복원을 가정해 cursor를 이어가며, 다른 키/폐기된 cursor는 거절한다.
이 검사는 실제 서버 재인증 응답이나 Android 입력 화면을 구동한 통합시험이 아니며 실기기 인수에
대량 회전 중 최근 로그인 만료·암호 재확인·취소·다른 계정/키 변경 실패 시나리오를 추가한다.

PR #79의 공통 관리 재인증 후속 수정은 typecheck·Android sync·JVM **299개**(실패·오류·건너뜀 0),
debug APK·release Kotlin을 통과했다. 신규 8개는 14종 변경 요청의 동일 bytes/version/Idempotency-Key,
반복 재인증·취소·계정/기기 변경, raw 키 2개와 복구코드 소거, 미확인 복구코드 요청 거절,
원본 mutable body와 보관 요청 분리, 보호 조회의 빈 폼 재진입 정책을 검사한다.
TS/bridge 계약은 바꾸지 않아 기존 브라우저 52개 결과를 유지하며 이번 수정에서 다시 실행하지 않았다.
이 JVM 검사는 Android Activity 입력·실제 서버 재인증 통합시험을 대신하지 않는다. 실기기에서는
initialize/recover/change-password/share/revoke/rotation-start/prepare의 5분 만료, 잘못된 로그인 암호,
동일 요청 재전송·네트워크 실패·취소와 prepare 성공 후 기존/새 키 재입력도 추가 확인해야 한다.

실기기 미실행 항목: 최초 등록/암호화/별도 열람, 지문 추가·삭제·잠금 방식 제거·키 무효화,
기존 등록/CVC가 있는 재저장 prompt 취소·오류 뒤 원래 값의 열람, 저장 실패 뒤 기존 암호문의 복원,
정상/일시 오류 키의 재설정 거절과 영구 무효화 확인·명시 삭제·재등록,
인증 취소/오류/늦은 성공/누락된 terminal callback, 30초 만료·초점 복귀·회전·Home·화면 꺼짐,
프로세스 종료 중 initialize/recover/prepare/stage/finalize 재개, 두 구성원 공유와 철회,
CVC 입력·저장·수정·purge·키 변경·로그아웃·재설치/기기 이전, 프록시·로그·backup·bridge 무유출,
FLAG_SECURE의 스크린샷/녹화/최근 앱/외부 디스플레이 보호다. 실제 개인 정보 대신 합성 데이터로 검증한다.

SB-039의 [합성 CVC 인수 화면](native-security-proof.md#sb-039-실제-저장-경로를-사용하는-합성-cvc-인수-화면)은
debug 빌드에서 실제 `NativeVaultStore`의 강한 인증별 Keystore 키, AAD, `AtomicFile` 저장/실패 복원 경로를
전용 합성 namespace로 실행하도록 추가했다. 일반 CVC gate는 계속 닫혀 있고 release의 대응 gate에는
활성화 상태나 실패 주입이 없다. 기본 저장 디렉터리·키 별칭·API·JS 계약·서버 스키마·백업 정책은 변경하지 않았다.
기기 instrumentation APK에는 gate/격리/미인증 키 사용 거절 7개와 기존 WebView 4개를 포함한다.
실제 두 Galaxy에서 인증/저장/취소/실패/키 무효화와 기기 이전을 실행한 결과는 아직 없다.
