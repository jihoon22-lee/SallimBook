# 모바일 첫 시작·배우자 연결 통합 검증

Issue #87 · R-01/R-02 · 2026-10-18.
[ADR 0008](../adr/mobile-first-start.md), [API 계약](../api-contract.md),
[Android 검증](native-onboarding.md)의 구현을 통합한 기록이다.

첫 사람은 웹 또는 앱에서 이름과 비밀번호를 설정하면 바로 홈으로 들어간다. 배우자는
첫 사람이 만든 8자리 코드로 같은 가계에 연결된다. 기존 빈 가계는 보존하고, 사용자·구성원이
하나라도 존재하면 최초 시작을 다시 열지 않는다. 비밀번호·코드는 사용자가 직접 입력한다.

## 실제 HTTPS

`uv run --project services/api python scripts/test_web_auth.py --onboarding` 통과.
일회용 빈 PostgreSQL schema, 임시 TLS 인증서, 합성 두 계정을 사용했다. HTTP mock 없이
모바일 너비의 브라우저에서 다음을 확인했다.

- 첫 시작·201 응답·자동 홈 진입, Secure/HttpOnly/SameSite=Strict 세션 쿠키, reload 후 같은 구성원.
- 배우자 코드 생성·기본 가림, 다른 브라우저의 연결·자동 홈 진입, 같은 가계의 서로 다른 구성원 두 명.
- 첫 등록 재시도 409, 사용한 코드 재사용 400, no-store와 local/sessionStorage·CacheStorage 미사용.

이 harness는 검증된 프록시 입력을 합성 헤더로 모델링한다. 실제 Tailscale 신원 검증을 대신하지
않는다. 운영의 Serve 헤더 제거·재설정과 node peer 경계는 ADR의 고정 버전 구현 및 운영 점검을
함께 대조한다. 종료 시 schema·인증서·fixture를 제거하고 시험 DB를 중지했다.

같은 통합 소스에서 기본 `scripts/test_web_auth.py`와 `--passkeys`도 각각 다시 통과했다.
기존 쿠키 인증·재인증·로그아웃과 Chromium 가상 인증기의 실제 WebAuthn 서명, 기존 긴 초대
경로의 step-up 동작을 검증했다. 새 등록 검증까지 실제 HTTPS 흐름 3개를 순차 실행했다.

## 검증 범위와 남은 인수

통합 소스에서 다음 명령을 실행했다.

| 대상 | 실행 | 결과 |
|---|---|---|
| 인증·패스키·등록·설정 API | `uv run --project services/api python scripts/test_database.py services/api/tests/test_identity.py services/api/tests/test_passkeys.py services/api/tests/test_onboarding.py services/api/tests/test_onboarding_regressions.py services/api/tests/test_config.py -q --tb=short` | **156 통과**, 80.67초. Alembic 차이 0, downgrade/upgrade 성공. 기존 Starlette 경고 1개 |
| 등록·로그인·패스키·잠금·26개 경로 | `pnpm --filter @sallimbook/client exec playwright test onboarding.spec.ts onboarding-native.spec.ts auth.spec.ts auth-native.spec.ts passkeys.spec.ts routing.spec.ts app-lock-native.spec.ts --workers=2` | **192 통과**, 1.9분, 실패·재시도 없음 |
| 타입·API 계약 | `pnpm typecheck`, `pnpm api:generate`, 생성 파일 diff | 통과, 재생성 차이 0. 기존 모든 path/schema 동일, 신규 경로 6개 |
| 웹 빌드 | HTTPS harness의 `pnpm --filter @sallimbook/client build` | 168 modules, 910.38kB/gzip 234.19kB. 기존 chunk 크기 경고 유지 |
| 정적 검사 | 변경 API/테스트/harness의 기본 Ruff, ops의 `--select E9,F63,F7,F82`, `git diff --check` | 통과 |

서버 시험은 첫 등록 동시성·기존 빈 가계 보존·폐기된 계정이 있을 때 재개방 금지·발급자
권한/CSRF/최근 인증·웹/native 동시 코드 수락·발급 재시도와 전역 추측 제한·세션 생성 중
실패 롤백을 포함한다. 짧은 코드를 기존 긴 초대 경로에 제출해도 거부하고 기존 초대는 유지한다.
실제 HTTPS `--onboarding` 명령은 CI의 격리 브라우저 job에도 추가했다. 원격 CI 실행 성공을
로컬 결과로 대신하지 않는다.

ops에 API의 전체 Ruff 규칙을 확장한 추가 실행은 기존 진단 6개를 보고했다. 기준 `03d5eac`의
같은 두 파일에서도 동일한 FURB188·PLW1510·BLE001 진단을 확인했다. 이번 변경으로 발생한
진단이 아니며 ops 전체 lint 통과로 표시하지 않는다.

Android 전체 JVM 356개와 debug·instrumentation·unsigned release 빌드가 통과했다.
release 전체 DEX의 debug marker 9개 제외와 비공개 onboarding Activity 설정도 확인했다.
네이티브의 인증 경계·세대/시한 검사·설치 실패 롤백·비밀의 JS 비반환은 별도 소스 리뷰에서
구체적인 결함이 발견되지 않았다. 세부 결과와 최초 실패는 [Android 기록](native-onboarding.md)에 있다.

초기 UI 검증은 176개 중 175개 통과, Android 크기의 26개 경로 순회 한 건이 60초 제한에 걸렸다.
같은 시점의 부하가 원인인지는 확인되지 않았다. 이 실행은 전체 성공으로 계산하지 않는다.
마지막 회귀를 포함한 위 통합 192개는 같은 테스트 시간 제한을 유지한 채 모두 통과했다.

저장소 도구의 첫 `pnpm test:docs`는 새 환경변수 검사에서 SQLAlchemy가 없는 문서 전용
Python 환경을 만나 오류 두 건이 발생했다. preflight가 허용되지 않은 환경변수부터 거절하도록
검사 순서를 정리했다. DB URL 파서나 검증 규칙은 완화하지 않았고, 문서 전용 환경에서 68개가
모두 통과했다. 최종 문서 66개·로컬 링크 315개와 manifest 검증도 통과했다.

실제 Galaxy의 입력·잠금·회전·기기 인증과 서명 업데이트 인수는 아직 실행하지 않았다.
일반 CVC 활성화는 false이며 이 변경으로 v1 출시 게이트를 통과했다고 표시하지 않는다.
