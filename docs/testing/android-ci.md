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
- 전체 job은 150분으로 제한한다. 모든 step에도 명시적 제한을 두며 합계는 136분이다.
  checkout/도구 설정 25분 + 경로 설정 1분 + KVM/SDK/의존성 준비 31분 + AVD 60분 + release 검사
  10분 + 정리 2분 + 정제 증거 생성 2분 + artifact 업로드 5분을 합산했다. 나머지 14분은 action의
  post 단계와 runner 전환 여유다. 아래 실행기의 전체 시간 예산을 포함한다.
- AVD 단계 안의 부팅은 600초, 시험 명령은 1800초이며 fixture/자식 정리와 AVD/ADB 종료를 포함한
  실행기 제한을 60분 안에 둔다. 취소/호스팅 강제 종료로 정리 증거가 없으면 완료로 표시하지 않는다.

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

시간 예산 회귀 시험은 모든 16개 step의 명시적 제한 합계 136분과 job 제한 150분의 관계를 검사한다.
기존 원격 실행의 제한은 바뀌지 않으며 새 workflow로 시작한 실행부터 적용된다.

## AVD 단계의 전체 시간 예산

[probe 실행기](../../scripts/probe_android_avd.py)의 `run()` 기본 제한은 30초이며, timeout 뒤에도
[프로세스 정리 helper](../../scripts/android_cloud_process.py)의 `stop_group()`이 실행된다.
기본 정리는 SIGINT 10초 + SIGTERM 5초 + SIGKILL 5초이고 0.05초 polling의 마지막 sleep까지
올림해 호출당 21초를 예산에 넣는다. 시험 자식의 `grace=120`은 같은 방식으로 131초다.

| 구간 | 코드에 대응하는 보수적 상한 | 초 |
| --- | --- | --- |
| AVD 준비 | accel-check 30 + version 30 + avdmanager 60 + ADB start 30 + 각 호출의 정리 4 × 21 | 234 |
| 부팅 | 600초 deadline + 마지막 getprop 5 + 해당 호출 정리 21 + poll sleep 2 | 628 |
| 상태 조회 | API/ABI/WebView 3 × (run 30 + 정리 21) | 153 |
| 시험 명령 | `child.wait(timeout=1800)` | 1800 |
| 최종 정리 | 시험 자식 131 + emulator 21 + ADB kill 15 + kill 명령 timeout 뒤 정리 21 | 188 |
| 합계 | 모든 bounded 호출의 합 | **3003** |

준비나 상태 호출이 실패하면 뒤의 시험을 생략하지만, 예산은 각 호출의 timeout 정리 비용까지 모두
더해 보수적으로 계산한다. 부팅 loop는 deadline 직전에 시작한 마지막 ADB 호출의 제한·정리·sleep만큼
넘길 수 있다. 최종 ADB kill도 timeout이면 자체 프로세스 그룹 정리가 추가되므로 이를 빼지 않는다.

AVD step의 3600초에서 위 합계를 빼면 597초가 남는다. 이는 uv/프로세스 시작, 임시 AVD 파일 생성·삭제,
결과 파일 기록과 runner의 실행 지연에 둔 여유다. 파일 I/O 자체를 별도 hard deadline으로 제한했다는
뜻은 아니다. 실제 boot 600초와 시험 명령 1800초 제한은 그대로이며, 시험 실패를 성공/skip으로 바꾸지 않는다.

[시간 예산 회귀 시험](../../tests/test_android_workflow_deadline.py)은 실행기 AST의 모든 `run()` 호출,
기본/명시적 timeout, 상태 조회 개수, boot polling, 자식 정리 grace를 대조한다. 실제 `stop_group()`은
가상 시계로 끝까지 실행해 polling 초과분을 포함한다. AVD step이 계산 상한에 최소 5분 여유를 더한 값보다
짧거나, 전체 job에 모든 step과 14분 여유가 들어가지 않으면 실패한다. 기존 45분 AVD 제한, 여유 없는
job 제한, timeout 없는 setup step도 거절하는 회귀를 포함한다.

