# SallimBook · 살림북

**부부가 함께 관리하는 자산과 생활의 기록. Android 앱을 중심으로, 같은 내용을 PC 웹에서도.**

문서 기준일: **2026-10-18** · 목표 릴리스: **v1.0.0** · 현재 상태: **전체 기능 통합·운영 검증 진행, 0.x 개발 빌드**

> 자산·계좌·카드·수입·고정 납부·보험·가전/소모품의 수동 입력과 이력, 비공개 문서, 보관함, 사용자 내보내기, 설정·감사 조회를 웹/Android에 연결했습니다.
> 서버 권한·금액·충돌·멱등성, 실제 HTTPS, 브라우저와 네이티브 정책 검증을 수행하고 있습니다. [최종 통합 검증 기록](docs/testing/final-integration.md)과 [요구사항 추적표](docs/requirements-traceability.md)에 근거를 연결합니다.
> 두 Galaxy의 보안·업데이트와 운영 백업/복원·재시작 인수는 남아 있습니다. CVC는 실기기 보안 검증과 사용자 선택 전까지 비활성화하며, v1.0.0 출시로 표시하지 않습니다.

남은 작업은 [v1 잔여 실행 계획](docs/v1-completion-plan.md), 클라우드 검증 작업은
[Android 테스트 전달문](docs/testing/android-cloud-handoff.md)에 정리합니다.

## 무엇을 만드는가

월말에 부부가 자산의 잔액·평가액을 확인하고, 수입과 정기 납부를 정리하며,
카드·계좌·보험·의료 사건·가전·소모품을 서로 연결해 관리합니다.
금융 거래 전체를 수집하는 앱부터 시작하지 않습니다. **필수 관리 영역은 모두 v1에 포함하고, 자동 수집만 뒤로 미룹니다.**

| v1 필수 영역 | 반드시 제공할 내용 |
|---|---|
| 현재 자산 | 부동산·보증금·금융자산·부채, 월별 잔액/평가액, 전월 대비 변화 |
| 월간 수입 | 부부별 급여·상여·부수입, 보험금 수령 별도 구분 |
| 고정 지출 | 대출 원리금, 보험료, OTT·AI 구독, 통신비, 납부 주기·결제수단 |
| 카드 관리 | 카드사·카드명·소유자·번호·유효기간, 등록·수정·종료, 재인증 보관함 |
| 계좌 관리 | 은행·증권·연금저축·IRP·DC·ISA, 계좌번호와 월별 평가액 |
| 보험 관리 | 계약·보장·보험료 및 사건별 진료/약국 트리, 수동 청구·지급·환불 기록 |
| 전자제품·소모품 | 제품·구매·보증 정보, 호환 소모품·재고·입고·교체 이력 |

**홈의 주인공은 월간 자산 변동과 오늘 기준 소모품 상태입니다.**
수입·고정 납부·보험 청구 상태는 보조 정보입니다.

## 확정한 제품 방향

- 부부 **2개 계정**, **1개 공동 가계**. 금융상품 소유자와 로그인 사용자는 다른 개념입니다.
- **Android 앱 우선 + PC 웹 동등한 핵심 기능**. iOS와 별도 데스크톱 앱은 v1 범위 밖입니다.
- 카드 문자/알림 수집, 금융 API, 상세 거래 가져오기, OCR·AI 보험금 산정은 후속입니다.
- 수입·보험금·정기 납부를 기록해도 월별 계좌 스냅샷은 자동 가감하지 않습니다.
- 카드번호·유효기간은 클라이언트 암호화 동기화. **CVC/CVV는 Android 기기 내 직접 입력·암호화 보관만**, 서버·PC 웹·백업·로그에는 포함하지 않습니다.
- 생체인증, 로그인, 보관함 복호화는 서로 구분합니다. 지문 자체를 앱이나 서버가 수집하지 않습니다.

## 처음 사용하기

전용 사설망에 연결한 휴대폰 웹·PC 웹 또는 Android 앱에서 **우리 가계 시작하기**를 선택하고
이름과 비밀번호를 정하면 바로 홈으로 들어갑니다. 첫 사용자의 로그인 이름은 `owner`입니다.
배우자는 설정의 **배우자 연결 코드 만들기**로 받은 8자리 코드와 자신의 이름·비밀번호를
입력해 같은 가계에 연결합니다. 배우자의 로그인 이름은 `partner`입니다.

첫 시작은 배포에서 지정한 사용자에게만, 아직 계정이 없을 때만 열립니다. 운영자가 만든
코드를 PC에서 옮기는 절차는 기본 사용 흐름에서 제외했습니다. [시작·연결 설계](docs/adr/mobile-first-start.md)에
기존 초대 호환성과 보안 경계를 기록합니다. 실제 배포 설정과 실기기 검증 상태는 해당 PR의 근거를 확인합니다.

## 기술 스택

