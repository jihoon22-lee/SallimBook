# Android 보관함 암호·수명 경계 — SB-028/029/032

관련 요구사항 R-09/R-10/R-11/R-18/R-20, Issue #37/#38/#41.
이 단계는 [v1 포맷](../adr/vault-format-v1.md)의 Android 암호 codec과 순수 수명 정책이다.
서버 API 연결, 실제 Keystore 키, 카드 입력·표시 화면과 CVC 저장은 아직 이 checkpoint에 포함하지 않는다.
보관함의 출시 보안 게이트와 Galaxy 실기기 검증을 완료한 결과가 아니다.

## 암호 구현과 의존성

`NativeVaultCrypto`는 플랫폼 JCA `AES/GCM/NoPadding`, `PBKDF2WithHmacSHA256`,
`SecureRandom`을 사용한다. recovery HKDF는 **Tink Android 1.24.0**의
`Hkdf.computeHkdf("HmacSHA256", ...)`에 위임한다. 자체 암호 알고리즘이나 HKDF 조합을 작성하지 않는다.
Tink의 keyset·저장소·전역 설정은 사용하지 않는다.

[공식 1.24.0 릴리스](https://github.com/tink-crypto/tink-java/releases/tag/v1.24.0),
[게시된 Android POM](https://repo.maven.apache.org/maven2/com/google/crypto/tink/tink-android/1.24.0/tink-android-1.24.0.pom),
[고정 태그의 HKDF 구현](https://github.com/tink-crypto/tink-java/blob/v1.24.0/src/main/java/com/google/crypto/tink/subtle/Hkdf.java),
[공식 Java/Android 지원 범위](https://developers.google.com/tink/setup/java)를 대조했다.
릴리스 문서는 1.24.0을 명시하며 setup 본문은 1.23.0을 예로 든다. 의존성에는 정확한 1.24.0을 고정했다.
공식 Android 지원 하한은 API 24이며 저장소의 minSdk는 30이다. 게시된 HKDF class의 bytecode major는
55(Java 11)이고 빌드 JDK는 21이다. 이는 실제 Android 런타임·기기 호환 시험을 대체하지 않는다.

`app/gradle.lockfile`에서 Tink 1.24.0과 전이 의존성을 고정한다.
POM의 annotation-jvm 1.8.2는 기존 그래프의 1.10.0으로 해석되고, jsr305 3.0.2,
gson 2.13.2, error_prone_annotations 2.41.0이 해당 앱 classpath에 포함된다.
Android POM은 protobuf나 Conscrypt를 새로 요구하지 않는다. 기존 Gradle 시험 도구의
별도 classpath에 있는 구버전 의존성을 앱 runtime으로 해석하지 않는다.

보관함 암호는 CharArray로 받고 잘못된 surrogate·최대 1,024 UTF-8 bytes 초과를 거부한다.
원래 공백·결합 문자·Unicode를 그대로 보존하고 trim·정규화·대소문자 변경을 하지 않는다.
PBKDF2 전에 strict UTF-8 인코딩을 검증하고 임시 bytes와 `PBEKeySpec` 암호를 지운다.
[Android PBKDF2 provider의 UTF-8 구현](https://android.googlesource.com/platform/prebuilts/fullsdk/sources/+/refs/heads/androidx-constraintlayout-release/android-35/com/android/org/bouncycastle/jcajce/provider/symmetric/PBEPBKDF2.java)을 확인했다.
암호 길이 하한 등 새 설정 UI 정책은 이후 native 화면에서 별도로 적용해야 한다.

AAD와 고정 길이 payload는 공통 포맷을 따른다. UUID canonical 형태, 양의 안전 정수 버전,
PBKDF2 600,000~2,000,000회, salt/nonce/key/암호문 길이와 canonical unpadded base64url을 검증한다.
카드 payload에는 숫자·Luhn·오른쪽 NUL padding·유효한 만료 월/연도만 허용한다.
실제 암호화마다 새 랜덤 nonce를 만들며 서버의 nonce 중복 거부를 대신하지 않는다.
클라이언트의 서버 재시도/충돌 처리와 실제 API envelope 검증은 후속 연결 단계에 해당한다.

복호화는 `doFinal`의 인증 tag 확인 뒤 완성된 payload만 처리한다. 오류에는 고정 enum만 두고
제출 값·provider 메시지·cause를 담지 않는다. 민감 객체의 `toString`은 redacted이고 명시적 폐기
메서드가 있다. 사용자가 소유한 key/password 버퍼는 호출자가 종료·실패·취소 경로에서 지워야 한다.
JCA/Tink 내부 복사본과 JVM/Android 문자열·렌더링 메모리의 완전 소거를 보장하지 않는다.

## 수명 정책

`NativeVaultLifetime`에는 비밀과 키가 없고 인증 권한도 없다. 실제 화면의 resumed·focus·기기 잠금·
앱 잠금 상태와 단조 시간을 받아 작업 세대·취소·표시 만료만 결정한다.
worker는 초점 이탈이나 잠금 뒤 늦은 결과를 사용할 수 없다. 생체 prompt가 초점을 갖는 동안에는
대기할 수 있지만 실제 Cipher 사용은 같은 요청의 성공 후 초점이 1초 안에 돌아온 경우로 제한한다.
인증 대기는 60초, 복호화된 값 표시는 최대 30초이며 재조회로 연장되지 않는다.
취소 중 prompt는 terminal callback 전까지 다음 요청을 막고, 이전 요청의 callback을 무시한다.

실제 production 호출자는 반환된 **동일 CryptoObject Cipher**와 실제 `doFinal`을 확인한 뒤에만
완료를 기록해야 한다. 정책의 bool이나 prompt 성공만으로 복호화했다고 해석하면 안 된다.
[CryptoObject 계약](https://developer.android.com/reference/android/hardware/biometrics/BiometricPrompt.CryptoObject)과
[Keystore 인증 매개변수](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder)는
후속 production Keystore 설계에서도 적용한다. SB-008의 debug 전용 Activity·AndroidX Biometric 의존성을
release로 옮기지 않았다.

## 자동 검증 범위

공통 [공개 합성 벡터](../../packages/test-fixtures/vault-v1.json)를 test에서 직접 읽는다.
고정 시험 key/nonce는 앱의 운영 기본값이나 assets에 포함하지 않는다. 두 구성원의 독립 PBKDF2,
한국어·emoji·결합 문자·앞뒤 공백, card/key-check/member/recovery AAD와 암호문을 대조한다.
태그·nonce 각 byte 변조, 다른 가계·카드·구성원·버전·generation·반복 수·salt·암호,
비정규 base64url·잘못된 Unicode·길이·payload를 거부한다.
수명 검사는 취소·늦은 callback·초점 복귀·정확한 만료·단조 시간 역행을 포함한다.

```bash
pnpm install --frozen-lockfile
pnpm android:sync
JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ANDROID_HOME=/home/jihoon/Android/Sdk apps/client/android/gradlew -p apps/client/android --no-daemon --max-workers=2 :app:dependencies --write-locks
JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ANDROID_HOME=/home/jihoon/Android/Sdk apps/client/android/gradlew -p apps/client/android --no-daemon --max-workers=2 :app:testDebugUnitTest :app:assembleDebug :app:compileReleaseKotlin
```

2026-10-18 WSL 검증: 위 명령이 모두 통과했다. 신규 암호 시험 **11개**, 수명 시험 **11개**를
포함한 JVM **248개**가 실패·오류·건너뜀 없이 통과했다. 디버그 APK 조립과 release Kotlin 컴파일도
성공했다. APK ZIP 목록에 공통 `vault-v1.json` fixture가 없음을 확인했고 문서/manifest·diff 검사를
통과했다. 이 checkpoint는 bridge·웹 UI·API를 변경하지 않아 브라우저와 DB 시험을 새로 실행하지 않았다.

실제 Keystore·지문 등록 변경·프로세스 종료·화면 캡처·기기 이전·네트워크/backup/bridge 유출 시험은
미실행이다. 이후 CVC 구현은 보안 검토·실기기 검증 전 기본 비활성 정책을 유지해야 하며,
이 제한을 숨긴 채 R-12 또는 v1 출시 완료로 표시하지 않는다.
