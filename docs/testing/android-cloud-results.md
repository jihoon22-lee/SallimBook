# Android 클라우드 실행 결과 — 2026-10-18

이 기록은 `android-cloud-handoff.md`의 실행 결과이며 v1 출시 승인이나 Galaxy 보안 인수가 아니다.
운영 계정·데이터·API origin·Tailscale·서명키·필드 암호화 키를 사용하지 않았다.
일반 CVC gate는 false로 유지했다.

## 기준과 변경

- 시작 기준: `origin/main` **173213ab2057216e6358f78606bcf2a8bbebdf9c**, clean clone.
- 브랜치: `test/android-cloud-acceptance-20261018`.
- 실행 기반 코드 commit: `aeb34298fbb3f68a5897cc17cda5f7c4148dee12`.
- 완료 전 원격 main을 다시 조회해 시작 SHA와 동일함을 확인했다.
- 최초 push는 GitHub 이메일 개인정보 보호(GH007)로 거절됐다. 미게시 커밋의 작성자 이메일만 noreply로 바꿨으며, 검증한 코드 tree가 동일함을 확인했다.
- 관련: #17, #43, #48, #87; R-01/R-02/R-10/R-11/R-12/R-19/R-20/R-21.
- `11e3333`: 공개 파일 거절 시험의 합성 파일 권한을 0644로 명시. 기본 umask 077에서도 거절 경로를 시험한다.
- `175602a`: 최초 등록 CLI의 공개 디렉터리 fixture를 0755로 명시. `mkdir(mode=0755)`도 umask 영향을 받는 문제를 수정했다.
- 제품의 권한 검사·API 계약·마이그레이션·의존성 잠금·운영 설정은 변경하지 않았다.

추가한 실행 기반:

1. `scripts/probe_android_avd.py`: 별도 AVD/ADB 서버, 포트 충돌 거절, 2GiB 사용자 파티션,
   부팅 제한 시간, `sys.boot_completed`, API/ABI/WebView 정보, 본인 프로세스 정리.
2. `scripts/test_android_cloud.py`: 기존 계측 12개 → 일회용 PostgreSQL schema와 실제 Alembic/FastAPI →
   임시 HTTPS → 네이티브 첫 시작 시험. `--host-only`/`--build-only`는 Android 실행으로 집계하지 않는다.
3. `AndroidCloudOnboardingTest`: A01 중 취소·빈 입력 거절·합성 이름/암호 등록·실제 세션·번들 홈 확인.
   Espresso로 native 입력을 조작하며 JS에 암호/토큰을 주입하지 않는다. 비밀이 포함될 수 있는 Espresso 실패 상세는 고정 단계명으로 정제한다.
4. `sallimbookCloudFixture` Gradle 속성으로 **debug source set만** 외부 임시 manifest/공개 시험 CA를 선택한다.
   일반 빌드는 이 속성을 사용하지 않는다. TLS hostname 검사와 cleartext 거절을 유지한다.
5. `scripts/inspect_android_cloud_apks.py`: APK SHA-256·패키지·버전·공개 서명 fingerprint,
   release의 모든 ZIP entry/DEX/UTF-16 리소스에서 시험 marker 유입 검사.

시험 신원 프록시는 loopback에만 열리고 수신 Tailscale 헤더를 제거한 뒤 합성 신원을 주입한다.
실제 peer 검사를 포함한 제품 인증 코드는 그대로 실행한다. 실제 Tailscale 신원 검증 증거가 아니다.
각 A01 실행은 빈 schema로 시작한다. H2를 먼저 넣으면 최초 시작 조건이 닫히므로 이 제한된 A01 fixture는
H2를 만들지 않는다. H1/H2 권한·업무 전체 Android 시나리오는 별도 미완료다.

## 환경

| 항목 | 실제 값 |
|---|---|
| OS/CPU | Debian 13.6, Linux 6.18.55, x86_64, Xeon Platinum 8573C, 5 vCPU |
| 메모리/디스크 | 시작 시 약 17GiB RAM, swap 없음; workspace 약 30GiB 여유, `/tmp` 별도 8.8GiB |
| 가상화 | `/dev/kvm` 없음, vmx/svm 미노출. `emulator -accel-check` exit 3 |
| JDK | Temurin JDK 21.0.12.1+1. 기본 설치 Java는 javac 없는 JRE였으므로 전용 JDK 설치 |
| Node/pnpm | 24.18.0 / 9.15.9, frozen lockfile 설치 |
| Python/uv | Python 3.14.7. 초기 uv 0.12.23; CI 고정 0.12.5로도 frozen sync 재확인 |
| Android | compile/target 36, min 30, app build-tools 36.0.0; 의존 모듈에서 35.0.0도 설치 |
| SDK CLI | 15859902, 저장소 설치기의 SHA-256 검증 |
| Emulator | 37.2.12.0, build 16428233, software `-accel off`, SwiftShader, RAM 2048MiB 요청 |
| 이미지 | Google APIs x86_64 API 36 revision 7 / API 30 revision 16 |
| ADB | platform-tools 37.0.1; 세션 전용 서버 5050/5051, emulator-5582/5584 |
| PostgreSQL | 실제 18.6, 저장소 고정 이미지 digest, `db-test` tmpfs/loopback 18745 |
| 브라우저 | Playwright Chromium 156.0.8078.4 실제 headless launch/title 확인 PASS |
| 네트워크 | 공식 Google/Node/Gradle/Maven/npm/PyPI/GitHub 다운로드와 Docker pull 가능, 세션 proxy/CA 사용 |

