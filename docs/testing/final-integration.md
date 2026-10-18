# 최종 통합 검증 기록

SB-034~040 · R-01~R-22 · 2026-10-18 WSL Ubuntu.
이 기록은 0.x 통합본의 개발 검증이며 v1.0.0 출시 승인이나 Galaxy 실기기 인수를 뜻하지 않는다.
도메인별 구현·검증은 [요구사항 추적표](../requirements-traceability.md)를 함께 읽는다.

## 완료한 통합 검사

| 대상 | 명령·기준 | 실제 결과 |
|---|---|---|
| API·실제 PostgreSQL | `uv run --project services/api python scripts/test_database.py services/api/tests -q --tb=short` | **1,210 통과**, 679.18초. Starlette deprecation warning 1개 |
| DB 구조 | 위 harness의 Alembic check, downgrade base, upgrade head | 모델 차이 0, 역방향·재적용 성공, 시험 DB 중지·잠금 반환 |
| Android 전체 | Android sync 뒤 JDK 21·고정 SDK로 `:app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest :app:assembleRelease` | 최종 소스 **333 통과**, 실패·오류·건너뜀 0. debug·instrumentation·unsigned release APK 성공, 1분 29초. 기기 테스트 실행은 아님 |
| Android 실행 설정 | `python3 scripts/test_android_runtime_config.py` | bundled config 및 원격·wildcard·잘못된 navigation 거절 5개 성공. 생성 설정 원상 복원 |
| API 계약·타입 | `pnpm api:generate`, 생성 파일 `git diff --exit-code`, `pnpm typecheck` | 재생성 차이 0, 타입 오류 0 |
| 실제 HTTPS | `scripts/test_web_auth.py`와 11개 업무 선택 플래그를 각각 실행 | 인증·패스키·자산/계좌·월 기록·비교·생활비·보험·소모품·보관함·문서·내보내기·감사의 **12개 흐름 통과**. 감사 외 11개 순차 실행 414.7초 |
| 전체 웹 | `TMPDIR=/home/jihoon/.cache/sallimbook pnpm test:web --workers=2` | `1f81039` **982 통과**, 실패·건너뜀 0, 6.7분. PC/Android 크기와 native plugin 모의시험이며 실기기 인수와 구분 |
| 웹 배포 빌드 | `pnpm build` | 165 modules 성공. JS 894.22kB/gzip 231.17kB, 기존 chunk 크기 경고 남음 |
| 정적 검사 | API src/tests/migrations와 실제 HTTPS harness Ruff | 통과 |
| 저장소·운영 도구 | `python3 -m unittest discover -s tests -q` | 운영 19개 포함 **59 통과** |
| 운영 컨테이너 | `python3 -m ops.test_runtime --image LOCALLY_BUILT_API_IMAGE` | `2fbe39e`: migration/readiness, runtime DB 역할, 11가지 권한 변조 거부, 감사 UPDATE/DELETE의 42501 및 정상 INSERT/조회, UID10001, 한국어 OCR·ClamAV 업로드, AEAD 저장·다운로드, 익명 차단 통과. scanner 미준비·stale 거부, 중단→unhealthy→복구 통과 |
| 암호화 백업·복원 | 검증한 age/PostgreSQL client 경로에서 `uv run --project services/api python -m ops.test_recovery` | 실제 새 합성 DB 복원, manifest·전체 테이블 행 수·첨부 AEAD, 기존 인증 폐기와 pending/new rotation gate 통과 |
| 배포 설정 | `python3 -m ops.test_deployment --web-image LOCALLY_BUILT_WEB_IMAGE` | 고정 Caddy/Tailscale Compose, 공개 JSON/다른 경로 404 통과. 실제 tailnet 노드 등록은 미실행 |
| APK 서명 도구 | JDK 21·고정 SDK에서 `python3 -m ops.test_release --sdk /DEDICATED_ANDROID_SDK` | `fc297d2`: 합성 키로 release v2/v3 실제 빌드·서명, manifest/native 설정·zipalign·인증서·증가 versionCode·이전 APK·변조 거부 통과. 시험 키/APK 제거 |

API 전체 시험은 `013fa19`의 테스트 DB 설정으로 시작했다. 이후 통합한 보관함 재인증·내보내기
오류 처리·감사 UI/native 변경은 서버 API·테스트·마이그레이션 파일을 바꾸지 않았으며
`1f81039`와의 파일 차이가 없음을 확인했다. 프런트엔드·Android 통합 결과는 해당 최종 코드로
다시 검사했다. 이 기준과 뒤의 추가 결과를 구분하여 기록한다.

## 실패와 조치

