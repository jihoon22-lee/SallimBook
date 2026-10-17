# 설정·감사 이력 화면 검증

대상: SB-034, SB-040의 UI-26 보완, R-02·R-19·R-20.
[화면 명세](../screen-specifications.md)의 설정 요구와
[감사 API 계약](../api-contract.md#sb-037-사용자-내보내기감사-조회-구현-계약-r20)을 연결한다.

## 설정과 26개 경로

`/settings`는 준비 상태 화면에서 실제 링크 허브로 바뀐다. 계정·기기·패스키·구성원 초대,
보관함, 자료 내보내기, 감사 이력을 기존 기능에 연결한다. 현재 가계 구성원은 인증된
`GET /household/members` 결과를 표시한다. Android 잠금은 기존 네이티브 `lockApp`을 사용하고
웹에서는 보호 화면 종료와 계정 로그아웃을 구분해서 안내한다.

버전은 package.json의 **웹 클라이언트 버전**이다. 이를 Android versionCode나 서명된
배포 APK의 버전이라고 표시하지 않는다.

기존 26개 경로 중 준비 상태 컴포넌트가 실제로 남아 있던 경로는 설정뿐이었다.
UI-01~02 인증, UI-03 홈, UI-04~09 자산·계좌, UI-10~15 수입·납부·카드,
UI-16 보관함, UI-17~21 보험, UI-22~25 가전·재고는 각 feature 화면에 이미 연결되어 있었다.
설정 전환 뒤 준비 상태 경로 조립을 제거했다. 26개 direct-entry/reload 시험에서 준비 상태
안내가 없고 비로그인 시 업무 데이터를 만들지 않는지를 확인한다. 미지원 네이티브 인증의
접근 차단 안내와 실제 요청 준비 상태는 기능 누락을 뜻하는 placeholder와 구분한다.
이 경로 조사는 각 도메인의 모든 인수 기준이나 Galaxy 실기기 보안 시험 완료를 뜻하지 않는다.

## 감사 목록

`/settings/audit`는 생성 TS client의 `listAuditEvents`와 `AuditListResponse`를 사용한다.
새 API·상세 조회·DDL·클라이언트 재계산 계약을 추가하지 않는다.

- 대상 종류/ID, 작업 종류, 가계 구성원, 날짜 범위를 적용한다. 날짜는 서울 기준이며 선택한
  마지막 날짜를 포함하도록 서버의 `[since, until)` 범위로 바꾼다. 조건 변경은 cursor를 지운다.
- 기본 50개를 읽고 서버 cursor로 다음 페이지를 요청한다. 중복 ID는 하나만 표시하며
  여러 페이지가 동일 DB snapshot이라는 주장은 하지 않는다. 새로고침은 첫 페이지에서 시작한다.
- 행에는 작업자, 시각, 대상·작업 종류, 전후 버전, 변경 필드 **이름**만 표시한다.
  펼침 영역의 ID와 request ID도 이미 받은 행의 메타데이터다. 원본 safe_diff·전후 값은 렌더하지 않는다.
- 삭제된 대상의 이력도 표시하며 존재 여부를 임의로 현재 엔티티 API에서 다시 확인하지 않는다.
  `user_export/export`는 서버 파일 발급이며 기기 저장 성공이 아님을 설명한다.
- 오류·권한 거절 뒤에는 이전 목록을 숨기고 명시적 새로고침을 제공한다. 401·잠금은 기존 인증
  계층에서 처리하고 늦은 이전 조건 응답은 현재 목록에 반영하지 않는다.
- 조건/결과를 페이지 주소의 query, localStorage, sessionStorage, Cache API에 저장하지 않는다.

Android는 생성 query/응답 타입을 참조하는 `nativeAudit.list({query})` 경계로만 호출한다.
네이티브가 bearer·고정 경로·메타데이터 투영을 담당한다. 기능 미지원·실패에 웹 HTTP로
우회하지 않는다. 앱 잠금과 실제 기기 결과는 [Android 담당 검증 기록](native-audit.md)과 구분한다.

## 검증 명령과 결과

```bash
pnpm typecheck
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts tests/settings-audit.spec.ts tests/settings-audit-native.spec.ts tests/routing.spec.ts --workers=1
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts tests/settings-audit.spec.ts tests/settings-audit-native.spec.ts --workers=1
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts tests/settings-audit-native.spec.ts --workers=1
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts tests/settings-audit.spec.ts --grep "settings long" --workers=1
pnpm build
uv run --project services/api ruff check scripts/test_web_auth.py
uv run --project services/api python scripts/test_web_auth.py --audit
python3 scripts/validate_docs.py
git diff --check
```

타입 검사와 Ruff, 배포용 빌드가 통과했다(165 modules, JS 894.13kB/gzip 231.15kB).
기존 500kB chunk 경고는 남는다. 전용 18756 포트에서 기존 경로 시험 16개가 통과했다.
첫 실행의 신규 시험 12개 실패는 select의 암시적 label 범위와 개발 StrictMode의 2회 초기 읽기를
고려하지 않은 assertion이었다. 필터를 명시적인 label/id로 연결하고 초기 읽기 횟수 대신
조건·cursor 및 추가 요청 여부를 검증하도록 수정했다. 신규 40개 전체 재실행이 통과했다(34.4초).
네이티브 미지원 안내를 추가하고 잠금·만료 상태 대기를 강화한 뒤 native 14개도 통과했다(18.8초).
설정의 긴 구성원 이름을 320px·200% 글꼴에서 확인한 추가 2개도 통과했다(3.8초).
따라서 신규 고유 44개(웹 30·native UI 14)와 기존 경로 16개가 검증됐다.

최신 통합 코드 `ba4d0ac`의 실제 HTTPS 시험도 통과했다. HTTP route mock 없이 실제 API와
PostgreSQL에 합성 가전 51개와 정정 1건을 기록하고 다음을 검증했다.

- 52개 감사 기록을 첫 50개와 추가 2개로 조회하며 cursor를 사용한다.
- 작업 구성원·대상 ID·종류·작업 필터로 정정 1건을 찾고 변경 필드 이름과 버전 1→2를 표시한다.
- 변경 전후 원문 값·safe_diff는 응답/화면에 없으며 다른 가계의 대상도 포함하지 않는다.
  다른 가계 구성원 ID로 강제 조회하면 404이며 기록 목록을 받지 못한다.
- 5분 최근 인증이 지난 뒤에도 현재 유효한 세션의 메타데이터 조회는 허용한다.
  서버에서 로그아웃한 뒤 다시 읽으면 401로 목록을 닫고 로그인 안내로 전환한다.
- 감사 요청은 모두 GET이며 no-store 응답을 확인했다. localStorage/sessionStorage/Cache API는 비어 있다.

합성 가계·일회용 schema·임시 TLS만 사용하며 실제 사용자 자료를 읽지 않았다. 시험 후 schema,
private fixture와 브라우저 산출물은 제거했고 전용 db-test를 중지하여 공유 검증 큐를 반환했다.
실제 Android 기기/SAF/생체인증과 TalkBack은 이 HTTPS 브라우저 시험의 범위가 아니다.

현재 API/DDL/lockfile 변경은 없다. 서명 APK·실기기 잠금·TalkBack·운영 접근 및 v1 최종
출시는 이 UI 변경의 완료 주장에 포함하지 않는다.