이미지·에뮬레이터 revision/공식 archive URL·size·SHA-1은 첨부 `sdk-packages.json`에 보존한다.
JDK의 Gradle 통신에는 세션 HTTP/HTTPS proxy와 `/etc/ssl/certs/java/cacerts`를 명시했다.
TLS 검증을 비활성화하지 않았다. SDK 설치와 Gradle 자동 설치가 겹쳐 생긴 platform-tools 복제 경로 경고도 있었으며,
실제 호출 대상은 `platform-tools/adb` 37.0.1이다.

## 실행 상태

`PASS / FAIL / SKIPPED / BLOCKED_ENV / NOT_RUN`을 구분하며,
소스 선언 수를 runtime discovery로 표시하지 않는다. XML의 조건부 skip과 Gradle의 `NO-SOURCE`는 통과 수에 포함하지 않는다.

확정된 결과:

- **PASS**: frozen Node/Python 설치, TypeScript 검사, Android sync.
- **PASS**: JVM 356개, 실패/오류/건너뜀 0; 일반 debug APK·계측 APK·unsigned release APK 조립.
- **PASS**: 최종 도구 시험 74개. 이 안에 cloud 실행기/전체 DEX 검사 자체 시험 6개가 포함된다.
- **FAIL → PASS**: 운영 도구의 공개 파일 fixture 1개, 초기 등록 CLI 공개 디렉터리 fixture 1개.
  후자는 umask 022/077 양쪽에서 개별 재실행했다. 제품 보안 검사 실패가 아니라 잘못된 시험 전제였다.
- **FAIL**: 최초 전체 PostgreSQL/API 실행은 1,246개 중 **1,245 PASS / 1 FAIL / 0 SKIPPED**.
  실패는 위 디렉터리 fixture 1개다. 수정 후 해당 1개와 실제 Alembic upgrade/check/downgrade/upgrade는 PASS.
  수정 후 전체 1,246개는 재실행하지 않았다.
- **PASS**: 빈 schema 실제 migration, TLS hostname 검증을 유지한 setup status 조회,
  잘못된 hostname 거절, 시험용 debug/계측 APK 조립 및 시험 overlay 속성을 지정한 일반 release 조립.
  시험 전용 origin을 release에서는 공란으로 덮어썼다. 생성 CA/키와 schema/서버는 종료 후 제거했다.
- 신규 fixture 첫 실행은 허용되지 않은 schema prefix 때문에 **FAIL**했으며, 기존 격리 정책이 허용하는
  `sallimbook_test_<uuidhex>`로 수정한 뒤 위 단계 전체를 재실행해 통과했다.
- **PASS**: 일반 release APK 전체 517개 entry, DEX 2개에서 시험 CA marker·계측 클래스·debug Activity 미포함.
  시험 빌드 후 release도 다시 검사했고 loopback HTTPS 시험 origin 유입이 없었다.
- **FAIL (기존 범위 밖 lint)**: 추가로 `ruff check tests/operations/test_operations.py`까지 넓혔을 때
  기존 SIM117 스타일 오류 5개가 보고됐다. 수정한 두 권한 fixture와 무관한 기존 중첩 with 문이며 그대로 남겼다.
  신규 runner/검사기/시험 및 수정한 API 시험 파일의 Ruff 검사는 PASS다.
- **BLOCKED_ENV**: API 36 software 부팅 602.11초 관측(600초 deadline + 마지막 ADB 호출).
  ADB `device`까지 진행했으나 `sys.boot_completed=1` 미확인. APK 설치/계측 실행 없음.
- **BLOCKED_ENV**: API 30 software 부팅 602.79초 관측. ADB `device`, zygote `running`은 확인했으나
  `sys.boot_completed=1` 미확인. WebView provider 버전·실제 APK 설치·runtime test discovery를 확보하지 못했다.
  두 AVD 모두 emulator 종료와 전용 ADB server 종료(exit 0)를 확인했다.
