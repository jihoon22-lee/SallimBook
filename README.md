# SallimBook · 살림북

**부부가 함께 관리하는 자산과 생활의 기록. Android 앱을 중심으로, 같은 내용을 PC 웹에서도.**

문서 기준일: **2026-10-17** · 목표 릴리스: **v1.0.0** · 현재 상태: **설계 및 개발 백로그 준비**

> 이 저장소의 초기 패키지는 설계 문서와 GitHub 게시·문서 검증 도구입니다.
> Android 앱, 웹 프론트엔드, API, 운영 DB는 아직 구현되지 않았습니다.
> 문서에 적힌 기술·보안 정책을 이미 동작하는 기능으로 오해하지 마세요.

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

## 기술 스택

| 계층 | 선택 |
|---|---|
| 공통 화면 | React + TypeScript + Vite |
| Android | Capacitor 8 계열 + Kotlin 네이티브 보안 모듈 |
| UI/상태/입력 | Tailwind CSS, shadcn/ui, TanStack Query, React Hook Form, Zod, Recharts |
| API | Python + FastAPI, SQLAlchemy 2, Alembic |
| 데이터 | PostgreSQL, 인증된 비공개 첨부파일 저장소 |
| 운영 | Docker Compose + Caddy + HTTPS |
| 검증 | pytest, Vitest, Playwright, Android 단위·계측·실기기 테스트 |

정확한 패치 버전은 호환성을 검증한 후 lockfile에 고정합니다.
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
| [마일스톤](docs/roadmap-and-milestones.md) | v1 개발 순서와 완료 조건 |
| [전체 문서 안내](docs/README.md) | 나머지 설계·결정·추적표 |

## 지금 실행 가능한 명령

아래는 **문서 패키지 도구**이며 앱 실행 명령이 아닙니다.

```bash
python3 scripts/validate_docs.py
python3 -m unittest discover -s tests -v
python3 scripts/publish_github.py --owner jihoon22-lee --dry-run
```

GitHub에 실제 게시하려면 GitHub CLI가 설치·인증된 환경에서 다음을 실행합니다.
새 저장소는 기본적으로 비공개입니다. 게시기는 다른 프로젝트의 파일을 덮어쓰지 않도록 검사합니다.

```bash
gh auth login
python3 scripts/publish_github.py --owner jihoon22-lee --apply
```

정확한 동작·재실행·권한·실패 처리: [저장소 게시 안내](docs/repository-publishing.md).
로그인 토큰을 문서·채팅·스크립트에 붙여 넣지 않습니다.

## 개발 시작

[SB-001부터 시작하는 백로그](planning/ISSUES.md)를 사용합니다.
먼저 기초 골격과 인증 경계, 실제 Android 보안 모듈의 가능성을 검증한 뒤 기능을 쌓습니다.
실제 개인정보를 테스트 fixture, GitHub Issue, 로그, AI 프롬프트에 입력하지 않습니다.
오픈소스 라이선스는 아직 선택하지 않았으며, 임의의 라이선스를 부여하지 않습니다.
