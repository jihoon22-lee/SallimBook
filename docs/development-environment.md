# 개발 환경·기술 스택

## 1. 기본 원칙

기존 **WSL 기반 개발 흐름**을 유지한다. 확인 환경은 WSL2 Ubuntu 26.04.1 LTS다.
React/API/DB/CLI 빌드와 일반 테스트는 WSL에서 수행할 수 있게 설계한다.
Android UI 디버깅과 실기기 연결은 Windows Android Studio/ADB 또는 실제 연결 가능한 WSL 경로를 사용한다.
작업 지시 도구는 특정 AI 제품에 종속되지 않는다.

## 2. 선정 스택

| 범위 | 선택 | 결정 이유 |
|---|---|---|
| UI | React + TypeScript + Vite | Android/PC UI와 업무 로직 공유 |
| 모바일 | Capacitor 8.x | 공통 UI에 네이티브 보안 기능 연결 |
| 네이티브 | Kotlin, AndroidX Biometric, Keystore, Credential Manager | 시스템 인증과 암호키 접근 분리/결합 |
| UI 도구 | Tailwind CSS, shadcn/ui | 반응형 폼·표·다이얼로그 |
| 서버 상태 | TanStack Query | 조회·갱신·메모리 캐시 |
| 입력 | React Hook Form, Zod | 일관된 입력 처리, 서버 검증과 계약 대조 |
| 차트 | Recharts | 자산 추이, 접근 가능한 표 병행 |
| API | FastAPI, SQLAlchemy 2, Alembic | 관계형 도메인과 버전 있는 DB |
| DB | PostgreSQL | 정확한 금액·관계·트랜잭션 |
| 패키지 도구 | pnpm, uv 제안 | JS/Python lockfile와 반복 가능한 설치 |
| 배포 | Docker Compose + Caddy | 개인용 상시 서버의 단일 운영 구성 |

프레임워크 이름은 확정 방향, 패치 버전은 구현 검증 후 고정이다.
Capacitor 8 공식 자료는 Node 22 이상과 Android Studio 2025.2.1 이상을 안내하며,
8.0 이행 예시에는 compile/target SDK 36이 제시되어 있다([S01, S02](references.md)).
이를 '작성일 현재 모든 구성요소의 최신 버전'이라고 확대 해석하지 않는다.

## 3. 버전 확정 절차

SB-001에서 실제 도구 버전을 조사하고 다음을 저장한다.
Node·pnpm·Python·uv·JDK·Android SDK/Build Tools·Gradle·AGP·Kotlin·Capacitor·PostgreSQL·Docker 버전.
`packageManager`, lockfile, Python lock, Gradle wrapper와 dependency lock을 통해 반복 가능하게 한다.
JDK는 선택한 Gradle/AGP 요구와 일치시킨다. 임의의 시스템 java에 의존하지 않는다.
Android 최소 지원은 사용자 승인에 따라 API 30이다.
운영 applicationId는 `io.github.jihoon22lee.sallimbook`, 개발 빌드는 `.debug` 접미사로 분리한다.
실기기는 Galaxy S25 Ultra(OS 미확인), Galaxy S24 Ultra(Android 16)이며 연결·실기기 검증은 아직 수행하지 않았다.

### SB-001 도구 고정