```sh
python -m unittest tests.test_android_workflow_deadline tests.test_android_avd_probe tests.test_android_cloud_support -v
actionlint .github/workflows/android-instrumentation.yml
```

이 검증은 SDK·Docker·실제 Android 기기를 실행하지 않는 시간 예산/프로세스/정제 결과 시험이다.
실제 원격 계측의 성공 여부는 별도 실행 증거로 판단한다.

## 실제 KVM 실행 기록 — 2026-10-18

| 실행 | 실제 checkout SHA | 기존 네이티브 | 신규 가입 | 결과 |
| --- | --- | --- | --- | --- |
| [39095425156](https://github.com/jihoon22-lee/SallimBook/actions/runs/39095425156) | `91e8b286b39c49d8fcb65cc2762cec86c68cdcf1` | 11 PASS / 1 SKIPPED | 1 FAIL, 정제 증거로 세부 단계 확인 불가 | FAIL |
| [39096333533](https://github.com/jihoon22-lee/SallimBook/actions/runs/39096333533) | `a7b56fb89154c120d13f670f33a750a3ec411351` | 11 PASS / 1 SKIPPED | 1 FAIL, `CANCEL_FORM` | FAIL |
| [39096963060](https://github.com/jihoon22-lee/SallimBook/actions/runs/39096963060) | `d4ed676d63829500013b3d80a0047ff9b3a4198f` | 11 PASS / 1 SKIPPED | 1 FAIL, `CANCEL_SCROLL` | FAIL |
| [39097997409](https://github.com/jihoon22-lee/SallimBook/actions/runs/39097997409) | `5f555bd067f96f2205d801eaff348a155fafadf8` | 11 PASS / 1 SKIPPED | 1 FAIL, `SESSION_AND_MAIN` / `ASSERTION` | FAIL |
| [39099073948](https://github.com/jihoon22-lee/SallimBook/actions/runs/39099073948) | `95aa9c7dd3c771aa36dbbe9bd726d74a7fb37357` | 11 PASS / 1 SKIPPED | 1 FAIL, `SESSION_CREATED` / `INPUT_INVALID` | FAIL |

두 checkout SHA는 GitHub가 만든 PR merge ref이며 각각 PR head `3ca1bd3`, `39adb28`에 해당한다.
두 실행 모두 KVM 가속, API 36/x86_64 부팅, AVD/ADB 종료와 합성 DB·포트 정리를 확인했다.
등록된 생체 인증이 없는 AVD의 `ownerFlagCannotUseKeystoreCipherWithoutActualBiometricAuthorization`
한 건이 실제 skip됐다. 전체 13건의 수치는 매 실행 11 PASS / 1 FAIL / 1 SKIPPED이며 합산하지 않는다.

가입 실패로 후속 정상 release 격리 단계는 실행되지 않았다. 따라서 해당 실행의
`release_isolation_verified=false`와 APK metadata 부재를 별도로 유지한다. 최초 실행에서 제거된
실패 단계는 후속 실행의 `CANCEL_FORM`으로 소급해 단정하지 않는다. 후속 진단은 고정 allowlist
단계명만 보존하며 Espresso 오류 원문·입력값·UI tree를 공개하지 않는다.

정제 artifact 4개씩을 보존했다: 첫 실행의 [요약](evidence/android-kvm-20261018/run-39095425156/summary.json),
[SDK](evidence/android-kvm-20261018/run-39095425156/sdk.json),
[기존 시험 XML](evidence/android-kvm-20261018/run-39095425156/existing.xml),
[가입 XML](evidence/android-kvm-20261018/run-39095425156/onboarding.xml);
진단 실행의 [요약](evidence/android-kvm-20261018/run-39096333533/summary.json),
[SDK](evidence/android-kvm-20261018/run-39096333533/sdk.json),
[기존 시험 XML](evidence/android-kvm-20261018/run-39096333533/existing.xml),
[가입 XML](evidence/android-kvm-20261018/run-39096333533/onboarding.xml).

이 결과로 기존 클라우드 환경의 `BLOCKED_ENV` 이력은 지우지 않는다. 실행 환경이 바뀌어 실제
계측이 가능해졌다는 후속 증거이며, 가입 실패 수정 및 A01~A13 나머지 사용자 흐름은 별도 작업이다.

`763bd0b`에서는 가입 Activity의 resumed/focus와 버튼 준비를 기다린 다음 해당 Activity의 decor와
실제 View로 클릭 대상을 한정했다. 취소 후 main 복귀와 새 setup 조회도 기다린다. 취소·스크롤·클릭·
복귀를 서로 다른 고정 단계로 기록해 실패 위치를 구분한다. 별도로 초기 전제를 네이티브 잠금 커튼·
빈 세션·bridge 준비로 교정했고, 마지막 실제 등록 세션과 API 응답 홈 판정은 유지했다.
제품의 잠금/세션 로직은 변경하지 않았다. Kotlin 계측 컴파일, 정제 도구 12건, 실제 React 브라우저
홈 판정 10건이 통과했다. 수정 후 원격 계측 성공은 별도 실행 결과로 확인해야 한다.

세 번째 실행은 PR head `fb16191`에 해당하며 실제 Activity 준비와 닫기 버튼 조회를 통과하고
Espresso `ScrollToAction`에서 실패했다. KVM·부팅·정리는 통과했고, release 검사는 앞선 실패로
실행되지 않았다. [요약](evidence/android-kvm-20261018/run-39096963060/summary.json),
[SDK](evidence/android-kvm-20261018/run-39096963060/sdk.json),
[기존 XML](evidence/android-kvm-20261018/run-39096963060/existing.xml),
[가입 XML](evidence/android-kvm-20261018/run-39096963060/onboarding.xml)을 보존했다.
이 증거만으로 constraint/root/표시 면적 중 어느 조건이 원인인지 단정하지 않는다.

후속 `b865709`의 시험 helper는 IME를 닫고 해당 Activity·root·ScrollView 제약을 확인한다.
버튼이나 입력 칸이 이미 90% 이상 보이면 동작하고, 아니면 실제 `swipeUp`/`swipeDown`을 최대 6회
수행한 뒤 같은 90% 기준을 요구한다. 리스너 직접 호출이나 표시 기준 하향, 실패 무시는 없다.
닫기·입력·제출에 같은 경로를 적용한다. 실패 시 고정 stage 27개, reason 13개와 전/후 상태 4비트만
보존한다. 비트는 owner focus/해당 root에 부착/scroll 제약/90% 표시 순서이고, 미측정은 `----`다.
예외 원문·스택·UI tree·입력값은 읽어 진단에 넣지 않는다. 결과 도구와 workflow는 동일 helper로
재검증하며 허용 형식 밖의 값은 버린다. 정제/실행기 22건, Kotlin 계측 컴파일, typecheck/build/sync,
Ruff/actionlint가 통과했다. 실제 swipe와 가입 성공은 다음 원격 실행으로 확인한다.

네 번째 실행(PR head `7be7dde`)에서는 실제 swipe를 포함한 취소·복귀, 빈 입력 거절, 필드 입력과
유효 제출 클릭을 지나 최종 세션/잠금/화면 복귀 결합 대기가 30초에 만료됐다. `pre/post=----`는
그 단계에서 표시 상태를 측정하지 않았다는 뜻이다. 등록 성공이나 특정 제품 결함으로 단정하지 않는다.
[요약](evidence/android-kvm-20261018/run-39097997409/summary.json),
[SDK](evidence/android-kvm-20261018/run-39097997409/sdk.json),
[기존 XML](evidence/android-kvm-20261018/run-39097997409/existing.xml),
[가입 XML](evidence/android-kvm-20261018/run-39097997409/onboarding.xml)을 보존했다.
KVM·부팅·정리는 통과했지만 release 검사는 앞선 실패 때문에 실행되지 않았다.

후속 진단은 각 입력 후와 마지막 스크롤/IME 닫기 후의 값 보존·정책 유효·owner 준비 상태를
네이티브 시험 메모리에서 boolean으로 확인한다. 값을 출력하지 않는다. 원래 30초 총기한을 공유해
세션 생성·잠금 해제·main 복귀를 나눠 확인하고, 완료 시 세 조건이 동시에 참임을 다시 요구한다.
마지막 실제 API 홈 판정도 유지한다. 고정 stage 36개, reason 13개, 표시 상태 4비트에 더해
세션/잠금/main의 flow 3비트와 공개 고정 상태 문구에 대응하는 status 20개만 진단에 허용한다.
상태 분류는 EditText를 제외하며 입력과 닮은 문자열도 상태로 수집하지 않는다.
정제 도구·workflow 이중 정제와 부정 사례, Kotlin 계측 컴파일이 통과했다.
제품 코드·기기 인증 조건·보안 가드는 변경하지 않았고, 가입 성공은 새 원격 결과로 판정한다.


다섯 번째 실행(PR head `c4bccb7`)은 마지막 스크롤 이후의 입력 보존·정책·owner 준비 검사를
모두 통과했으나 `SESSION_CREATED`에서 실패했다. flow `000`, 공개 상태 `INPUT_INVALID`이며
세션 생성·잠금 해제·main 복귀가 확인되지 않았다. 이 상태는 앞선 빈 입력 시험의 문구가 남았을
가능성도 있어, API가 유효한 등록 요청을 거절했다는 뜻으로 해석하지 않는다.
[요약](evidence/android-kvm-20261018/run-39099073948/summary.json),
[SDK](evidence/android-kvm-20261018/run-39099073948/sdk.json),
[기존 XML](evidence/android-kvm-20261018/run-39099073948/existing.xml),
[가입 XML](evidence/android-kvm-20261018/run-39099073948/onboarding.xml)을 보존했다.
KVM·부팅·정리는 성공했고 release 격리 검사는 앞선 실패 때문에 실행되지 않았다.


후속 helper는 IME를 닫은 뒤와 각 실제 swipe 이후에 프레임별 scroll 위치·대상/viewport/window
영역·focus·layout·IME 상태를 관찰한다. 연속 1초 동안 상태가 같고 뒤따르는 프레임도 안정적이어야
다음 입력/탭으로 진행하며 대기는 10초로 제한한다. 화면 밖의 대상도 먼저 정지 여부를 확인한 뒤
실제 swipe로 가져오고, 최종 90% 표시 기준은 유지한다. 좌표나 입력은 진단에 출력하지 않는다.

이 보완의 근거는 Android 16의 [ScrollView 구현](https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-16.0.0_r1/core/java/android/widget/ScrollView.java)이다.
fling 또는 edge effect 중 첫 `ACTION_DOWN`을 부모가 가로채면 버튼 탭이 스크롤 정지로 소비될 수 있다.
[EdgeEffect 구현](https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-16.0.0_r1/core/java/android/widget/EdgeEffect.java)은 glow와 stretch가
다른 종료 방식을 사용한다. 1초를 모든 기기의 효과 종료 보장 시간으로 주장하지 않으며,
앞선 실패의 원인이 이 동작이었다고 확정하지 않는다. 실제 요청의 재제출이나 listener 직접 호출은 없다.

최종 탭에는 시험용 listener로 고정 5비트와 공개 status enum만 추가 관찰한다. 비트 순서는 표시 이름
보존/비밀번호 비움/확인 비밀번호 비움/status 갱신/window focus 상실이며 `tap_status`는 탭 반환 직후
관찰한 공개 상태다. 같은 문구를 다시 설정해도 갱신으로 기록한다. 정상 화면 전환도 focus를 잃으므로
focus 비트만으로 실패를 단정하지 않는다. listener는 관찰 직후 제거하고 입력 내용은 출력하지 않는다.
진단은 stage 36개/reason 14개/status 20개 및 고정 비트만 허용하며, 새 tap 비트와 tap_status는 함께 있어야
보존한다. 두 차례 정제 이후에도 같은 규칙을 적용하고, 잘못된 비트·부분 필드·동적 문자열은 제거한다.
기존 세션 생성/잠금 해제/main 복귀의 총 30초 기한, 최종 동시 상태와 실제 API 홈 검증을 유지한다.


## 취소 후 상태 재조회와 시험 서버 연결 수명

PR #95 head `5a869aa`의 [39100098328](https://github.com/jihoon22-lee/SallimBook/actions/runs/39100098328)
실행 1회와 코드 변경 없는 재실행 1회는 모두 `SECOND_SETUP_AVAILABLE / ASSERTION`으로
실패했다. 실제 checkout은 `67ef59af585a49e558e18c44f01bc5af0a0dd391`이며 각각 13건 중
11 PASS / 1 FAIL / 1 조건부 SKIP이다. 닫기 후 원래 Main의 resumed/focus는 한 차례 확인했지만,
그 뒤 시작 버튼 준비가 30초 안에 확인되지 않았다. 최종 제출에는 도달하지 않았으며
`TAP=-----`, `TAP_STATUS=NOT_CHECKED`다. KVM·부팅·기기·정리는 통과했고 release 검사는 생략됐다.
[1차 요약](evidence/android-kvm-20261018/run-39100098328/summary.json),
[1차 가입 XML](evidence/android-kvm-20261018/run-39100098328/onboarding.xml),
[2차 요약](evidence/android-kvm-20261018/run-39100098328-attempt2/summary.json),
[2차 가입 XML](evidence/android-kvm-20261018/run-39100098328-attempt2/onboarding.xml)을 보존했다.
코드 검토만으로 정상 취소의 lifecycle race를 확정하지 않았다.

별도 로컬 재현은 실제 컴파일한 `accountHttpClient()`와 고정 OkHttp 5.4.0/Okio 3.17.0,
Uvicorn 0.54.0, 합성 HTTPS CA 및 정상 hostname 검증을 사용했다. 두 GET을 6.5초 간격으로
보내면 기본 서버에서는 첫 요청만 성공하고 두 번째는 네트워크 실패였다. 접속 시도/서버 수신은
각각 1회였다. 같은 시험에서 수정된 proxy가 HTTP/1 응답에 `Connection: close`를 명시하자
접속과 서버 수신이 각각 2회였으며 두 요청 모두 성공했다. 두 경우 모두 자동 재시도는 false였다.
[고정 결과 비교](evidence/android-kvm-20261018/fixture-connection-comparison.jsonl)를 보존했다.

근거는 [Uvicorn 0.54.0 기본 유휴 5초](https://github.com/Kludex/uvicorn/blob/0.54.0/uvicorn/config.py)와
[OkHttp 5.4.0 GET 연결 검사 선택](https://github.com/square/okhttp/blob/parent-5.4.0/okhttp/src/commonJvmAndroid/kotlin/okhttp3/internal/connection/RealRoutePlanner.kt),
[소켓 상태 검사](https://github.com/square/okhttp/blob/parent-5.4.0/okhttp/src/commonJvmAndroid/kotlin/okhttp3/internal/connection/RealConnection.kt)다.
스크롤 안정화로 사용자 동작 간격이 길어지면 시험 서버의 유휴 종료와 겹칠 수 있다.
이 로컬 재현은 실패 경로를 설명하지만, 기존 KVM 실행의 실제 소켓 상태를 소급해 확인한 것은 아니다.

수정은 일회용 loopback fixture의 HTTP/1.0·1.1 응답만 명시적으로 닫는다. 응답 body/status와
합성 신원·실제 peer 검증은 유지한다. HTTP/2와 lifespan에는 연결 헤더를 넣지 않는다.
제품 네이티브·운영 서버·재전송 금지·인증서/hostname·시간 제한은 바꾸지 않는다.
실제 wrapper를 실행하는 stdlib ASGI 회귀는 streaming body, 기존 connection 헤더 교체,
원본 message/headers 보존과 프로토콜 분기를 확인한다. 새 KVM 가입 성공 여부는 별도 결과로 판단한다.
