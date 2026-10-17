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
Android는 compile/target SDK 36, 앱 Build Tools 36.0.0,
AGP 8.13.0, Gradle 8.14.3(checksum 고정), Kotlin 2.2.20이다.
CLI SDK 설치기는 공식 명령 도구 build 15859902의 SHA-256을 검증하며 기존 SDK 설치를 덮어쓰지 않는다.
설치 대상은 `platforms;android-36`, `build-tools;36.0.0`이다. 버전 없이 갱신되는
`platform-tools`는 설치 대상에서 제외하므로 기존 ADB를 변경하지 않는다.
실기기 연결에 필요한 ADB는 별도로 버전을 선택하며 빌드 설치기가 자동 설치·업데이트하지 않는다.
앱 Gradle dependency lock은 `apps/client/android/app/gradle.lockfile`에 저장한다.
DB와 운영 이미지 버전은 해당 Issue에서 호환 시험 후 별도로 고정한다.

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
SB-001은 기본 화면·프로세스 health·웹/Android 빌드까지 포함하고 PostgreSQL·migration은 SB-002에서 추가한다.
개발 포트는 API 18741, Vite 18742, 웹 E2E 18743이다. 기존 서버를 종료하거나 점유 포트를 빼앗지 않는다.
앱은 정적 웹 자산을 번들하며 `server.url`로 원격 UI를 로드하지 않는다.
Capacitor sync 전에 web production build가 완료되어야 앱에 최신 웹 자산이 포함된다.
Gradle wrapper의 CLI 빌드는 공식 지원 경로다([S18](references.md)).
에뮬레이터 테스트만으로 실제 지문과 하드웨어 보안키 동작을 검증했다고 쓰지 않는다.
기본 Android 모듈에는 업무 단위 테스트가 아직 없어 Gradle test task의 `NO-SOURCE`는 테스트 통과 수로 세지 않는다.

## 6. 환경 구분

- development: 합성 데이터, 제한된 로컬 디버그 origin, debug signing.
- test: 별도 DB·일회용 암호키·격리 첨부, 네트워크 부작용 차단.
- staging: 운영과 같은 HTTPS/인증/서명 흐름, 여전히 합성 데이터.
- production: 두 실계정, 별도 비밀·서명키·백업, debug/원격 WebView 설정 금지.

origin을 지정하지 않은 development·test는 전용 로컬 UI origin 두 개를 사용한다.
staging·production은 기본 허용 origin이 없으며 환경변수 또는 `.env`에 허용 목록을 명시한다.
`.env`에 적힌 로컬 origin도 명시적 설정이므로 운영 환경을 선택할 때 함께 검토한다.

환경 간 실제 건강·금융데이터를 복사하지 않는다. 꼭 필요한 진단은 익명화·축약된 재현 데이터로 대체한다.