첫 전체 API 실행은 PostgreSQL test 컨테이너의 1GiB 메모리 한도에서 WAL이 커져 backend가
종료됐다. 660개 통과·fixture 오류 9개 시점에 해당 시험만 중단했다. 일반/운영 DB의 설정과
데이터는 변경하지 않았다. 테스트 DB의 WAL·shared buffers·checkpoint 한도를 tmpfs 예산에
맞춘 뒤 위 전체 1,210개가 통과했다. fsync와 내구성 설정은 유지했다.

이전 웹 통합 실행은 766개 중 763개 통과·3개 실패였다. 한 실패에서 Vite module 로딩 중
`net::ERR_NETWORK_CHANGED` 13회를 확인했고 API 요청은 시작되지 않았다. 나머지 두 실패는
trace가 없어 같은 원인으로 확정하지 않았다. 세 시나리오를 PC/Android 크기에서 각 3회
실행한 18개는 코드 변경 없이 통과했다. 이후 전체 웹 검증에서는 Docker 네트워크 변경을
멈추고, 보관함 private/workflow 시험의 trace를 명시적으로 껐다. 최초 실행을 전체 성공으로
계산하지 않는다.

네트워크를 고정한 다음 전체 실행은 **971 통과·1 실패**(7.5분)였다. 기기별 소모품 주기를
수정한 직후 삭제할 때, 빠른 native 응답으로 loading 상태가 한 번에 렌더되면 삭제 검토의
초기 버전이 유지되는 문제를 확인했다. 최신 주기는 표시하지만 DELETE가 이전 버전으로 나가
409를 받았다. 데이터는 삭제되지 않았으며 이 실행도 전체 성공으로 계산하지 않는다.
공통 삭제 검토의 대상 ID/버전 변경을 명시적으로 처리했다. 새 회귀 10개와 기존 가전·소모품
시험 60개가 통과했고, 같은 회귀를 구 코드에 적용하면 기대 버전 2 대신 1을 보내 실패함을
확인했다. 수정 후 실제 `--homecare` HTTPS와 위 전체 **982개**가 통과했다.

최초 운영 이미지의 실제 첨부 시험은 저장소 경계 검사에서 실패했다. 이미지의 API source 경로가
원래 저장소보다 얕아 repository root를 잘못 계산한 원인이었다. `Dockerfile.api`가 원래의
`services/api/src` 깊이를 유지하도록 수정하고 전체 운영 smoke를 재실행해 통과했다.
스토리지 경계 검사는 약화하지 않았다. 운영 시험이 만든 container/network/volume과 테스트 DB는
정리했으며 실제 운영 서비스·사용자 자료는 만들거나 변경하지 않았다.

## 추가 검증 상태

설정·감사 UI 44개와 기존 경로 16개, native 감사 bridge 38개는 각 기능 검증에서 통과했다.
실제 감사 HTTPS도 `ba4d0ac`에서 통과했다. 현재 가계 52개 기록의 50+2 페이지, 값 없는
메타데이터·필터, 다른 가계 actor 404, 최근 인증 만료 후 안전한 조회, 로그아웃 뒤 401과
화면 제거, no-store·브라우저 저장소 미사용을 검증했다.
최종 실제 HTTPS는 `--passkeys`, `--finance`, `--months`, `--comparison`, `--cashflow`,
`--insurance`, `--homecare`, `--vault`, `--documents`, `--exports`, `--audit`를 각각 실행했다.
실제 API/PostgreSQL을 사용했고 HTTP route mock은 없었다. WebAuthn은 Chromium 가상 인증기의
실제 서명을 사용했고, 문서/내보내기는 고정 이미지의 실제 검사 도구와 연결했다.
각 실행은 일회용 schema·임시 인증서·합성 계정·private 출력물을 정리하고 DB를 중지했다.
최종 전체 웹은 위 버전 상태 수정과 추가 회귀 검증 뒤 Docker 네트워크 변경 없이 통과했다.
debug CVC 인수 도구는 실제 store를 별도 합성 namespace에서 사용하며 일반 CVC gate는 닫혀 있다.
333개 JVM에는 시한 경계 회귀 3개를 포함한다. 테스트 APK의 기기 검사 11개(새 CVC 7·기존 WebView 4)는
빌드만 했고 실행하지 않았다. 최종 unsigned release의 전체 DEX 2개에서 debug marker 9개가
모두 없음을 확인했다. 실제 서명·기기 인수와 이 정적 검사를 구분한다.

최종 로컬 APK SHA-256:

- debug: `4799cc5e88c440899d72219b55487cafbf81de60100ab9e5cc9a9c98cbf7f81f`
- androidTest: `2949ffa59d87ee41a1ec97333f0b9308e4a1af62ffe6d3fb5a075f650f661b42`
- unsigned release: `a6534bd9c69ea4af7dffae5773ddd7403925f8545af46037a0deda39b5710403`

