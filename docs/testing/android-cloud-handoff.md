# SallimBook Android 클라우드 테스트 전달문

이 문서를 새 클라우드 코딩 세션에 전달한다. 목표는 실제 Android APK를 에뮬레이터에 설치하고,
기존 계측 시험과 새 사용 흐름 시험을 실행해 재현 가능한 결과와 수정 사항을 반환하는 것이다.
환경 확인에서 멈추지 말고 가능한 단계까지 진행하되, 실행 불가·skip을 통과로 바꾸지 않는다.
전체 일정과 현재 환경의 별도 작업은 [v1 잔여 계획](../v1-completion-plan.md)에 있다.

## 저장소와 시작 조건

- 저장소: `https://github.com/jihoon22-lee/SallimBook`.
- 시작 시 최신 `main`의 정확한 SHA와 clean/dirty 상태를 기록하고 `test/android-cloud-acceptance` 계열의
  별도 브랜치/작업 트리를 만든다. 계획 작성 기준은 `b3db1e5271e4747fb4996b51c14678bfe3bce9a4`다.
  실제 기준 SHA를 결과에 사용하며, 후속 main의 제품 수정이 들어오면 영향 있는 시험을 다시 실행한다.
- `AGENTS.md`, `README.md`, [보안 정책](../security-authentication.md), [계산 fixture](../testing-and-acceptance.md),
  [네이티브 경계](../native-bridge-contract.md), [첫 시작 설계](../adr/mobile-first-start.md)를 읽는다.
- 사용자 대신 실제 계정에 로그인하지 않는다. 운영 APK의 서버 주소·Tailscale 설정·운영 키·운영 DB·
  복구코드·실제 사용자 데이터를 이 세션으로 가져오지 않는다. 운영 서버에서 합성 시험도 수행하지 않는다.
- 일반 CVC gate는 false로 유지한다. `debugproof`의 합성 CVC 예외만 문서의 정확한 범위에서 사용한다.

## 1. 환경 실행 가능성 확인

다음 값을 확인해서 비밀 없는 환경 보고서를 만든다.

- OS/아키텍처, CPU·메모리·남은 디스크, 가상화 장치 존재와 접근 가능 여부.
- JDK 21, Node 24.18.0, pnpm 9.15.9, 저장소의 고정 Python/uv 환경.
- Android compile/target API 36, min API 30, build-tools 36.0.0, SDK/에뮬레이터/AVD 이미지의 정확한 버전.
- 공식 다운로드·의존성 저장소 접근, 실제 PostgreSQL을 격리 실행할 방법, 브라우저 시험 실행 가능 여부.