- 기존 계측 12개와 신규 계측 1개는 **실행 0개**다. 실제 계측 PASS/FAIL/SKIPPED는 각각 0이며
  **13개 BLOCKED_ENV**로 소스 목록에 기록했다. 조건부 생체 시험의 skip을 실제 관측한 것처럼 기록하지 않았다.
- 최초 API 36 준비는 기본 12GiB 파티션이 `/tmp` 8.8GiB보다 커 부팅 전에 종료했다.
  2GiB 파티션으로 수정 후 위 제한된 software 부팅 한 번을 수행했다.

## A01~A13 범위

| ID | 상태 | 실제 범위 / 남은 조건 |
|---|---|---|
| A01 | NOT_RUN | 부분 native UI 시험은 구현·컴파일. 취소/빈 입력/등록/홈이 대상이며 중복 시작·응답 손실은 아직 별도 계측 없음 |
| A02 | NOT_RUN | 코드 생성/연결/만료/재사용/로그인 선택의 Android E2E 미구현·미실행 |
| A03 | NOT_RUN | 전체 잠금/회전/59초·60초/이전 세대 응답 Android 사용자 흐름 미실행 |
| A04 | NOT_RUN | T-01~T-07 실제 APK 흐름 미실행. 서버/JVM 결과를 대체 증거로 쓰지 않음 |
| A05 | NOT_RUN | T-08~T-11 실제 APK 흐름 미실행 |
| A06 | NOT_RUN | T-12~T-19 실제 APK 흐름 미실행 |
| A07 | NOT_RUN | T-20~T-24 실제 APK 흐름 미실행 |
| A08 | NOT_RUN | 실제 Android 파일 제공자·첨부·내보내기 미실행 |
| A09 | NOT_RUN | native/web 키 공유·복구·회전·보관함 실제 사용자 흐름 미실행; 일반 CVC gate 유지 |
| A10 | NOT_RUN | H1/H2 및 두 사용자 Android/PC 클라이언트 조합 미실행 |
| A11 | NOT_RUN | 두 versionCode 업데이트/재설치 미실행. 단일 versionCode 1 APK 서명 검사만 수행 |
| A12 | NOT_RUN | 키보드/큰 글꼴/접근성/네트워크 실패 실제 APK 흐름 미실행 |
| A13 | BLOCKED_ENV | 실제 native passkey 제공자·RP/DAL·등록된 인증수단 없음. Chromium launch로 대체하지 않음 |

전체 시나리오를 완료한 runner라고 주장하지 않는다. 이번 변경은 부팅/기존 계측/부분 A01 실행 기반이며,
나머지 사용자 흐름 구현과 실행은 정상 부팅하는 AVD 또는 실제 기기에서 계속해야 한다.

## 증거 파일

비밀·키·원문 logcat·bugreport·화면/trace는 포함하지 않았다. XML은 실제 출력에서 testcase 이름/시간/상태를
보존하고 속성·system-out·상세 진단을 제거한 공유용 사본이다. 원본 실행의 FAIL을 PASS로 고치지 않았다.
매개변수 testcase 이름에 포함될 수 있는 합성 자격증명은 `parameter-case-N`으로 대체했다.
메서드 이름과 같은 메서드 내 실행 순서/상태는 보존했다.

- [JVM 356개 XML](evidence/android-cloud-20261018/jvm.xml)
- [최초 PostgreSQL/API 1,246개 XML](evidence/android-cloud-20261018/api-database.xml)
- [실패한 권한 fixture 개별 재현](evidence/android-cloud-20261018/identity-umask-before.xml),
  [수정 후 재검증](evidence/android-cloud-20261018/identity-umask-after.xml),
  [DB runner·migration 재검증 XML](evidence/android-cloud-20261018/migration-regression.xml)
- [일반 APK hash/ID/version/서명 공개 fingerprint](evidence/android-cloud-20261018/apks-baseline.json)
- [시험 CA를 포함한 debug APK와 정상 release의 메타데이터/전체 DEX 검사](evidence/android-cloud-20261018/apks-fixture.json)
- [시험 후 공란 origin·시험 CA 없는 일반 debug로 복원한 최종 APK 메타데이터](evidence/android-cloud-20261018/apks-final-normal.json)
- [고정 SDK/이미지 공식 메타데이터](evidence/android-cloud-20261018/sdk-packages.json)
- [API 36 초기 파티션 실패](evidence/android-cloud-20261018/api36.json),
  [API 36 software deadline/종료 결과](evidence/android-cloud-20261018/api36-software.json),
  [API 30 software deadline/종료 결과](evidence/android-cloud-20261018/api30.json)
- [계측 소스 선언 13개 목록](evidence/android-cloud-20261018/instrumentation-discovery.json):
  기존 12개 + 신규 부분 A01 1개. **runtime discovery 또는 계측 실행 XML이 아니다.**