| 계층 | 선택 |
|---|---|
| 공통 화면 | React + TypeScript + Vite |
| Android | Capacitor 8 계열 + Kotlin 네이티브 보안 모듈 |
| UI/상태/입력 | 공통 CSS·React hooks·생성 API 타입, SVG 추이와 접근 가능한 표 |
| API | Python + FastAPI, SQLAlchemy 2, Alembic |
| 데이터 | PostgreSQL, 인증된 비공개 첨부파일 저장소 |
| 운영 | Docker Compose + Caddy + HTTPS |
| 검증 | pytest, Python unittest, Playwright, Kotlin JVM·Android 계측/실기기 인수 |

정확한 패치 버전은 호환성을 검증한 후 lockfile에 고정합니다.
초기 UI 도구 후보와 실제 설치된 구현의 차이는 [클라이언트 구현 결정](docs/adr/client-implementation-and-tests.md)에 기록합니다.
선정 근거와 현재 공식 문서는 [기술·환경 문서](docs/development-environment.md)와 [참고 자료](docs/references.md)에 있습니다.

## 문서 읽는 순서

| 문서 | 내용 |
|---|---|
| [AGENTS.md](AGENTS.md) | 사람과 모든 개발 에이전트에 공통인 작업 지침 |
| [제품 요구사항](docs/product-requirements.md) | v1 범위·비목표·필수 인수 조건 |
| [아키텍처](docs/architecture.md) | 모듈, 배포, 데이터 흐름, 경계 |
| [도메인·계산 규칙](docs/domain-and-calculation-rules.md) | 중복 집계·월별 비교·원리금·보험금·재고 규칙 |
| [DB 모델](docs/data-model.md) | 테이블, 필드, 관계, 제약조건, 트랜잭션 |
| [API 계약](docs/api-contract.md) | 엔드포인트, 인증, 요청·응답, 오류 |
| [화면 명세](docs/screen-specifications.md) | Android/PC 화면과 입력·상태·동작 |
| [보안·인증](docs/security-authentication.md) | 로그인·지문·마스킹·개인정보·위협 대응 |
| [보관함 키 수명주기](docs/vault-key-lifecycle.md) | 부부 공유·기기 등록·복구·폐기 |
| [보험 사건 흐름](docs/insurance-workflows.md) | 진료 트리와 청구·지급 정산 예시 |
| [테스트·인수 기준](docs/testing-and-acceptance.md) | 계산 예제와 보안 실패 테스트 |
| [운영·백업](docs/deployment-backup-operations.md) | 배포, 복구, APK 서명·업데이트 |
| [운영 도구 실행](docs/operations-runbook.md) | 격리 배포 설정, 암호화 백업·복원, 서명 APK 도구 |
| [마일스톤](docs/roadmap-and-milestones.md) | v1 개발 순서와 완료 조건 |
| [전체 문서 안내](docs/README.md) | 나머지 설계·결정·추적표 |

## 개발 실행

Node `24.18.0`, pnpm `9.15.9`, Python `3.14.7`(uv), Android 빌드용 JDK 21을 사용합니다.
WSL에 있는 기존 서버를 유지하며, 아래 명령은 SallimBook 전용 로컬 포트를 사용합니다.

```bash
pnpm install --frozen-lockfile
uv sync --project services/api --frozen
python3 scripts/setup_dev.py  # 최초 한 번; 기존 .env 보존, 개발 비밀번호 자동 생성
pnpm db:up                  # SallimBook 개발 DB만 시작: 127.0.0.1:18744
pnpm db:migrate
pnpm dev:api  # 127.0.0.1:18741, 별도 터미널
pnpm dev      # http://127.0.0.1:18742
```

API 설정은 명령을 실행한 디렉터리의 `.env`를 읽습니다. 위 명령은 저장소 루트에서 실행합니다.
필요하면 `.env.example`을 참고해 `.env`를 만들되 기존 파일은 덮어쓰지 않습니다.
설정 우선순위는 명시적 `Settings` 인자 → 프로세스 환경변수 → `.env` → 기본값입니다.
staging·production의 CORS 허용 origin 기본값은 빈 목록이며, 필요한 origin을 명시적으로 지정합니다.
웹 로그인은 HTTPS와 Secure 쿠키를 사용하므로 위 HTTP 개발 서버의 화면 탐색만으로 인증 동작을 검증하지 않습니다.
실제 인증 검증은 HTTPS에서 진행하며 쿠키 보안 속성을 개발 편의상 낮추지 않습니다.

```bash
pnpm api:generate
pnpm typecheck
pnpm build
pnpm test:api
pnpm test:database  # 일회용 *_test DB: 18745, 시험 후 이 컨테이너만 중지
pnpm --filter @sallimbook/client exec playwright install chromium
pnpm test:web  # 전용 시험 포트 18743, 다른 실행 중인 서버를 재사용하지 않음
uv run --project services/api python scripts/test_web_auth.py  # 실제 HTTPS + 격리 PostgreSQL 인증
```