Codex 클라우드의 [공식 환경 문서](https://learn.chatgpt.com/docs/environments/cloud-environments)는
도구 설치와 VM 환경을 설명하지만 Android 가상화 가속을 보장하지 않는다. 해당 세션에서 직접 확인한다.
Android의 [가속 검사](https://developer.android.com/studio/run/emulator-acceleration)에 따라
설치한 `emulator -accel-check` 결과를 기록한다. `/dev/kvm` 파일 존재만으로 가속 성공이라고 하지 않는다.

SDK 빌드 도구는 기존 `scripts/setup_android_sdk.py`를 우선 사용한다. 이 스크립트는 emulator·
system image·platform-tools를 설치하지 않으므로 필요한 항목은 공식 Google 배포에서 별도로 준비한다.
선택한 emulator/image revision과 다운로드 checksum 또는 공식 패키지 메타데이터를 기록·고정한다.
기존 설치나 잠금 파일을 근거 없이 업데이트하지 않는다.

API 36 AVD 하나를 먼저 headless로 부팅해 실제 `sys.boot_completed=1`, ADB 연결, WebView provider를
확인한다. 이어 API 30의 최소 지원 동작을 순차 검사한다. 더 큰 동시 AVD 수보다 안정적인 한 대를 우선한다.
가속이 없으면 호환 이미지의 소프트웨어 실행을 제한된 시간 안에서 한 번 확인할 수 있다. 부팅당 상한을 정해
기록하고 무한 재시도하지 않는다. 실행 불가면 `BLOCKED_ENV`와 구체적인 자원/권한/다운로드 실패를 반환한다.
유료 VM/기기 서비스를 새로 만들거나 결제·조직 정책·호스트 보안을 임의 변경하지 않는다.

설치 없이 앱 빌드만 성공한 결과, JVM 성공, Playwright의 Android 크기 화면은 AVD 실행 성공과 구분한다.

## 2. 기존 계측 시험부터 실행

현재 소스에는 다음 12개가 있다. 실행 시 실제 파일과 discovery 결과를 다시 대조한다.

| 클래스 | 준비된 수 | 검증 내용 |
|---|---:|---|
| `SecureBridgeWebViewTest` | 4 | 실제 WebView의 초기 navigation, 레거시 bridge fallback 차단, 번들 origin 경계 |
| `NativeVaultCvcAcceptanceTest` | 8 | 일반 CVC gate 닫힘, 합성 namespace/Activity 소유권, 종료/잠금, 인증 없는 실제 Cipher 거부, no-backup 경로 |

저장소 루트의 기본 빌드 순서:

```bash
pnpm install --frozen-lockfile
uv sync --project services/api --frozen
pnpm android:sync
cd apps/client/android
./gradlew --no-daemon --max-workers=1 :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest :app:assembleRelease
./gradlew --no-daemon --max-workers=1 :app:connectedDebugAndroidTest
```

위 명령 전 JDK 21과 이 세션 전용 SDK의 `JAVA_HOME`/`ANDROID_HOME`을 올바르게 지정한다.
자신이 만든 AVD만 연결됐는지 확인하고 여러 기기가 있으면 명시적인 대상 serial을 사용한다.
다른 기기·다른 ADB 서버를 종료하거나 초기화하지 않는다.

중요한 선행 조건:

- 합성 Activity 소유권 시험은 잠금이 해제된 foreground AVD가 필요하다.
- `ownerFlagCannotUseKeystoreCipherWithoutActualBiometricAuthorization`은 API 33+,
  강한 생체인증 등록, 기존 합성 CVC/키가 없는 환경을 요구한다. API 30 등에서의 `Assume` skip은 통과가 아니다.
- 지원되는 AVD에서 시스템 생체 등록과 emulator의 인증 입력을 사용한다. JS 성공 플래그·mock Cipher·
  무인증 키로 실제 암호 연산 검사를 대신하지 않는다. 이 결과도 Galaxy의 하드웨어 보안 증거로 쓰지 않는다.
- 테스트 이름별 PASS/FAIL/SKIPPED와 이유를 XML에서 수집한다. 조건 미충족을 숨기려고 assertion을 지우지 않는다.

## 3. 실제 API와 연결할 시험 환경 구현

아래는 **추가로 구현할 항목**이다. 현재 `scripts/test_web_auth.py`는 브라우저용이며 Android E2E runner가 아니다.

1. 일회용 PostgreSQL DB/schema, 합성 가계 H1/H2, 실제 Alembic과 FastAPI를 준비한다.
   기존 `scripts/test_database.py`의 격리 원칙과 `scripts/test_web_auth.py`의 TLS/fixture 생성을 재사용한다.
   Docker를 못 쓰면 같은 PostgreSQL 버전의 별도 로컬 인스턴스 가능성을 확인한다. SQLite로 대체해 DB 검증을 주장하지 않는다.
2. AVD에서 접근할 수 있는 시험 전용 HTTPS origin과 임시 인증서를 만든다. 필요한 경우 ADB reverse 등
   [공식 에뮬레이터 연결 방식](https://developer.android.com/studio/run/emulator-commandline)을 사용한다.
   인증서 hostname 검사를 유지하며 연결 경로를 실제로 확인한다.
3. 테스트 CA가 필요하면 새 debug 전용 manifest/resource와
   [Android debug trust 설정](https://developer.android.com/privacy-and-security/security-config#debug-overrides)을 사용한다.
   production TLS 검증·인증·고정 origin·cleartext 차단·bundled WebView 경계는 바꾸지 않는다.
   일반 배포 release의 manifest/resources/전체 DEX에 debug 시험 CA·주소·예외·검증 Activity가
   자동 유입되지 않았는지 검사한다. 명시적으로 시험 origin을 선택한 합성 release는 별도 표시하고 배포하지 않는다.
4. 첫 시작 시험은 외부에 노출하지 않은 시험 프록시가 합성 신원 헤더를 주입하도록 구성한다.
   실제 peer 검사와 서버 권한 코드는 유지하고, 이 fixture를 실제 Tailscale 신원 검증으로 표시하지 않는다.
   각 첫 시작 시나리오는 새로운 빈 DB/schema에서 시작한다.
5. debug APK의 `sallimbookApiOrigin`을 시험 origin으로 고정한다. origin 공란 빌드는 네트워크 인증을
   비활성화하므로 가입/로그인 통과로 사용할 수 없다. 인증서 신뢰 실패를 HTTP 또는 trust-all로 우회하지 않는다.
6. APK UI를 Espresso/UI Automator 등으로 조작한다. 비밀번호·코드는 네이티브 입력 화면에서 입력하고
   요청은 실제 native HTTP/bridge를 통과해야 한다. API만 직접 호출하거나 Playwright로 바꾼 결과를 Android E2E로 쓰지 않는다.

시험 네트워크에는 운영 서비스 접근이 필요 없다. H1/H2는 공통 합성 fixture이며 제품을 다가계 SaaS로 바꾸는 뜻이 아니다.
DB/HTTPS 준비에 막혀도 네트워크가 필요 없는 기존 계측과 네이티브 수명주기 시험은 계속한다.

## 4. 실행할 시나리오

| ID | 시나리오와 기대 결과 | 요구사항 |
|---|---|---|
| A01 | 빈 가계에서 네이티브 이름/암호 등록 → 실제 세션 → 홈. 중복 시작 거절, 취소·응답 손실·잘못된 입력에서 거짓 성공 없음 | R-01/R-02 |
| A02 | 설정에서 코드 생성, 다른 사용자 연결, 두 구성원 확인. 만료/재발급/재사용/오입력 제한, owner/partner 로그인 선택, 기존 초대 호환 | R-01/R-19 |
| A03 | 앱 재시작·프로세스 종료·화면 잠금·수동 잠금·외부 1분 전후·회전. 잠긴 동안 요청과 이전 세대 응답 차단, 취소 후 재시도 | R-10/R-11/R-19 |
| A04 | 계좌·연금/IRP·부채·자산, 두 달 입력/확정/정정/비교. null/0/미확인 구분, 중복 합산 없음. 공통 T-01~T-07 | R-03~R-06/R-22 |
| A05 | 수입, 고정비 예정/실제/분할, 원금·연금과 소비 구분, 카드/계좌 종료 영향. snapshot 자동 변경 없음. T-08~T-11 | R-07~R-09/R-18/R-22 |
| A06 | 보험계약·사건→진료/약국 트리·비용/환불·복수 청구·실제 지급/반환·사건 배분. T-12~T-19의 합계 일치 | R-13~R-15/R-18/R-22 |
| A07 | 가전·소모품 등록, 입고·교체·재고 조정, 재전송/동시 소모. 과거 자산월에서도 오늘 소모품. T-20~T-24 | R-03/R-16~R-19/R-22 |
| A08 | 합성 파일 첨부·검사/실패·보호된 보기·연결 이력·권한 거절, JSON/CSV/문서 export와 취소/만료. PAN/CVC/토큰 내보내기 없음 | R-20 |
| A09 | 웹/native 간 합성 카드 암호화/복호화, 재인증·30초·이탈 가림, 새 기기/복구/키 회전 및 중단. 일반 CVC는 계속 거절 | R-09~R-12/R-20 |
| A10 | 합성 두 사용자의 재조회 반영·같은 버전 편집409·금전/재고 멱등성, H2 ID/첨부 접근 거절. 실제 사용한 클라이언트 조합 기록 | R-01/R-02/R-18/R-19/R-22 |
| A11 | 시험용 동일 서명키의 이전/새 versionCode APK 업데이트 후 데이터 보존·잠금. 재설치는 로컬 토큰/키가 이전되지 않음 | R-02/R-20/R-21 |
| A12 | 좁은 화면·큰 글꼴·키보드·접근성 label/focus·오류/빈 화면/네트워크 끊김. 실패한 저장을 성공으로 표시하지 않음 | R-02/R-19 |
| A13 | 지원 이미지·인증 제공자·시험 RP/DAL이 준비되면 실제 native 패스키 등록/로그인/재인증/취소. 조건 없으면 BLOCKED_ENV | R-01/R-11/R-21 |

최소 API 30과 주 시험 API 36을 구분한다. 같은 가계 두 사용자 시험은 여유가 있으면 AVD 2대,
그렇지 않으면 AVD+PC 웹 또는 별도 세션으로 진행하고, 두 실제 휴대전화 시험으로 표시하지 않는다.
회전·타이머·오프라인·충돌에 대한 명시적 assertion을 둔다. 화면이 열렸다는 결과만으로 금액/권한/암호화 성공을 판단하지 않는다.

A11의 시험 키는 세션 안에서 새로 만들고 private 위치에만 둔다. 운영 서명키를 요구하지 않는다.
시험 인증서를 신뢰하는 debug 업데이트 결과와 실제 정식 APK 업데이트 인수는 별도다. release APK는
추가 신뢰 예외 없이 검증 가능한 시험 HTTPS를 준비했을 때 네트워크 시험하고, 그렇지 않으면 구조/서명 검사를 구분해 보고한다.
A13은 이미 통과한 Chromium 가상 WebAuthn으로 대체하지 않는다. 외부 검증 가능한 RP/DAL 준비가 필요하면
그 선행 조건을 보고하고 나머지 시험을 계속한다.

## 5. 수정 범위와 반환물

클라우드 담당은 Android 계측, 새 시험 runner/fixture, debug 전용 시험 설정, 결과 문서다.
테스트가 실제 앱 결함을 발견하면 원인·회귀를 먼저 제시하고 필요한 최소 제품 수정을 별도 commit으로 만든다.
API 계약·마이그레이션·공통 잠금 파일 변경은 현재 작업 환경 담당과 조율한다. Android 시험 의존성은
정확한 버전·공식 근거·잠금 파일을 같은 변경에서 갱신한다. 운영/배포/스케줄 설정은 현재 환경 담당이 소유한다.

다음 산출물을 반환한다.

1. 실행 가능한 시험 명령/runner와 필요한 코드 변경. 기준 SHA·변경 SHA·브랜치 또는 PR 링크.
2. `docs/testing/android-cloud-results.md`에 환경·명령·A01~A13 상태·실패 원인·남은 항목을 기록한다.
   이 파일은 **실행 후 새로 작성할 결과물**이며 현재 존재하는 성공 증거가 아니다.
3. JUnit XML과 테스트별 개수, APK hash/applicationId/version/서명 공개 fingerprint,
   emulator/image/API/ABI/WebView 버전·가속 결과, 실행·종료 확인.
4. 실패 재현 절차와 최소 회귀, 시도한 수정 및 재실행 결과. 수정 후 전체 수를 재실행하지 않았다면 범위를 명시한다.
5. 실제 Galaxy에 남길 검사만 추린 짧은 목록. 소프트웨어·에뮬레이터 Keystore를 하드웨어 보안 증거로 쓰지 않는다.

결과 상태는 `PASS / FAIL / SKIPPED / BLOCKED_ENV / NOT_RUN` 중 하나를 사용한다.
컴파일 성공·테스트 APK 생성·0 tests·조건부 skip을 PASS로 합산하지 않는다.
비밀 입력/표시 화면의 screenshot/video/trace, 원문 logcat/bugreport, 토큰·복구코드·키·비밀번호를
Git/이슈/AI 응답/공유 artifact에 넣지 않는다. 원문 대신 안전한 assertion 결과와 필요한 비민감 오류만 남긴다.

본인이 만든 AVD·시험 서버·DB/schema·임시 키/인증서만 정리한다. 실패 환경을 남겨야 하면 소유 범위와
다음 명령을 기록하고 운영 환경에는 손대지 않는다. 결과 제출은 제품 전체 v1 출시 승인과 구분한다.
