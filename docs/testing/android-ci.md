# Android 계측 CI

연결: #17, #43, #48, #87 및 PR #91 · R-01, R-02, R-10, R-11, R-12, R-19, R-20, R-21.
기존 실행/실기기 한계는 [Android cloud 결과](android-cloud-results.md)를 함께 확인한다.

[Android instrumentation workflow](../../.github/workflows/android-instrumentation.yml)는
`ubuntu-24.04` x64 GitHub 호스팅 VM 한 대에서 API 36 AVD를 만들고 기존 네이티브 12개와 실제
HTTPS 온보딩 1개를 실행한다. 기존 `.github/workflows/ci.yml`의 JVM/컴파일 job과는 별도다.

## 실행 조건과 자원

- `main` 대상 일반 PR에서 클라이언트·API·Android 시험 도구·관련 의존성·이 workflow가 바뀌면 실행한다.
  Draft PR은 자동 실행하지 않는다. 문서만 바뀐 경우도 이 job을 실행하지 않는다.
- `workflow_dispatch`로 명시적 재실행이 가능하다. GitHub 수동 실행은 workflow가 기본 브랜치에
  존재해야 한다. 임의 명령이나 고객 계정을 입력하는 dispatch 인자는 없다.
- 고정 concurrency group으로 이 workflow의 AVD job은 저장소 전체에서 하나만 실행한다.
  새 요청은 이전 실행을 취소한다. API/ABI matrix, 다른 기기 fallback, 소프트웨어 CPU 에뮬레이션은 없다.
- 전체 job은 135분으로 제한한다. 모든 step에도 명시적 제한을 두며 합계는 121분이다.
  checkout/도구 설정 25분 + 경로 설정 1분 + KVM/SDK/의존성 준비 31분 + AVD 45분 + release 검사
  10분 + 정리 2분 + 정제 증거 생성 2분 + artifact 업로드 5분을 합산했다. 나머지 14분은 action의
  post 단계와 runner 전환 여유다. 준비가 길어져도 job의 60분 제한이 시험·정리·업로드를 먼저
  중단할 수 있던 문제를 수정한 것이며, 각 시험 자체의 제한을 늘리지는 않았다.
- AVD 단계 안의 부팅은 600초, 시험 명령은 1800초이며 fixture/자식 정리와 AVD/ADB 종료를 포함한
  실행기 제한을 45분 안에 둔다. 취소/호스팅 강제 종료로 정리 증거가 없으면 완료로 표시하지 않는다.