일반 debug ID는 `io.github.jihoon22lee.sallimbook.debug`, versionCode 1 / `0.1.0-dev`이고,
release는 `io.github.jihoon22lee.sallimbook`, versionCode 1 / `0.1.0` unsigned다.
세션에서 생성한 debug 서명의 SHA-256 공개 fingerprint는
`1fc5785141acab984c17d0a27076fc200dbe6f14cf1d863ddc36e0f81e166e5b`이다.
APK와 private signing key는 Git에 넣지 않았다. 시험용 debug APK는 배포하지 않는다.

## 정리 확인

두 AVD와 전용 ADB 서버를 종료했고 5050/5051, 5582~5585 포트에 listener가 없음을 확인했다.
일회용 schema·HTTPS 서버·임시 TLS key/CA 디렉터리를 제거했다. 본 작업에서 만든 `db-test` 컨테이너와
전용 Compose 네트워크도 제거했다. 일반 debug APK를 공란 origin/시험 CA 없는 설정으로 다시 빌드해 검사했다.
이 세션의 합성 `.env`와 자동 생성된 debug signing key는 최종 artifact 기록 후 삭제했다.
SDK/JDK/Node와 빌드 산출물은 재현을 위해 작업 공간에 남겼다. 재실행은 `setup_dev.py`로 새로운 합성 설정을 만든다.

## 재실행 명령

JDK 21, 저장소 고정 Node/pnpm/uv와 전용 SDK를 선택한다. 클라우드에서는 Java에도 세션 proxy/CA를 설정한다.
기존 운영 `.env`를 복사하지 않는다. 아래 `setup_dev.py`는 새 checkout에서 합성 개발/시험 자격증명만 생성한다.

```bash
# SDK 설치 후 별도 공식 패키지 설치; 기록한 revision과 대조한다.
python3 scripts/setup_android_sdk.py --sdk-root "$ANDROID_HOME" --accept-licenses
"$ANDROID_HOME/cmdline-tools/15859902/bin/sdkmanager" --sdk_root="$ANDROID_HOME" \
  emulator platform-tools 'system-images;android-36;google_apis;x86_64'

pnpm install --frozen-lockfile
uv sync --project services/api --frozen
python3 scripts/setup_dev.py
pnpm android:sync
apps/client/android/gradlew -p apps/client/android --no-daemon --max-workers=1 \
  :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest :app:assembleRelease

# 새 output 경로만 허용. KVM이 있는 환경은 --software를 생략한다.
python3 scripts/probe_android_avd.py --sdk-root "$ANDROID_HOME" \
  --image 'system-images;android-36;google_apis;x86_64' \
  --output /tmp/new-sallimbook-api36-results --boot-timeout 600 --software \
  --command uv run --project services/api python scripts/test_android_cloud.py

# 기기가 없어도 실행 가능한 HTTPS/schema/호스트명 검사와 시험 빌드.
uv run --project services/api python scripts/test_android_cloud.py --host-only
uv run --project services/api python scripts/test_android_cloud.py --build-only
python3 scripts/inspect_android_cloud_apks.py --output /tmp/sallimbook-apks.json

# 독립 보조 검증; Android E2E 통과로 합산하지 않는다.
uv run --project services/api python scripts/test_database.py services/api/tests \
  --junitxml=/tmp/sallimbook-api-database.xml
python3 -m unittest discover -s tests -v
```

`--existing-only`는 기존 계측 12개만 실행한다. API 30에는 image/port/adb-port/output을 바꿔 순차 실행한다.
실제 Android 연결 명령은 probe가 생성한 `sallimbook-probe` AVD인지 확인하고 그 serial만 사용한다.
기본 AndroidCloudOnboardingTest는 전용 fixture 인자가 없으면 skip하며, 이를 성공으로 집계하지 않는다.
시험 APK는 배포용이 아니며, 일반 origin 공란 APK 빌드로 가입/로그인 성공을 주장하지 않는다.

## Galaxy에 남는 검사

- 강한 생체 등록/취소/잠금 제한/등록 변경과 실제 CryptoObject·키 무효화, 제조사 하드웨어 보안 수준.
- 화면 캡처·최근 앱·외부 디스플레이, 접근성/키보드/자동완성에 대한 비밀 화면 보호.
- 강제종료·회전·화면 잠금·59초/60초 복귀·늦은 HTTP 응답과 앱 잠금/보관함 30초 만료.
- 두 실제 기기 동시 편집/멱등성, 키 공유·복구·회전 중단, 제조사 백업/기기 이전과 재설치.
- 시험 동일 서명 업데이트와 별개인 실제 정식 APK 업데이트·데이터 보존·서명/DAL/패스키 제공자 검증.
- 실제 파일 제공자 권한/취소/부분 저장과 문서·내보내기 실패 처리.

운영 백업/복원과 v1 전체 인수는 이 작업의 에뮬레이터/호스트 결과로 대체하지 않는다.