공개 origin/RP/cert가 공란인 개발 검증 산출물이므로 실제 서버 로그인용 배포 APK가 아니다.
운영 최종 통합 `2fbe39e183582cfa4b0d0b085224bd547d20a40a`의 깨끗한 archive에서 API/웹
이미지를 함께 빌드했다. 실제 이미지의 OCI revision·역할 label과 내부 `source-revision.json`이
이 commit과 일치하고, 다른 revision 또는 API/웹 역할을 요구하면 preflight가 거부함을 확인했다.

- 빌드 입력 receipt SHA-256: `a9329fcbb8c7e264a027c2d992955efd73ae84f1cac08ad2ed545ede338d2fda`
- API image ID/index: `sha256:175eee925f55ab32388c9ff05a2686ac191e7fc022419101563700c81cd3fddb`
- API linux/amd64 manifest: `sha256:60867c8e4a05968f4a7b0bc4a914dcf7666d5da36258f426a8ac4eec90b6858a`
- 웹 image ID/index: `sha256:c34671fd354482b3ce7173d70f934df9faa0e09b3b32b24e5f21121db3e57d20`
- 웹 linux/amd64 manifest: `sha256:2dcf18dd8b737b102113a2de282f23dc051b03ffb50190827b1afe92a4e6c453`

scanner가 없는 실제 container에서 두 health mode가 실패했고, 실제 Unix PING·엔진/DB 검사가
정상일 때 통과했다. 시험 프로세스의 시계를 8일 뒤로 바꾸면 stale DB로 두 mode 모두 거부했다.
실제 scanner를 중지하면 API의 DB HTTP readiness가 200인 동안에도 Docker health는 unhealthy로
바뀌었고, scanner 재시작 뒤 healthy로 복구했다. 이 검사는 운영 도구만 변경했으며 API·웹·Android
런타임 소스는 앞의 전체 검증과 같다. 시험 container/network/volume을 모두 제거했다.
실제 운영 노드·서명키·휴대전화 인수는 이 합성 검증과 별도로 진행한다.

PR #85 첫 통합 리뷰 후 문서 이력의 다음 페이지가 남아 있을 때 재연결을 허용하던 화면 조건을
보완했다. 기존 76개와 신규 16개를 합친 문서 화면 **92개**가 통과했다. 수정 전 코드에서 같은
회귀가 실패했고, 다음 페이지 지연·503·재시도·마지막 활성 연결·다른 대상 연결을 웹/native
경로와 두 화면 크기에서 검사했다. 타입/빌드도 통과했으며 최종 bundle은 894.41kB/gzip 231.22kB다.
위 전체 982개 기록은 이 추가 회귀 이전 실행이며 이 수정 뒤 전체 수를 재실행했다고 표시하지 않는다.
운영 node의 Docker 로그는 인증 URL 보존을 피하도록 none으로 제한했고 기존 도구 59개를 재검증했다.

GitHub Actions는 기존 PR부터 runner·step이 시작되기 전에 종료되는 상태를 관찰했다.
조회 권한 때문에 일부 상태/로그 API도 거절됐다. 로컬 동등 명령 결과와 원격 CI 성공을
구분하며, 원격 실패의 정확한 계정/결제 원인은 확인되지 않았다.

PR #86의 재현 명령 후속 정정은 필수 `--web-image` 인자를 문서에 보완한 변경이다.
배포 이미지와 APK의 구현 소스는 `d9eb6e245022c9d8f6502339437140880ec44d71`로 유지하며,
이 문서 정정으로 실행 코드·이미지·APK를 변경하거나 다시 빌드하지 않았다.

## 남은 출시 인수

실제 Galaxy 2대의 기기 인증·Keystore 무효화·취소·백그라운드·재설치·CVC 백업/전송 차단,
TalkBack·확대 글꼴·양 계정 교차 편집, 운영 서명 APK의 데이터 보존 업데이트는 아직 실행하지
않았다. 실제 전용 Tailscale 노드·서비스 FQDN/RP/DAL·VPN 외부 차단·운영 백업 보관과 복원도
별도 입력과 실행 증거가 필요하다. 기존 호스트 Tailscale 및 다른 서버 설정은 변경하지 않았다.

CVC 활성화 게이트는 false다. 실제 기기 보안 검증과 사용자 선택을 모두 충족한 뒤 활성화하며,
출시 게이트를 충족하기 전에는 관련 Issue를 완료 처리하거나 v1.0.0으로 배포하지 않는다.