실제 HTTPS 업무 검증은 같은 명령에 `--passkeys`, `--finance`, `--months`, `--comparison`,
`--cashflow`, `--insurance`, `--homecare`, `--documents`, `--exports`, `--audit`, `--vault`, `--onboarding` 중
하나를 붙여 실행합니다. 각 명령은 합성 계정·일회용 schema를 만들고 종료 시 제거합니다.
`--onboarding`은 빈 가계에서 첫 등록·자동 로그인·배우자 연결을 실제 HTTPS로 검증합니다.
문서·내보내기는 고정 이미지의 파일 검사 도구도 실행합니다. 공유 테스트 DB는 동시 실행을
거부합니다. 브라우저 시험 중 다른 Docker 네트워크를 만들거나 제거하면 Chromium의 네트워크
변경 오류가 발생할 수 있으므로 전체 웹 시험과 컨테이너 시작·종료를 순차로 실행합니다.

Android는 WSL의 SDK와 JDK를 명시적으로 선택합니다.

```bash
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export ANDROID_HOME="$HOME/Android/Sdk"
python3 scripts/setup_android_sdk.py  # 최초 SDK 설치; 라이선스 확인
pnpm android:build
```

SDK 설치기는 고정된 빌드 도구만 설치하며 `platform-tools`와 ADB를 설치·업데이트하지 않습니다.
실기기 연결용 ADB는 기존 환경을 유지하고 별도로 버전을 선택합니다.

산출물은 `apps/client/android/app/build/outputs/apk/debug/app-debug.apk`이며 개발용입니다.
최소 API 30, 개발 앱 ID `io.github.jihoon22lee.sallimbook.debug`입니다.
운영 앱 ID는 접미사가 없는 `io.github.jihoon22lee.sallimbook`이며 정식 서명·배포는 SB-038에서 검증합니다.

Android 인증 서버 주소는 빌드 시 Gradle 속성 `sallimbookApiOrigin`으로 지정한 HTTPS origin만 사용합니다.
`ORG_GRADLE_PROJECT_sallimbookApiOrigin` 환경변수로 주입할 수 있으며 경로·쿼리·사용자정보가 없는 주소여야 합니다.
미설정 빌드는 인증을 비활성화합니다. 운영 주소는 별도 Tailscale 노드를 마련한 뒤 확정합니다.
앱의 로그인·초대 입력과 인증 토큰은 네이티브 모듈에서 처리하고 일반 웹 상태에 반환하지 않습니다.
안전한 메시지 채널을 지원하지 않는 WebView에서는 업데이트 안내를 표시합니다.
두 Galaxy의 실기기·백업/전송·잠금 실패 시나리오는 전체 기능 개발 뒤에 수행합니다.
Android 앱 잠금은 프로세스 시작·화면 잠금·수동 잠금 및 외부 백그라운드 1분 후 적용합니다.
네이티브 기기 인증 또는 현재 계정의 서버 비밀번호 재인증으로 다시 열며, 카드 보관함 인증과 구분합니다.
구현 경계와 실기기 미검증 항목은 [앱 잠금 정책](docs/security-authentication.md#앱-잠금)을 참고합니다.

자세한 환경·검증 범위는 [개발 환경](docs/development-environment.md)을 참고합니다.
[실제 브라우저 인증 검사](docs/testing/browser-authentication.md)는 임시 HTTPS 인증서와 합성 계정을 사용합니다.
`pnpm db:stop`은 SallimBook 개발 DB만 중지하며 데이터 볼륨은 유지합니다.
DB 시험은 개별 격리 schema에 실제 migration을 적용합니다. `pnpm test:api`만 실행하여
DB 환경이 없을 때 표시되는 skip을 DB 검증 통과로 간주하지 않습니다.

## 문서 도구 명령

아래는 **문서 패키지 도구**이며 앱 실행 명령이 아닙니다.

```bash
python3 scripts/validate_docs.py
python3 -m unittest discover -s tests -v
python3 scripts/publish_github.py --owner jihoon22-lee --dry-run
```

현재 원격에는 작업 그룹 Issue #1~#9와 구현 Issue #10~#49가 있습니다.
최초 게시기의 식별 marker와 다른 형식이므로 이 저장소에 `--apply`를 재실행하지 않습니다.
기능 개발은 기존 Issue와 Git 브랜치·PR 흐름으로 진행합니다.

정확한 동작·재실행·권한·실패 처리: [저장소 게시 안내](docs/repository-publishing.md).
로그인 토큰을 문서·채팅·스크립트에 붙여 넣지 않습니다.

## 개발 시작

[SB-001부터 시작하는 백로그](planning/ISSUES.md)를 사용합니다.
먼저 기초 골격과 인증 경계, 실제 Android 보안 모듈의 가능성을 검증한 뒤 기능을 쌓습니다.
운영은 사용자가 지정한 현재 PC의 WSL에서 별도 Compose 프로젝트·볼륨·전용 Tailscale 노드로 격리합니다.
기존 서버와 호스트 Tailscale 설정을 수정하지 않습니다. [승인된 운영 결정](docs/adr/private-network-and-app-identity.md)을 따릅니다.
실제 개인정보를 테스트 fixture, GitHub Issue, 로그, AI 프롬프트에 입력하지 않습니다.
오픈소스 라이선스는 아직 선택하지 않았으며, 임의의 라이선스를 부여하지 않습니다.
