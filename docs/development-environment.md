# 개발 환경·기술 스택

## 1. 기본 원칙

기존 **WSL 기반 개발 흐름**을 유지한다. Ubuntu 배포판 버전은 실제 개발 환경을 확인해 기록한다.
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
Android 최소 지원은 API 30 제안이며 실제 두 기기 확인 뒤 최종 결정한다.
서명하기 전 applicationId는 예시가 아닌 실제 배포값으로 확정한다. 후보 `io.github.jihoon22lee.sallimbook`은 아직 확정이 아니다.

## 4. 저장소와 실행 환경

WSL의 Linux 파일시스템에 clone을 두고 프로젝트별 의존성을 관리한다.
운영 DB/첨부/서명키는 저장소 밖의 명시적 경로에 보관한다.
개발 .env.example에는 변수 이름과 무해한 예시만 넣고 실제 비밀은 로컬 환경으로 주입한다.
Windows와 WSL에서 같은 node_modules/Gradle 캐시를 공유하지 않는다.
Windows의 별도 checkout이 필요하면 Git으로 동기화하고 생성 파일/빌드 폴더를 무작정 복사하지 않는다.

## 5. 목표 개발 흐름

기초 코드가 만들어진 뒤 검증된 명령을 README에 추가한다.
목표 흐름은 의존성 설치 → PostgreSQL 개발 인스턴스 → migration → API → Vite → Android bundle sync → 테스트/빌드다.
Capacitor sync 전에 web production build가 완료되어야 앱에 최신 웹 자산이 포함된다.
Gradle wrapper의 CLI 빌드는 공식 지원 경로다([S18](references.md)).
에뮬레이터 테스트만으로 실제 지문과 하드웨어 보안키 동작을 검증했다고 쓰지 않는다.

## 6. 환경 구분

- development: 합성 데이터, 제한된 로컬 디버그 origin, debug signing.
- test: 별도 DB·일회용 암호키·격리 첨부, 네트워크 부작용 차단.
- staging: 운영과 같은 HTTPS/인증/서명 흐름, 여전히 합성 데이터.
- production: 두 실계정, 별도 비밀·서명키·백업, debug/원격 WebView 설정 금지.

환경 간 실제 건강·금융데이터를 복사하지 않는다. 꼭 필요한 진단은 익명화·축약된 재현 데이터로 대체한다.
