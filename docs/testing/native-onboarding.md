# Android 처음 시작·배우자 연결 검증

Refs #87, R-01/R-02. API 계약의 첫 가계 생성과 배우자 연결을 Android 네이티브 화면에 연결한다.
기존 로그인·초대 API와 화면은 유지한다. 이 문서는 구현 경계와 자동 검사, 아직 실행하지 않은
기기 인수를 구분한다. 공통 계약은 [네이티브 브리지](../native-bridge-contract.md)와
[보안 정책](../security-authentication.md)을 따른다.

## 사용자 흐름

로그인 전 Android 가림 화면에서 서버의 시작 가능 여부를 조회한다. 가능하면 `처음 시작하기`,
기존 가계에 들어가려면 `배우자 연결하기`를 선택한다. 가계 생성은 표시 이름·비밀번호·비밀번호 확인,
배우자 연결은 여기에 숫자 8자리 연결 코드를 입력한다. 로그인 이름을 직접 만들거나 운영 CLI에서
코드를 발급받을 필요가 없다. 첫 시작의 허용 여부는 서버가 사설 연결 소유자와 기존 사용자/구성원
존재를 검사하여 결정한다. 네이티브의 `available` 응답은 안내용이며 서버 권한 검사를 대체하지 않는다.

가입 성공은 새 토큰으로 `/me`의 메타데이터와 예상 역할을 확인하고, refresh token을 기존 Keystore
보호 저장소에 기록한 뒤 앱 잠금을 해제한다. 별도 로그인 단계 없이 시작한다. 이미 로컬 세션이 있으면
가입으로 교체하지 않는다. 서버 응답 손실이나 로컬 저장 실패 때 서버 가입이 이미 끝났을 수 있으므로,
자동으로 가입을 재전송하지 않는다. 로그인 화면의 `처음 시작한 사람` / `연결한 배우자` 선택은 각각
서버의 고정 로그인 값을 채운다. 기존 사용자용 로그인 이름 직접 입력도 유지한다.

로그인한 첫 구성원은 `배우자 연결 코드` 네이티브 화면에서 코드를 만든다. 서버가 최근 인증을 요구하면
같은 네이티브 화면에서 현재 비밀번호를 다시 확인하고 코드 생성을 다시 요청한다. 서버 유효기간은
15분이며 화면 표시는 단조 시간 최대 30초다. 코드 보기 버튼을 눌러 배우자의 연결 화면에 직접 입력한다.
코드는 웹 상태·Activity 결과·로그·클립보드·영구 저장소로 보내지 않는다.

## 네이티브 경계

| 브리지 메서드 — 모두 인자 없음 | 반환되는 정보 |
|---|---|
| `getSetupStatus` | `{available: boolean}`만 |
| `createHousehold` | `status` 값 `authenticated` 또는 `cancelled`만 |
| `connectHousehold` | `status` 값 `authenticated` 또는 `cancelled`만 |
| `createConnectionCode` | `status` 값 `created` 또는 `cancelled`만 |

실제 반환은 기존 `NativeAuthResult` wrapper를 따른다. 이름·암호·확인 암호·연결 코드를 JS 인자로
받지 않는다. NativeOnboardingActivity는 `exported=false`, 정확한 내부 mode extra만 허용하고
외부 URI/clip/selector/action/category와 상태 복원을 거절한다. FLAG_SECURE, 저장 상태 제외,
자동완성/콘텐츠 수집 제외, 가려진 터치 차단을 적용한다.

HTTP는 네이티브가 정한 HTTPS origin의 다음 네 경로로 제한한다.

| 고정 요청 | 전송 경계 |
|---|---|
| `GET /api/v1/household/setup` | 본문·Bearer 없이 `{available}`만 투영 |
| `POST /api/v1/auth/native/setup` | 네이티브 이름·암호·고정 기기 이름, 새 토큰 응답은 네이티브 내부만 |
| `POST /api/v1/auth/native/connect` | 위 항목과 정확한 ASCII 숫자 8자리 코드 |
| `POST /api/v1/household/connection-code` | 현재 Bearer, payload 없음, 코드/만료 시각은 네이티브 표시 소유자만 |

일반 `request` 브리지는 이 경로들을 열지 않는다. 전용 내부 플래그와 메서드·정확한 필드·타입·헤더 제한을
함께 검사한다. POST는 one-shot 본문으로 자동 재전송하지 않으며 쿠키·리디렉션·HTTP 로그를 추가하지 않는다.
연결 코드 생성의 payload는 0 bytes이며 임의 JSON 필드를 보내지 않는다.

시작 가능 여부용 잠금 예외는 해당 GET만 허용하고 앱 잠금을 풀 수 없다. 가입용 예외는 setup/connect
POST와 새 access token의 `/me` 검증에만 사용한다. 자산·구성원 목록·refresh·코드 생성으로 확장되지 않는다.
입력 검사는 이름 최대 80, 암호 15~128 Unicode scalar를 사용하고 암호를 trim/정규화하지 않는다.
짝이 없는 UTF-16 surrogate와 비ASCII 연결 코드는 거절한다. 서버가 최종 검증 권한을 가진다.

