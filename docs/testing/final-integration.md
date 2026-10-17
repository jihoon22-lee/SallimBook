# 최종 통합 검증 기록

SB-034~040 · R-01~R-22 · 2026-10-18 WSL Ubuntu.
이 기록은 0.x 통합본의 개발 검증이며 v1.0.0 출시 승인이나 Galaxy 실기기 인수를 뜻하지 않는다.
도메인별 구현·검증은 [요구사항 추적표](../requirements-traceability.md)를 함께 읽는다.

## 완료한 통합 검사

| 대상 | 명령·기준 | 실제 결과 |
|---|---|---|
| API·실제 PostgreSQL | `uv run --project services/api python scripts/test_database.py services/api/tests -q --tb=short` | **1,210 통과**, 679.18초. Starlette deprecation warning 1개 |
| DB 구조 | 위 harness의 Alembic check, downgrade base, upgrade head | 모델 차이 0, 역방향·재적용 성공, 시험 DB 중지·잠금 반환 |
| Android 전체 | Android sync 뒤 JDK 21·고정 SDK로 `:app:testDebugUnitTest :app:assembleDebug :app:compileReleaseKotlin` | `ba4d0ac` **330 통과**, 실패·오류·건너뜀 0. debug APK·release Kotlin 성공, 1분 5초 |
| Android 실행 설정 | `python3 scripts/test_android_runtime_config.py` | bundled config 및 원격·wildcard·잘못된 navigation 거절 5개 성공. 생성 설정 원상 복원 |
| API 계약·타입 | `pnpm api:generate`, 생성 파일 `git diff --exit-code`, `pnpm typecheck` | 재생성 차이 0, 타입 오류 0 |
| 웹 배포 빌드 | `pnpm build` | 165 modules 성공. JS 894.13kB/gzip 231.15kB, 기존 chunk 크기 경고 남음 |
| 정적 검사 | API src/tests/migrations와 실제 HTTPS harness Ruff | 통과 |
| 저장소·운영 도구 | `python3 -m unittest discover -s tests -v` | 운영 14개 포함 **54 통과** |
| 운영 컨테이너 | `python3 -m ops.test_runtime --image LOCALLY_BUILT_API_IMAGE` | `fc297d2`: migration/readiness, runtime DB 역할, 4가지 권한 변조 거부, UID10001, 한국어 OCR·ClamAV 업로드, AEAD 저장·다운로드, 익명 차단 통과 |
| 암호화 백업·복원 | 검증한 age/PostgreSQL client 경로에서 `uv run --project services/api python -m ops.test_recovery` | 실제 새 합성 DB 복원, manifest·전체 테이블 행 수·첨부 AEAD, 기존 인증 폐기와 pending/new rotation gate 통과 |
| 배포 설정 | `python3 -m ops.test_deployment` | 고정 Caddy/Tailscale Compose, 공개 JSON/다른 경로 404 통과. 실제 tailnet 노드 등록은 미실행 |
| APK 서명 도구 | JDK 21·고정 SDK에서 `python3 -m ops.test_release --sdk /DEDICATED_ANDROID_SDK` | `fc297d2`: 합성 키로 release v2/v3 실제 빌드·서명, manifest/native 설정·zipalign·인증서·증가 versionCode·이전 APK·변조 거부 통과. 시험 키/APK 제거 |

API 전체 시험은 `013fa19`의 테스트 DB 설정으로 시작했다. 이후 통합한 보관함 재인증·내보내기
오류 처리·감사 UI/native 변경은 서버 API·테스트·마이그레이션 파일을 바꾸지 않았으며
`ba4d0ac`와의 파일 차이가 없음을 확인했다. 프런트엔드·Android 통합 결과는 해당 최종 코드로
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
최종 전체 웹·나머지 실제 HTTPS 업무 검증은 실행 완료 후 결과를 추가한다.
새 debug CVC acceptance proof의 release 제외 검사는 해당 Android 변경 이후 추가한다.
실행 대기 상태를 통과로 표시하지 않는다.

GitHub Actions는 기존 PR부터 runner·step이 시작되기 전에 종료되는 상태를 관찰했다.
조회 권한 때문에 일부 상태/로그 API도 거절됐다. 로컬 동등 명령 결과와 원격 CI 성공을
구분하며, 원격 실패의 정확한 계정/결제 원인은 확인되지 않았다.

## 남은 출시 인수

실제 Galaxy 2대의 기기 인증·Keystore 무효화·취소·백그라운드·재설치·CVC 백업/전송 차단,
TalkBack·확대 글꼴·양 계정 교차 편집, 운영 서명 APK의 데이터 보존 업데이트는 아직 실행하지
않았다. 실제 전용 Tailscale 노드·서비스 FQDN/RP/DAL·VPN 외부 차단·운영 백업 보관과 복원도
별도 입력과 실행 증거가 필요하다. 기존 호스트 Tailscale 및 다른 서버 설정은 변경하지 않았다.

CVC 활성화 게이트는 false다. 실제 기기 보안 검증과 사용자 선택을 모두 충족한 뒤 활성화하며,
출시 게이트를 충족하기 전에는 관련 Issue를 완료 처리하거나 v1.0.0으로 배포하지 않는다.
