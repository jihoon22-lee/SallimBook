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
기존 재인증이 만료되면 화면을 닫고 계정 재인증 후 다시 시작하거나 회전을 재개해야 한다.
서버 실패의 원문 메시지·제출값은 표시하거나 반환하지 않고 알려진 코드와 로컬 문구만 쓴다.

`NativeVaultHttp`는 고정 HTTPS와 플랫폼 TLS 검증을 사용한다. 쿠키·리디렉션·캐시·HTTP 로그·
자동 인증 응답·자동 재전송이 없다. one-shot 본문과 OkHttp 후속 요청 취소를 함께 적용한다.
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

실기기 미실행 항목: 최초 등록/암호화/별도 열람, 지문 추가·삭제·잠금 방식 제거·키 무효화,
인증 취소/오류/늦은 성공/누락된 terminal callback, 30초 만료·초점 복귀·회전·Home·화면 꺼짐,
프로세스 종료 중 initialize/recover/prepare/stage/finalize 재개, 두 구성원 공유와 철회,
CVC 입력·저장·수정·purge·키 변경·로그아웃·재설치/기기 이전, 프록시·로그·backup·bridge 무유출,
FLAG_SECURE의 스크린샷/녹화/최근 앱/외부 디스플레이 보호다. 실제 개인 정보 대신 합성 데이터로 검증한다.