Node 24.18.0, pnpm 9.15.9, 프로젝트 Python 3.14.7, uv 0.12.5, JDK 21을 사용한다.
시스템 Python 3.14.4와 프로젝트 uv Python은 별개다. `.python-version`은 프로젝트 버전을 고정한다.
React 19.3.1, Vite 8.3.4, TypeScript 5.9.3, Capacitor 8.5.3,
FastAPI 0.143.3을 lockfile에 고정했다. OpenAPI 생성기의 TypeScript 5 peer 범위를 따른다.
Capacitor CLI의 `xcode@3.0.1` 하위 UUID는 CommonJS 지원 수정판 `uuid@11.1.1`로 좁게 고정한다.
[버퍼 경계 검증 공지](https://github.com/uuidjs/uuid/security/advisories/GHSA-w5hq-g745-h8pq)를 반영했으며
Xcode 도구의 UUID 생성과 Android sync 호환, `pnpm audit`를 확인한다. 앱에서 해당 UUID API로 비밀을 생성하지 않는다.
Android는 compile/target SDK 36, 앱 Build Tools 36.0.0,
AGP 8.13.0, Gradle 8.14.3(checksum 고정), Kotlin 2.2.20이다.
CLI SDK 설치기는 공식 명령 도구 build 15859902의 SHA-256을 검증하며 기존 SDK 설치를 덮어쓰지 않는다.
설치 대상은 `platforms;android-36`, `build-tools;36.0.0`이다. 버전 없이 갱신되는
`platform-tools`는 설치 대상에서 제외하므로 기존 ADB를 변경하지 않는다.
실기기 연결에 필요한 ADB는 별도로 버전을 선택하며 빌드 설치기가 자동 설치·업데이트하지 않는다.
앱 Gradle dependency lock은 `apps/client/android/app/gradle.lockfile`에 저장한다.
SB-005의 native 계정 인증 HTTP는 OkHttp 5.4.0으로 고정한다. [공식 변경 기록](https://raw.githubusercontent.com/lysine-dev/okhttp/master/CHANGELOG.md)과
배포 AAR 메타데이터를 확인했다. 5.5.0은 compileSdk 37을 요구하여 현재 SDK 36 빌드에 사용할 수 없었고,
5.4.0의 minCompileSdk 36을 선택했다. JVM/Android 호환 검증은 실제 Gradle 빌드와 단위 테스트로 수행한다.
SB-002에서 SQLAlchemy 2.1.5, Alembic 1.20.0, psycopg 3.3.6을 추가했다.
SB-006 서버 패스키 검증은 `webauthn==3.0.1`로 고정했다. [공식 배포 메타데이터](https://pypi.org/project/webauthn/3.0.1/)의
Python 3.10 이상 요구를 확인하고, 프로젝트 Python 3.14.7에서 합성 ES256 서명과 PostgreSQL 통합 시험을 실행했다.
검증 구현은 [Duo Labs 공식 소스](https://github.com/duo-labs/py_webauthn)를 기준으로 하며 전이 의존성도 `services/api/uv.lock`에 고정한다.
이 시험은 서버 호환 검증이며 PC WebAuthn UI·Android Credential Manager·실기기 보안 검증을 대신하지 않는다.
개발 PostgreSQL 18.6-bookworm 이미지는 Compose에서 digest까지 고정한다.
운영 이미지 버전은 해당 Issue에서 호환 시험 후 별도로 고정한다.

버전 선택 근거: [Vite 환경](https://vite.dev/guide/),
[Capacitor 8 Android 환경](https://capacitorjs.com/docs/updating/8-0),
[FastAPI 변경 기록](https://fastapi.tiangolo.com/release-notes/),
[Android 공식 SDK·체크섬](https://developer.android.com/studio#command-tools).

## 4. 저장소와 실행 환경

WSL의 Linux 파일시스템에 clone을 두고 프로젝트별 의존성을 관리한다.
운영 DB/첨부/서명키는 저장소 밖의 명시적 경로에 보관한다.
개발 .env.example에는 변수 이름과 무해한 예시만 넣고 실제 비밀은 로컬 환경으로 주입한다.
API `Settings`는 현재 작업 디렉터리의 `.env`를 UTF-8로 읽으며 상위 디렉터리를 검색하지 않는다.
README의 명령은 저장소 루트에서 실행하므로 루트 `.env`가 적용된다.
설정 우선순위는 명시적 `Settings` 인자 → 프로세스 환경변수 → `.env` → 기본값이다.
격리 테스트는 `_env_file=None`으로 로컬 `.env` 로딩을 끌 수 있다.
Windows와 WSL에서 같은 node_modules/Gradle 캐시를 공유하지 않는다.
Windows의 별도 checkout이 필요하면 Git으로 동기화하고 생성 파일/빌드 폴더를 무작정 복사하지 않는다.

## 5. 목표 개발 흐름

현재 실행 명령은 [README](../README.md#개발-실행)에 있다.
SB-001은 기본 화면·프로세스 health·웹/Android 빌드, SB-002는 PostgreSQL·migration·공통 계약을 포함한다.
개발 포트는 API 18741, Vite 18742, 웹 E2E 18743, 개발 DB 18744, 일회용 시험 DB 18745다.
시험 DB는 데이터·WAL을 tmpfs에 두므로 확장된 migration/이력 회귀의 메모리 사용을 포함해 한도를 1 GiB로 둔다. 개발 DB 한도는 384 MiB로 유지한다.
기존 서버를 종료하거나 점유 포트를 빼앗지 않는다.
`scripts/setup_dev.py`는 기존 `.env`를 덮어쓰지 않고 새 파일에만 난수 개발 비밀번호를 저장한다(mode 0600).
`pnpm db:up`과 `db:stop`은 Compose 프로젝트 `sallimbook-dev`의 `db` 서비스만 제어한다.
개발 DB 포트는 loopback에만 바인딩한다. 내부 전용 bridge는 host 포트를 게시하지 않으므로
별도 개발용 `local_access` bridge도 연결한다. 운영 DB의 네트워크 설계와 구분한다.
`pnpm test:database`는 tmpfs의 `sallimbook_test`만 사용하고 마지막에 시험 서비스만 중지한다.
각 DB 시험은 `sallimbook_test_<UUID>` schema를 생성·migration·폐기하며 다른 schema를 지우지 않는다.
테스트 DB 이름이 `_test`로 끝나지 않으면 시험을 거부한다. 운영 DB로 시험하지 않는다.
앱은 정적 웹 자산을 번들하며 `server.url`로 원격 UI를 로드하지 않는다.
Capacitor sync 전에 web production build가 완료되어야 앱에 최신 웹 자산이 포함된다.
Gradle wrapper의 CLI 빌드는 공식 지원 경로다([S18](references.md)).
에뮬레이터 테스트만으로 실제 지문과 하드웨어 보안키 동작을 검증했다고 쓰지 않는다.
Android 계정 인증 정책에는 JVM 단위 테스트가 있다. bridge 계측·Keystore·생체인증은 별도 환경이 필요하며,
Gradle task의 `NO-SOURCE`나 계측 APK 컴파일을 해당 동작 테스트 통과로 세지 않는다.

## 6. 환경 구분

- development: 합성 데이터, 제한된 로컬 디버그 origin, debug signing.
- test: 별도 DB·일회용 암호키·격리 첨부, 네트워크 부작용 차단.
- staging: 운영과 같은 HTTPS/인증/서명 흐름, 여전히 합성 데이터.
- production: 두 실계정, 별도 비밀·서명키·백업, debug/원격 WebView 설정 금지.

origin을 지정하지 않은 development·test는 전용 로컬 UI origin 두 개를 사용한다.
staging·production은 기본 허용 origin이 없으며 환경변수 또는 `.env`에 허용 목록을 명시한다.
`.env`에 적힌 로컬 origin도 명시적 설정이므로 운영 환경을 선택할 때 함께 검토한다.

### 패스키 설정

`.env.example`은 다음 세 변수를 빈 값/빈 목록으로 둔다. 이 상태에서는 패스키 ceremony가 비활성화된다.

| 설정 | 운영 연결 시 입력할 값 |
|---|---|
| `SALLIMBOOK_WEBAUTHN_RP_ID` | 실제 소유·배포할 RP 호스트명. URL·포트·경로 제외 |
| `SALLIMBOOK_WEBAUTHN_WEB_ORIGINS` | 같은 RP 호스트의 정확한 HTTPS origin을 담은 JSON 배열. 필요한 포트까지 일치 |
| `SALLIMBOOK_WEBAUTHN_NATIVE_ORIGINS` | 실제 인증서 SHA-256의 패딩 없는 base64url을 사용한 `android:apk-key-hash:…` JSON 배열 |

웹 origin은 `SALLIMBOOK_ALLOWED_ORIGINS`에도 명시한다. Vite의 HTTP localhost 개발 origin은 패스키 origin으로
사용할 수 없다. 테스트의 합성 도메인·인증서는 운영 설정으로 복사하지 않는다.
native는 [Android Digital Asset Links 절차](https://developer.android.com/identity/credential-manager/prerequisites)에 따라
실제 RP 도메인에 `/.well-known/assetlinks.json`을 배포하고 applicationId와 실제 서명 인증서를 연결해야 한다.
DAL의 `sha256_cert_fingerprints`와 서버 native origin의 base64url 해시 표현을 구분한다.
웹 WebAuthn UI와 Android Credential Manager UI를 서버 검증에 연결했다. 실제 도메인·운영 서명 인증서·
DAL 배포·실기기 인증은 아직 미완료다. [웹 검증 기록](testing/passkeys-web.md)의 가상 인증기 결과를
Android 실기기 검증으로 해석하지 않는다.

Android 빌드에는 다음 Gradle 속성을 별도로 지정한다. 기본값은 모두 비어 있으며 임의의 운영 호스트나
개발 인증서 지문을 자동 채우지 않는다. 환경변수로 지정할 때는 `ORG_GRADLE_PROJECT_` 접두사를 쓴다.

| Gradle 속성 | 내용 |
|---|---|
| `sallimbookApiOrigin` | 네이티브 API의 고정 HTTPS origin |
| `sallimbookPasskeyRpId` | 실제 RP 호스트명. API 호스트는 이 RP 또는 그 하위 도메인이어야 함 |
| `sallimbookPasskeyCertSha256` | 실제 APK 서명 인증서 SHA-256 64자리 hex. 콜론과 대소문자는 정규화 |

실행 시 실제 APK 서명 인증서가 지정 지문과 일치하는지 확인한다. RP·인증서가 미지정이거나 잘못되면
패스키를 사용할 수 없으며 다른 인증으로 성공 처리하지 않는다. APK의 `asset_statements`는 지정 RP의
`/.well-known/assetlinks.json`을 참조한다. 서버 native origin과 DAL에는 배포할 debug/release applicationId와
실제 서명 인증서를 각각 정확히 연결한다. 지문 확인은 DAL의 실제 배포 검증을 대신하지 않는다.

Android 의존성은 `androidx.credentials:credentials`와 `credentials-play-services-auth` **1.6.0**으로 고정했다.
[공식 릴리스](https://developer.android.com/jetpack/androidx/releases/credentials)와 AAR 요구 SDK를 확인한 뒤
현재 SDK 36·AGP 8.13.0·JDK 21에서 debug 빌드, release Kotlin 컴파일, JVM 정책 검사로 호환성을 확인했다.
비밀번호·패스키·초대 UI 및 토큰은 네이티브에 남기며 JS에는 완료·취소 상태와 공개 메타데이터만 반환한다.
구체적인 메서드는 [계정 인증 bridge 계약](native-bridge-contract.md#7-계정-인증-bridge-sb-005006)을 따른다.

서버 검증 명령은 `uv run --project services/api --frozen python scripts/test_database.py`다.
전체 테스트와 Alembic 차이 검사·`downgrade base`/`upgrade head`를 전용 시험 DB에서 실행한다.
API 변경 후 `pnpm api:generate`와 `pnpm typecheck`로 OpenAPI·TS 계약을 갱신하고 확인한다.

환경 간 실제 건강·금융데이터를 복사하지 않는다. 꼭 필요한 진단은 익명화·축약된 재현 데이터로 대체한다.

### 자산·계좌 화면 검증

자산 목록·등록·상세·수정·사용 종료와 계좌 목록·등록·상세·수정·사용 종료를 실제 생성 API client에 연결했다.
기본정보 목록은 아직 조회하지 않은 금액을 0원으로 채우지 않는다. 웹 월 입력·확정·정정은 별도 월 기록 화면에서 제공한다. 월간 비교·추이와 홈 요약은 확정 월 기록을 조회한다.
계좌는 하나의 금융 자산과 연결하고 평가액을 중복 합산하지 않는다.

`pnpm --filter @sallimbook/client exec playwright test --config playwright.finance.config.ts`는 별도
loopback 18748 포트에서 UI 회귀를 실행한다. `uv run --project services/api python scripts/test_web_auth.py --finance`는
전용 DB 18745의 임시 schema, 임시 HTTPS 인증서·서버 필드 암호키, 실제 가상 WebAuthn 인증기를 사용한다.
전역 DB 시험 잠금을 획득하며 다른 체크아웃이 사용 중이면 서비스 변경 없이 종료한다.
키 파일과 비공개 브라우저 산출물은 mode 0700 임시 디렉터리에 만들고 종료 시 삭제한다.
기존 서버·신뢰 저장소·운영 RP·서명키를 변경하지 않는다.

구현 범위와 검증 결과는 [자산·계좌 UI 검증 기록](testing/assets-accounts-client.md)을 따른다.
Android 번호 입력·표시 실기기 시험은 빌드/JVM/브라우저 bridge 모의시험과 구분한다.

### 웹 월 기록 입력 검증

`/assets/months/:month`는 실제 월 작성본·전월 복사·행 확인·명시 범위 반영·확정·정정에 연결된다.
`?revision=N`으로 당시 범위와 금액을 읽기 전용 조회한다. 전월 미확인은 0원이 아니고, 확정 전 날짜와 비교 범위를 확인한다.
`pnpm --filter @sallimbook/client exec playwright test --config playwright.months.config.ts`는 18749 포트를 사용한다.
`uv run --project services/api python scripts/test_web_auth.py --months`는 실제 HTTPS·일회용 DB의 월 전체 흐름을 검증한다.
[월 입력 검증 기록](testing/monthly-assets-client.md)에 재현 명령과 구현/검증 경계를 기록한다.
Android 월 adapter는 같은 생성 계약과 네이티브 인증에 연결되며 잠금 중 요청·응답을 차단한다.
### 반복 규칙 DB 확장

`0009_recurring`의 기간 배타 제약은 고정 PostgreSQL 이미지의 btree_gist 1.8을 사용한다. 마이그레이션 역할에 대상 DB의 CREATE 권한이 필요하고 런타임 API 역할에는 확장 설치 권한을 주지 않는다. public의 기존 확장 버전/위치가 다르면 자동 이동·업그레이드하지 않고 마이그레이션을 중단한다. [PostgreSQL btree_gist 문서](https://www.postgresql.org/docs/18/btree-gist.html), [CREATE EXTENSION 문서](https://www.postgresql.org/docs/18/sql-createextension.html)를 확인했다.

SB-018 결제수단 연결 조회·종료 확인은 새 migration 없이 `0009_recurring` 위에 연결했다.
`test_payment_links.py`42개, 카드30개, 자산61개, 고정비69개, 계좌68개가 현재 코드에서 통과했다
(총270개, 종료 확인이 필요한 기존 fixture 수정 후 분리 재검증 포함). Alembic drift 없음과
downgrade/upgrade 왕복도 확인했다. 기존 서버·데이터는 변경하지 않고 일회용 시험 DB만 사용했다.

### 수입·고정 납부·카드 화면 검증

웹과 Android adapter를 수입·반복 규칙·예정 회차·실제 납부·카드 일반정보에 연결했다.
카드·계좌·연결 자산 종료에는 선택 종료일 기준 연결 전체 조회와 명시 확인을 사용한다.
`pnpm --filter @sallimbook/client exec playwright test --config playwright.cashflow.config.ts`는
18751 포트에서 UI/bridge 모의시험을 실행한다. 실제 HTTPS 흐름은
`uv run --project services/api python scripts/test_web_auth.py --cashflow`로 실행한다.
구체적인 금액·이력·종료 검증과 실행 한계는 [생활비 UI 검증 기록](testing/cashflow-client.md)을 따른다.

### 병렬 검증 자원

같은 WSL에서 UI 브라우저 검사를 실행하는 동안 Docker 시험 컨테이너의 생성·시작·중지를 병행하지 않는다. 네트워크 인터페이스 변경이 Chromium의 모듈 요청에 `ERR_NETWORK_CHANGED`를 일으킬 수 있어 순서를 조정한다. 별도 UI 포트는 config 하나의 webServer로 지정한다. `/tmp`가 메모리 기반이고 공간이 부족하면 재생성 가능한 이전 빌드 캐시를 정리하거나 TMPDIR를 충분한 로컬 저장소로 지정한다. 소스·사용자 파일·기존 서비스는 정리 대상이 아니다.

SB-019/SB-020 보험 서버의 합성 계약·암호화20개, API/권한/동시성23개, DB 보존4개 총47개가 통과했다.
최초 실행의 fixture3건(종료 상태·적용일·기존400계약)을 수정한 뒤 47개 전체와 Alembic drift/왕복을 다시 통과했다.
실제 잠금 대기 중 인증 만료, 기기 철회, 복호화/감사 후 만료, 다른 가계 참조와 깊은 진료 트리를 포함한다.
이 서버 검사와 별도로 웹/Android 보험 화면을 연결했다. 운영 키·실기기 검증은 미완료다.

### 보험 화면 검증

`pnpm --filter @sallimbook/client exec playwright test --config playwright.insurance.config.ts`는
18753 포트에서 보험과 기존 UI 회귀를 실행한다. `uv run --project services/api python scripts/test_web_auth.py --insurance`는
전용 일회용 DB·개인 임시 키링·임시 HTTPS 인증서로 실제 계약/사건/비용/청구/수령/반환을 검사한다.
키링은 증권번호 서버 필드 보호 시험에만 사용하며 기존 키나 신뢰 저장소를 바꾸지 않는다.
구체적인 범위와 결과는 [보험 UI 검증 기록](testing/insurance-client.md)을 따른다.

SB-021/SB-022의 보험 검증은 108개 통과했다(API/계산38, 이벤트 직접 DB 제약19, 기존 보험 API27·계약/암호화20·보존4). 실제 PostgreSQL에서 T-12~T-19/T-22, 금전 정정 중 실패의 전체 rollback, 동시 반환 한도, 멱등 재전송, 현재 청구 근거 정정과 과거 이력, 다른 가계/사건 차단, 읽기 전용 소득 투영과 스냅샷 불변을 확인했다. `uv run --project services/api python scripts/test_database.py services/api/tests/test_insurance_events.py services/api/tests/test_insurance_event_storage.py services/api/tests/test_insurance_core.py services/api/tests/test_insurance_contract.py services/api/tests/test_insurance_storage.py -q` 및 Alembic drift/왕복을 통과했고 전용 DB를 정지했다. 생성 API client·타입·전체 Ruff·문서 검사도 통과했다. 보험 화면은 별도 client 검증을 따르며 실기기 검증은 남아 있다.
