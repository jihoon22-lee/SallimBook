# Financial First Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 최초 카드/계좌 입력의 누락과 보관함 UX를 보완하고 웹 CVC의 암호화 동기화를 구현한 뒤 기존 레코드에 이어서 입력한다.

**Architecture:** 일반정보는 가계 범위 API에 저장한다. 비밀은 클라이언트에서 암호화한 버전별 보관함 payload로 저장하며 웹/네이티브가 같은 계약을 사용한다. 기존 메모와 Android 로컬 CVC는 보존한다.

**Tech Stack:** React/TypeScript/Vite, FastAPI/SQLAlchemy/Alembic/PostgreSQL, Capacitor/Kotlin, 기존 WebCrypto/JCA.

**Spec:** `docs/superpowers/specs/2026-10-31-financial-first-import.md`

## Global Constraints

- KRW는 API 십진 문자열, Python Decimal/int이며 float를 사용하지 않는다.
- 미확인과 0원/false를 구분하고 가계 권한·409·감사 이력을 유지한다.
- 비밀은 일반 API/React state/로그/fixture에 넣지 않는다. 합성 자료만 시험한다.
- 기존 서비스와 등록 자료를 보존하고 추가 실데이터 입력은 검증 뒤 재개한다.
- 사용자 요청으로 CVC 로컬 전용 원칙을 변경하며 ADR/보안 문서/생성 client를 함께 수정한다.

## Review Focus

- 구버전 클라이언트가 v2를 v1으로 덮어써 CVC를 잃지 않는가: API 회귀 시험.
- 암호화 직후 연결이 끊기면 동일 암호문/멱등키로 재시도하는가: 웹 보호 작업 시험.
- 키 회전/복구가 CVC까지 보존하는가: TS/Kotlin 공통 벡터 및 회전 비교 시험.
- null/0/false 및 큰 정수가 내보내기까지 유지되는가: API/DB/웹 시험.
- 잠금/실패/취소/이탈 시 일괄 입력 DOM과 mutable bytes가 비워지는가: 웹 lifetime 회귀 시험.

---

### Task 1: 카드 일반정보와 보관함 진입 UX (#180)

**Files:** `services/api/src/sallimbook/cards/{models,schemas,service}.py`, `services/api/migrations/versions/0022_card_terms.py`,
`apps/client/src/features/cards/`, `apps/client/src/features/vault/WebVaultAction.tsx`, API client와 exports 및 관련 tests.

**Interfaces:** nullable `annual_fee_krw`, `is_family_card`; 기존 POST/PATCH/응답 확장, 메모 불변.

- [x] null/0/false·금액 검증·권한/409·메모 보존 및 스크롤/초점 회귀 시험을 먼저 작성하고 실패 확인.
- [x] 모델/마이그레이션/API/client/공통 UI/내보내기 구현.
- [x] `pnpm test:database services/api/tests/test_cards.py -q`, 관련 Playwright 및 typecheck/lint 실행.
- [ ] 문서·독립 리뷰·커밋/PR로 검증 결과 기록.

### Task 2: 공유 CVC 포맷과 호환성

**Files:** `services/api/src/sallimbook/vault/{formats,schemas,models,storage,service}.py`, 새 migration,
`apps/client/src/features/vault/crypto.ts`, Android `NativeVaultCrypto.kt`, `NativeVaultWire.kt`, `NativeVaultActions.kt`,
공통 crypto fixture 생성 스크립트·TS/Kotlin/server tests, ADR/보안/백업 문서.

**Interfaces:** 기존 암호화 envelope의 `payload_schema_version=2`; v1 읽기 유지. v2는 선택 CVC의 길이와 padding을 고정 검증한다.

- [x] 독립 리뷰로 포맷·AAD·구버전 쓰기/회전 정책 확정 후 ADR 작성.
- [x] v1/v2 상호 검증, 잘못된 CVC/길이/AAD/버전·다운그레이드 거부 시험부터 추가.
- [x] 서버 opaque 검증·DB 제약·TS/Kotlin encode/decode/회전 보존을 구현하고 client 재생성.
- [x] 공통 벡터·API/DB·Kotlin 시험, Android 빌드 및 보안 리뷰 수행.

### Task 3: 보호된 웹/Android 입력과 일괄 입력

**Files:** `apps/client/src/features/vault/{WebVaultAction,CardVaultActions,VaultPage,workflow,lifetime,actions}.ts*`,
Android `NativeVaultActivity.kt`, 전용 batch 입력 모듈과 관련 Playwright/네이티브 시험.

**Interfaces:** CVC 포함 보호 입력은 DOM/ref/소유 bytes로만 처리; 일괄 작업 결과는 카드 ID와 상태만 노출.

- [x] CVC 동기화 동의·마스킹·삭제·로컬 값 구분·잠금/취소 시험 작성.
- [x] 입력/표시/수정·삭제를 구현하고 웹/Android 안내를 갱신.
- [x] 일괄 대상 검토·암호화·부분 성공·정확 재시도와 재인증 시 비밀 초기화 구현.
- [x] 합성 자료로 실제 HTTPS·JVM 시험 및 독립 보안 리뷰. 실기기 시험은 사용자 수행 범위로 미실행 명시.

### Task 4: 배포 및 입력 재개

**Files:** 요구사항 추적표·검증 기록·운영 manifest(개인 비밀 없음).

- [ ] 변경별 PR에 요구사항/마이그레이션/보안 영향/실행 명령/미실행 실기기 항목 기록.
- [ ] 운영 백업·전용 스키마/이미지/APK 호환 확인 후 배포 및 실제 화면 인수.
- [ ] 기존 일반정보의 메모를 보존하며 전용 필드를 채우고 중복 건수 확인.
- [ ] 사용자의 보관함 인증으로 기존 카드에 비밀 입력 후 공개 응답에 비밀이 없는지 검증.

### Task 5: 현재 예상 수입과 성과연도 상여 (#182, 입력 재개 전)

- [x] 사용자에게 예상/실제, 성과/지급연도, 주식 평가 기준을 확인.
- [x] 예상 기준과 상여 원본을 분리, typed schema·0024 migration·멱등 revision·현금 원자 연결 구현.
- [x] 웹/Android 입력·전용 내보내기·감사 필드 구현.
- [x] 합성 자료로 권한/0/null/중복·재시도/정정 rollback/주식 분리/실제 지급월 검증.
- [ ] 배포 뒤 기존 카드 중복 없이 보완하고 예상 기준·상여 원본을 등록해 합계 대조.