GitHub는 Linux 호스팅 실행기의 Android 하드웨어 가속을 지원한다고 명시한다. 공개 저장소의 표준
`ubuntu-24.04`는 x64 4 CPU/16GB VM이며 소형 컨테이너 실행기와 구분된다.
[GitHub 실행기 공식 문서](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

Android의 x86_64 VM 가속은 호스트 CPU와 맞는 시스템 이미지 및 Linux KVM을 요구한다.
워크플로는 `/dev/kvm`에 **해당 일회용 실행 사용자만** ACL을 부여하고 KVM API 12 ioctl과 실제
`emulator -accel-check`를 모두 확인한다. 가속이 없으면 설치/실행을 중단한다. GPU는 headless 소프트웨어
렌더러를 사용하지만 CPU의 `--software` fallback을 허용하지 않는다.
[Android 하드웨어 가속 문서](https://developer.android.com/studio/run/emulator-acceleration).

이 ACL 조작은 GitHub 호스팅 VM에만 적용한다. 현재 PC의 `/dev/kvm` 권한, WSL·Docker·Tailscale·사용자
그룹을 변경하는 로컬 설치 지침이 아니다. 실행 전과 정리 전 `RUNNER_ENVIRONMENT=github-hosted`를 확인한다.

## 고정 도구와 SDK

모든 action은 전체 commit SHA로 고정한다. checkout은 `persist-credentials: false`이고 workflow 권한은
`contents: read`뿐이다. 저장소 secret·운영 인증서·서명키·사용자 계정을 요청하지 않는다.

| 구성요소 | 검토한 버전 |
| --- | --- |
| Node / pnpm | 24.18.0 / 9.15.9 |
| uv / Python | 0.12.5 / 3.14.7 |
| Temurin JDK | 21.0.12.1+1, setup-java의 SemVer 표현 `21.0.12+1.1` |
| Gradle | 저장소 wrapper 8.14.3 및 `distributionSha256Sum` |
| Android command-line tools | build 15859902 및 기존 설치기의 SHA-256 |
| Android platform / build-tools | API 36 revision 2 / 36.0.0 |
| platform-tools / emulator | 37.0.1 / 37.2.12, build 16428233 |
| AVD system image | `system-images;android-36;google_apis;x86_64`, revision 7 |
| PostgreSQL | 기존 합성 Compose의 18.6-bookworm 및 이미지 digest |
| artifact action | upload-artifact 7.0.2, `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |

Temurin의 정확한 패치 릴리스는 [공식 릴리스](https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.12.1%2B1)를
기준으로 정했다. setup-java의 고정 버전이 OpenJDK 패치/빌드 표기를 정규화하는
[공식 구현](https://github.com/actions/setup-java/blob/b843ebf9b913146b38da2eaa7aeddf76074ae1ad/src/distributions/temurin/installer.ts)을
확인했다. artifact action도 [공식 7.0.2 릴리스](https://github.com/actions/upload-artifact/releases/tag/v7.0.2)에 연결한다.

SDK는 runner의 기존 SDK를 재사용하지 않고 `RUNNER_TEMP` 안에 새로 설치한다. 설치 전에 Google 공식
[SDK metadata](https://dl.google.com/android/repository/repository2-3.xml)와
[Google APIs image metadata](https://dl.google.com/android/repository/sys-img/google_apis/sys-img2-3.xml)의
stable revision·archive 파일명·바이트 수·공개 SHA-1을 workflow의 검토 값과 비교한다. SDK manager가
archive checksum을 검사한 뒤 설치된 `package.xml`의 revision도 다시 검사한다. metadata 또는 실제
설치 버전이 달라지면 새 버전을 조용히 수용하지 않고 실패한다. Google이 제공하는 archive SHA-1과
command-line tools의 SHA-256을 같은 알고리즘으로 표현하지 않는다. 실제 emulator/ADB 파일의 SHA-256도
증거에 기록한다. 의존성은 frozen pnpm/uv lock과 기존 Gradle 검증 설정을 사용한다.

## 합성 데이터와 정리

새 checkout에서 `.env`가 없는지 확인하고 `setup_dev.py`로 합성 자격만 만든다. 전용 AVD 디렉터리와
ADB 포트 5049, emulator 포트 5580/5581을 사용한다. 실행기는 자신이 만든 `sallimbook-probe` AVD만
선택한다. 시험 서비스는 전용 `sallimbook-dev`의 tmpfs `db-test`이고 운영 Compose를 사용하지 않는다.

실제 온보딩은 새 PostgreSQL schema에 실제 migration을 적용하고, 임시 CA/키로 loopback HTTPS를
시작한다. hostname 검증과 native-to-host ADB reverse를 사용한다. 시험 CA와 origin은 명시적 debug
fixture에만 적용한다. 정상 unsigned release를 별도로 만들고 모든 APK entry/DEX의 시험 marker 격리를
검사한다. APK·정식 서명키는 게시하지 않는다.

시험 실행기는 자신이 만든 schema·TLS 서버·임시 CA/키·ADB reverse·AVD·전용 ADB를 정리한다.
workflow의 `always()` 정리는 이 일회용 VM의 `db-test` 컨테이너와 새 합성 `.env`를 제거하고 네 개
전용 포트에 listener가 남지 않았는지 확인한다. 나머지 일회용 SDK/빌드 디스크는 호스팅 VM 폐기 시
제거된다. 다른 프로젝트나 로컬 사용자의 프로세스를 종료하는 절차가 아니다.

## 결과의 의미와 공개 artifact

실행기는 이번 실행의 XML만 수집한다. workflow는 다음 조건을 함께 검사한다.

- 부팅 완료, 실제 API 36/x86_64, KVM 가속, 시험 명령 성공.
- AVD/ADB 종료와 추가 정리 step 성공, unsigned release의 시험 marker 격리 검사 성공.
- `existing.xml` 12건과 `onboarding.xml` 1건, 중복 testcase 없음, failure/error 없음.
- 생체 인증 미등록 AVD에서 `ownerFlagCannotUseKeystoreCipherWithoutActualBiometricAuthorization`
  한 건의 skip만 별도로 허용한다. 다른 skip, 온보딩 skip, 누락된 XML/시험은 실패다.

13건 모두 통과하면 `PASS`, 알려진 생체 한계가 있으면 `PARTIAL_DEVICE`이며 예를 들어
`tests=13, passed=12, skipped=1`로 표시한다. 이를 13개 통과나 실제 생체 인증 인수 완료로 바꾸지 않는다.
시험 실패는 timeout 증가나 skip 추가로 숨기지 않는다. 하드웨어 Keystore·생체 등록/무효화·화면 보안·
두 Galaxy 기기·정식 업데이트 인수는 별도로 남는다.

7일 보관 artifact에는 새 정제 디렉터리의 정확한 5개 경로만 허용한다.

| 파일 | 보관 내용 |
| --- | --- |
| `summary.json` | 실제 소스/실행 ID, 검증 boolean, suite별 실제 pass/fail/skip 수 |
| `sdk.json` | 검토한 공개 SDK metadata, 설치 revision, emulator/ADB 파일 hash |
| `apks.json` | APK hash·앱 식별·버전·공개 debug 서명 fingerprint·release 격리 결과 |
| `existing.xml`, `onboarding.xml` | 공개 testcase 이름/class와 상태; 실패 원문은 고정 문구로 대체 |

원본 result/webview dump, emulator/Gradle/device 로그, 스크린샷, UI hierarchy, APK, `.env`, AVD 디스크,
CA/키, 비밀번호·세션 body는 업로드하지 않는다. `always()`로 실패 증거도 만들지만 실패한 실행의 결과를
성공으로 처리하지 않는다. raw Gradle과 emulator 진단은 일회용 VM의 private 임시 파일에만 둔다.

작성 단계에서 actionlint 1.7.12, inline Python 6개 블록 문법, 실제 Google metadata의 SDK 5개 pin 대조가
통과했다. 합성 evidence gate의 정상·허용 skip·예외 skip·중복·누락·API 불일치·실패 원문 제거 7개 경우도
각각 기대한 성공/실패와 redaction을 확인했다. 원격 KVM/계측 결과는
실제 실행 후 run URL·정확한 source SHA·boot 시간·suite별 수·정리 결과로 기록한다. workflow 파일이 존재하거나
이전 JVM 컴파일이 통과했다는 사실만으로 Android 계측 성공을 주장하지 않는다.

시간 예산 후속 검증에서는 모든 16개 step의 명시적 제한 합계 121분과 job 제한 135분의 관계를
검사하고, actionlint 및 Android 결과 정제 회귀 시험을 다시 실행했다. 이 변경은 이미 진행 중인
원격 실행의 제한을 바꾸지 않으며, 새 workflow로 시작한 실행부터 적용된다.