요청 60초 제한은 직렬 실행 대기 시간도 포함한다. 화면 이탈·pause·기기 잠금·회전·취소는 진행 요청과
입력 버퍼/코드 표시를 폐기한다. 자격증명 설치의 마지막 단계에서도 요청 세대와 시한을 확인하고,
새 저장/잠금 해제 중 실패하면 새 로컬 자격증명을 정리한다. 이는 이미 서버에 완료된 가입을 취소했다는
뜻이 아니다. 기존 보관함을 가입 실패 처리로 삭제하지 않는다.

잠금 해제 이벤트는 Activity/브리지 완료 결과보다 먼저 올 수 있다. React는 이를 세션 조회 신호로만
사용하며 JS 이벤트로 네이티브를 해제하지 않는다. Android 가림 화면에서 직접 시작한 가입은
JS의 가입 호출 없이도 잠금 해제 이벤트 후 실제 `/me` 조회로 상태를 갱신한다.

## 자동 검사와 한계

순수 Kotlin 검사는 정확한 요청/응답 투영, Unicode 길이와 코드 형식, 허용 오류의 status 일치,
네이티브 코드 버퍼 폐기, 잠금 예외의 경로 제한을 검사한다. 주입한 단조 시계와 실제 설치 helper로
대기 시한, 이전 세대, 취소, 저장 중 시한 경계, 잠금 해제 실패와 정리 실패를 재현한다.
이 검사는 Android Keystore·Activity 입력·실제 서버 가입을 실행한 결과가 아니다.

가림 화면 통합 조사에서 합성 CVC 인수 화면의 debug 예외가 빠진 것을 함께 수정했다. debug에서만
정확한 두 검증 Activity를 허용하며 일반 CVC gate는 계속 닫혀 있다. 이를 확인하는 기기 계측 회귀를
추가하고 테스트 APK를 생성한다. release 전체 DEX에서 기존 검증 marker 9개가 없는지 다시 확인한다.
기기 계측 시험은 패키징과 실행을 구분한다.

2026-10-18, 분리 작업 트리에서 다음을 실행했다. 서버 계약은 `4e0f5c9`의 기존 토큰 응답과
새 setup/connect/connection-code 스키마에 대조했으며 API/생성 client/lockfile을 변경하지 않았다.

| 명령·검사 | 결과 |
|---|---|
| `pnpm install --frozen-lockfile`, `pnpm android:sync` | 성공. TypeScript 검사·기존 web bundle 생성·Capacitor sync 포함 |
| `./gradlew --no-daemon --max-workers=1 :app:assembleDebug :app:assembleDebugAndroidTest :app:assembleRelease :app:testDebugUnitTest` | 성공. JVM **356개**, 실패·오류·건너뜀 0. 신규 가입 정책/수명주기 회귀 23개 포함 |
| debug/release 병합 manifest | NativeOnboardingActivity `exported=false` 확인 |
| 실제 unsigned release APK 전체 DEX | 새 onboarding 클래스 존재, 합성 보안 검증 marker 9개 제외 |
| `pnpm test:docs`, `git diff --check` | 문서 검증·도구 테스트 **64개**·diff 검사 성공 |
| `connectedDebugAndroidTest` 및 실제 기기 가입 | **미실행**. 계측 APK의 CVC gate 8개·WebView 4개는 컴파일/패키징만 수행 |

첫 전체 실행은 355개 중 기존 `NativeDocumentHttpTest.serverRetryAfterZeroCannotTriggerASecondDownloadRequest`
한 건이 `expected 1, actual 0`으로 실패했다. 동시에 브라우저 검사가 진행 중이었고 이 테스트의 서버
수신 대기는 1.5초다. 브라우저가 종료된 뒤 단일 테스트를 `--max-workers=1`로 분리해 실행하여
1개 통과(1.689초)를 확인하고, 최신 소스의 전체 356개도 순차 검사로 통과했다. 환경 부하와 시간 제한의
영향 가능성은 있으나 원인으로 확정하지 않는다. 관련 transport 코드나 기존 테스트 판정은 바꾸지 않았다.

APK는 `apps/client/android/app/build/outputs/apk/`의 `debug/app-debug.apk`,
`androidTest/debug/app-debug-androidTest.apk`, `release/app-release-unsigned.apk`에 생성했다.
이 작업 트리의 API origin/RP/cert 값은 공란이다. 실제 서버 로그인·서명 배포를 검증한 APK가 아니며,
통합된 React 화면과 설정을 포함한 최종 검사는 별도 통합 작업에서 수행한다.

아직 실행하지 않은 두 Galaxy 인수 항목:

- 처음 시작 가능/불가 상태, 이름·암호 확인, 가입 후 바로 홈 진입, 연결 코드 발급·만료·잘못된 입력·연결 후 홈 진입.
- 재설치/응답 손실 후 계정 선택 로그인, 기존 자유 입력 로그인과 기존 초대 호환.
- 최근 인증 만료 후 네이티브 암호 재확인, 실패/취소, 앱 잠금과 늦은 응답의 경합.
- 입력/요청/코드 표시 중 Home·화면 잠금·회전·알림 초점 이탈, 30초 코드 가림, 백업/bridge/로그/캡처 무유출.
- 실제 서버의 두 계정 제한·사설 연결 제한·가입 동시성·rate limit은 별도 서버 검증 근거와 대조.

실제 개인 이름·암호·연결 코드를 Git/이슈/로그/스크린샷에 남기지 않는다. 실기기와 서명 배포를
실행하지 않은 자동 빌드는 운영 사용 인수 통과로 표시하지 않는다.
