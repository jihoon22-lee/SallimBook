# SB-008 · 디버그 네이티브 보안 검증

관련 요구사항은 R-10·R-11·R-12다. [SB-008](../../planning/ISSUES.md#sb-008--실기기-지문keystore네이티브-보안-화면-poc)의 실기기 완료 조건은 아래 미실행 항목이 검증될 때까지 열어 둔다.

이 문서는 공개 합성 문자열로 Android 생체 인증과 실제 Keystore 키 연산을 확인하기 위한 절차다.
최종 카드 보관함, 서버 로그인, CVC 입력·저장 기능을 구현하거나 검증한 문서가 아니다.
현재 실기기 시험 결과는 모두 **미실행**이다. 빌드와 JVM 정책 테스트만으로 보안 게이트를 완료하지 않는다.
사용자 결정(2026-10-17)에 따라 실기기 연결은 전체 기능 개발 이후에 수행한다.
그동안 소스·자동 검증을 진행하고 아래 Galaxy 시험표와 출시 보안 게이트는 미완료로 유지한다.

## 검증 범위와 데이터

검증 화면은 `apps/client/android/app/src/debug/`에만 존재하며 릴리스 소스에 포함하지 않는다.
AndroidX Biometric `1.1.0`을 `debugImplementation`으로만 연결한다.
Activity에는 WebView, JS bridge, 사용자 입력, 네트워크 호출, 파일 저장, 클립보드와 자체 로그 출력이 없다.
Intent의 URL·extras·임의 암호문도 입력받지 않는다. 앱의 일반 보관함 어댑터는 계속 사용 불가 상태다.

유일한 평문은 소스에 공개된 다음 합성 문자열이다. 실제 카드번호·CVC·개인정보로 바꾸지 않는다.

```text
SALLIMBOOK PUBLIC SYNTHETIC PROOF V1 - NOT A CARD SECRET
```

검증 키 별칭은 `sallimbook.debug.sb008.disposable-proof.v1`이며 실제 보관함 키와 공유하지 않는다.
키는 Android Keystore의 AES-256-GCM 키로 생성하고, 매 사용 시 강력한 생체 인증을 요구한다.
`setUserAuthenticationParameters(0, AUTH_BIOMETRIC_STRONG)`과 등록 변경 시 무효화를 설정한다.
암호화와 복호화는 서로 다른 `BiometricPrompt.CryptoObject` 요청이며, 성공 콜백만으로 표시하지 않는다.
요청에 연결된 동일 `Cipher`의 실제 `doFinal` 결과를 검증한 뒤 네이티브 TextView에 표시한다.
PIN·약한 생체 인증·무보호 키로 자동 전환하지 않는다.

암호문은 Activity 메모리에만 두며 화면 재생성·프로세스 종료 시 사라진다.
검증 키는 등록 변경에 따른 무효화를 확인할 수 있도록 유지되며, 명시적인 삭제 버튼 또는 앱 제거로 폐기한다.
무효화된 키를 자동 재생성하지 않는다. 평문 표시 종료와 암호문·키 삭제는 서로 다른 동작이다.
표시는 `SystemClock.elapsedRealtime` 기준 최대 30초이며 화면 이탈·초점 상실·화면 잠금·회전 시 가린다.
`FLAG_SECURE`와 메모리 참조 정리는 검증할 보호 수단이며, 외부 촬영이나 메모리 완전 소거를 보증하지 않는다.

## 빌드와 실행

저장소 루트에서 지정한 JDK와 SDK로 빌드한다. 기존 SDK·ADB·서버 설정은 바꾸지 않는다.

```bash
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export ANDROID_HOME="$HOME/Android/Sdk"
pnpm android:build
```

APK는 `apps/client/android/app/build/outputs/apk/debug/app-debug.apk`이며 개발 앱 ID는
`io.github.jihoon22lee.sallimbook.debug`다. 정식 서명·배포용 APK가 아니다.

연결할 기기를 확인하고 아래 `DEVICE_SERIAL`을 실제 대상의 serial로 바꾼다.
이 문서 작성 시 S25 Ultra·S24 Ultra에 아래 명령을 실행하지 않았다.

```bash
adb devices -l
adb -s DEVICE_SERIAL install -r apps/client/android/app/build/outputs/apk/debug/app-debug.apk
adb -s DEVICE_SERIAL shell am start -n io.github.jihoon22lee.sallimbook.debug/io.github.jihoon22lee.sallimbook.debugproof.SecurityProofActivity
```

Activity는 디버그 manifest에만 선언되며 `android.permission.DUMP`로 보호한다.
일반 앱에서 실행하는 경로와 런처 메뉴는 제공하지 않는다. ADB shell의 실행 권한은 각 대상 기기에서도 확인한다.

화면의 순서는 다음과 같다.

1. **검증 키 생성**을 누른다. 기존 키가 있으면 덮어쓰지 않는다.
2. **인증 후 합성 문자열 암호화**를 누르고 기기에 등록된 강력한 생체 인증을 수행한다.
3. **인증 후 최대 30초 표시**를 누르고 다시 인증한다. 복호화된 공개 합성 문자열만 표시해야 한다.
4. **지금 가리기** 또는 아래 실패 시나리오를 수행한다. 다시 표시하려면 별도 인증이 필요하다.
5. 검증을 마치면 **검증 키와 합성 암호문 삭제**를 누른다.

생체 인증은 기기에 등록된 인증수단의 검증이며, 특정 구성원 한 사람의 손가락을 식별하는 수단이 아니다.

## 자동 검사

정책 테스트는 요청 수명과 표시 시간만 검증한다. 실제 Keystore·생체 인증·캡처 차단을 모의 성공으로 대체하지 않는다.

```bash
cd apps/client/android
./gradlew --no-daemon :app:testDebugUnitTest :app:assembleDebug
./gradlew --no-daemon :app:compileReleaseKotlin :app:processReleaseMainManifest
./gradlew --no-daemon :app:dependencies --configuration releaseRuntimeClasspath
```

정책 테스트는 암호화 후 미표시, 별도 복호화 요청, 정확한 30초 만료, 반복 조회에 의한 시간 연장 방지,
중복 요청 차단, 잠금 뒤 늦은 콜백 차단, 재생성 초기 잠금, 단조 시간 역행 시 차단을 포함한다.
추가로 초점 복귀 전 키 연산 금지, 최대 1초 초점 복귀 대기, 시간 초과, 취소 완료 콜백 전 새 인증 금지,
이전 요청 콜백과 새 요청 분리, 대기 중 일시정지·화면 잠금을 검증한다.
초점 대기 잔여 시간 확인과 실제 키 연산 허용 검사 사이에서 기한이 만료되는 경계도 검사한다.
만료된 요청에는 재시도를 예약하지 않고 잠금 안내와 버튼 상태를 즉시 갱신한다.
릴리스 검사는 `SecurityProofActivity`·`ProofDisplayPolicy`가 릴리스 클래스와 병합 manifest에 없고,
`androidx.biometric:biometric`이 릴리스 runtime classpath에 없는지 확인한다. 서명·릴리스 배포는 수행하지 않는다.

후속 앱 잠금(Refs #18, #38)은 플랫폼 BiometricPrompt를 사용하므로 production manifest에 `USE_BIOMETRIC`을 선언한다.
아래 2026-10-17 검증의 권한 미포함 결과는 당시 빌드에 대한 기록이다. 앱 잠금 도입 후에도 디버그 검증 Activity/정책과 AndroidX Biometric 의존성은 릴리스에 포함하지 않는다.
디버그 합성 검증 Activity는 앱 잠금 화면의 별도 예외이며 일반 계정·금융 API 잠금을 해제하지 않는다.

2026-10-17 WSL의 분리된 `feat/SB-008-keystore-proof` 작업 트리에서 다시 확인한 결과는 다음과 같다.
JDK 21·compile SDK 36을 사용했으며, 이는 아래 실기기 검증표와 별개의 결과다.

| 검사 | 결과 |
|---|---|
| `pnpm install --frozen-lockfile`, `pnpm android:sync` | 성공. 고정 의존성 설치·웹 타입 검사와 빌드·Android 자산 동기화 |
| `:app:testDebugUnitTest :app:assembleDebug` | 성공. 정책 테스트 19개, 실패·오류·건너뜀 0개. 개발 APK 생성 |
| `:app:compileReleaseKotlin :app:processReleaseMainManifest` | 성공. 릴리스 컴파일 클래스·병합 manifest에 검증 Activity와 정책 클래스 없음. `USE_BIOMETRIC`·`USE_FINGERPRINT` 권한 없음 |
| `releaseRuntimeClasspath` | `androidx.biometric:biometric` 없음 |
| 디버그 병합 manifest | 검증 Activity, DUMP 권한 보호, USE_BIOMETRIC 선언 확인 |
| 별도 작성자의 소스 리뷰 | 초점 확인 후 실제 Cipher 사용·표시, 취소 완료 전 재인증 차단을 확인. 차단 사유 없음. 실기기 보안 판정은 아님 |
| 문서·diff 검사 | `refresh_docs_manifest.py --add docs/testing/native-security-proof.md`로 문서 목록 등록. 문서 검증·도구 테스트·diff 검사 통과 |

정책 테스트 수는 `app/build/test-results/testDebugUnitTest/TEST-*.xml`에서 확인했다.
릴리스 제외 여부는 `app/build/tmp/kotlin-classes/release/`,
`app/build/intermediates/merged_manifests/release/processReleaseManifest/AndroidManifest.xml` 및
`releaseRuntimeClasspath` 출력으로 대조했다. 디버그의 대응 산출물에는 검증 클래스와 화면이 존재한다.
이 경로들은 `apps/client/android/` 기준이다. 릴리스 서명·APK 배포와 실기기 명령은 실행하지 않았다.

## 실기기 검증표

각 셀은 해당 기기에서 실행한 뒤 결과·Android 버전·빌드 식별자·확인 일자를 기록해야 한다.
현재 자동 검사 결과를 아래 수동 검증 결과로 복사하지 않는다.

| 시나리오 | 기대 결과 | Galaxy S25 Ultra · OS 미확인 | Galaxy S24 Ultra · Android 16 |
|---|---|---|---|
| 최초 키 생성·암호화·별도 복호화 | 두 번의 인증과 실제 키 연산 후에만 합성 문자열 표시 | 미실행 | 미실행 |
| 미등록·미지원·약한 생체 인증만 존재 | 사용 불가 안내, PIN 또는 약한 방식으로 자동 전환 없음 | 미실행 | 미실행 |
| 인증 취소·실패·잠금 | 평문 미표시, 뒤늦은 성공 콜백으로 표시되지 않음 | 미실행 | 미실행 |
| 인증 대기 중 Home·화면 잠금·다른 Activity | 요청 취소, 복귀해도 잠금 유지 | 미실행 | 미실행 |
| 표시 중 Home·알림창·화면 잠금 | 즉시 가림, 복귀 후 별도 인증 필요 | 미실행 | 미실행 |
| 인증 호출의 동기 예외·종료 콜백 누락 | CANCELLING에서 재인증 차단을 유지. 종료 콜백이 없으면 Activity 재시작이 필요할 수 있음 | 미실행 | 미실행 |
| 인증 대기·표시 중 회전 | 재생성 후 잠금, 저장 상태에서 평문 복원 없음 | 미실행 | 미실행 |
| 30초 경과·시계 변경 | 벽시계 변경과 무관하게 단조 시간 30초 이내 가림 | 미실행 | 미실행 |
| 지문 추가·전체 삭제·기기 잠금 해제 방식 제거 | 기존 키 사용 불가 또는 무효화 안내, 자동 키 재생성 없음 | 미실행 | 미실행 |
| 앱 강제 종료·다시 실행 | 평문과 메모리 암호문 복원 없음 | 미실행 | 미실행 |
| 재설치·기기 이전 | 이전 검증 키·암호문으로 열람되지 않음 | 미실행 | 미실행 |
| 스크린샷·화면 녹화·최근 앱·외부 화면 | FLAG_SECURE 적용 및 제조사별 노출 여부 확인 | 미실행 | 미실행 |
| 클립보드·로그·네트워크·bridge·백업 점검 | 합성 검증 데이터 전송·복사·저장 경로 없음 | 미실행 | 미실행 |
| 일반 앱에서 검증 Activity 실행 시도 | DUMP 권한 없이 실행 거부 | 미실행 | 미실행 |

검사는 합성 검증 앱 프로세스로 한정한다. 증거에는 성공/실패, 시각, 빌드·기기 식별용 메타데이터만 남기고
기기의 다른 앱이나 실제 개인정보가 포함된 원본 로그·스크린샷을 이슈에 첨부하지 않는다.
실패가 있으면 SB-008 완료로 표시하지 말고 실패 시나리오와 재현 조건을 기록한다.

## 공식 근거

- [AndroidX Biometric 릴리스와 안정 버전](https://developer.android.com/jetpack/androidx/releases/biometric)
- [BiometricPrompt와 CryptoObject](https://developer.android.com/identity/sign-in/biometric-auth)
- [Keystore 인증 매개변수·등록 변경 무효화](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder)
- [ADB shell의 DUMP 권한 선언](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/packages/Shell/AndroidManifest.xml)
