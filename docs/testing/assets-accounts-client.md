# 자산·계좌 클라이언트 검증 기록

SB-010/R-04·R-22, SB-011/R-06·R-18에 해당하는 기본정보 UI를 연결했다.
자산·계좌 서버 계약은 생성 client를 사용하며 임의의 두 번째 API 계약은 두지 않는다.

## 구현 범위

- 자산·부채 목록/필터/페이지, 등록, 상세, 기본정보 수정, 사용 종료. 소유자·공동 소유·가계 지분·금액 입력 기준·합계 포함 여부·시작/종료일·메모를 관리한다.
- 계좌 목록/유형·소유자·상태 필터, 새 금융 자산과 동시 등록 또는 기존 금융 자산 연결, 상세, 기본정보 수정, 연결 자산과 함께 사용 종료. 입출금·적금·정기예금·증권·연금저축·IRP·DC·ISA·CMA·기타 유형을 모두 제공한다.
- 409 시 작성 내용을 유지하고 저장을 막는다. 사용자가 서버 최신 값을 확인한 뒤 바꾼 필드만 유지하거나 서버 값으로 돌아갈 수 있다. 확인만으로 자동 저장하지 않는다.
- 계좌번호는 별도 입력/삭제/일시 열람. 웹은 전용 DOM에 최대 30초만 표시하고 이탈·숨김·버전 변경에 지운다. 번호를 일반 React state, 목록 DTO, URL, 브라우저 저장소에 넣지 않는다. Android는 보호 화면에 위임하고 JS에는 상태만 반환한다.
- 패스키 추가 확인은 `account.reveal`과 대상 계좌 ID로 제한된다. 인증 grant는 같은 작업에서 소비하며 일반 재인증 상태로 승격하지 않는다.

월 스냅샷 금액·확정·월간 비교, 카드/수입 연결 관리, 운영 배포와 실기기 보안 시험은 이 기록의 완료 범위가 아니다.
금액 미조회 상태를 0원으로 만들어 표시하지 않고, 계좌와 금융 자산을 두 번 합산하지 않는다.

## 재현 명령

```bash
pnpm install --frozen-lockfile
uv sync --project services/api --frozen
pnpm api:generate
pnpm typecheck
pnpm --filter @sallimbook/client exec playwright test --config playwright.finance.config.ts
uv run --project services/api python scripts/test_web_auth.py --finance
pnpm android:sync
cd apps/client/android
./gradlew testDebugUnitTest assembleDebug compileReleaseKotlin
```

UI 서버는 18748을 사용하고 이미 점유된 포트를 재사용하지 않는다. HTTPS 검증은 `sallimbook-dev`의
일회용 db-test(18745)를 전역 잠금으로 조정한다. 고유 임시 schema에 실제 migration/API를 띄우고 삭제한다.
실제 패스키 서명은 Chromium 가상 인증기로 생성하며 개인키를 추출하지 않는다.
서버 필드 암호키는 mode 0600 임시 파일에만 저장한다. 브라우저 인증 fixture, 테스트 제어 값, 키,
입력·응답 본문을 stdout에 출력하지 않는다. 실패 시 안전한 소스 위치와 고정 단계 표시만 출력하고
비공개 산출물은 삭제한다. 합성 데이터만 사용한다.

## 확인 결과

- 생성 API 재생성과 TypeScript 검사 통과.
- 웹 UI 전체 **162개 통과**: desktop 및 Android 크기의 자산 14, 계좌 웹 18, 계좌 native bridge 10, 기존 인증/패스키/라우팅 등 120.
- 지분 문자열을 정확히 변환하고, 공동 자산 한 건, 연결 금융 자산 한 건, 빈 금액 상태, 필터 연속 변경을 확인했다.
- 자산/계좌 409 비교와 변경하지 않은 서버 필드 보존, 연결 중복 거부, 종료일 보존, 접근 불가 화면, CSRF 재시도를 확인했다.
- 계좌번호 30초(브라우저 시계 제어), blur/pagehide/화면 이동, 늦은 응답 폐기, 별도 번호 요청과 삭제, 저장 실패 시 입력 지우기를 확인했다.
- native bridge 모의시험은 웹 API 호출 0회, JS 번호 입력/출력 없음, 정확한 ID·버전 인자, 오류·취소 후 마스킹 메타데이터 재확인, 세션 만료 시 화면 해제를 확인했다.
- 실제 HTTPS finance **2개 통과**(desktop/Android 크기): 실제 PostgreSQL·API·서버 필드 암호화·가상 인증기 서명으로 계좌 저장, 마스킹, 단일 금융 자산 연결, 정확한 지분, 실제 409 비교, scope 제한, 30초 표시와 종료를 검증했다. 일반 재인증이 필요한 패스키 등록은 scope 확인 뒤에도 403이며, 성공/오류 응답의 no-store를 확인했다.
- Android 최신 JVM 검사 **64개 통과**(실패·오류·생략 0), release Kotlin 컴파일, `pnpm android:sync`, 최신 계좌 UI를 포함한 `assembleDebug` 통과. debug APK는 정식 배포하지 않았다.

## 검증의 한계

브라우저 모의응답은 서버 권한·암호화 검증이 아니다. native bridge 모의시험과 JVM 정책 검사는
실제 Keystore·화면 캡처·백그라운드·회전·기기 잠금·Credential Manager/DAL 검증이 아니다.
실제 도메인/운영 서명/정식 APK 배포와 Android 실기기 실패 시나리오는 별도 출시 조건으로 남아 있다.

### 통합 후 재검증

패스키/계좌 서버의 최종 계약을 합친 뒤 전체 UI162·실제 finance HTTPS2·JVM64·개발APK·releaseKotlin을 다시 통과했다. CI에도 실제 `--finance` 검사를 추가했다. UI 시험용 config는 base와 별도 포트 서버를 동시에 시작하지 않도록 단일 config 객체를 사용한다.
초기 두 전체 회귀는 각각160/162,161/162였고 인증 화면 초기 로드 시간 초과가 남았다. 실패 항목은 단독 재검사를 통과했으며 최종 전체162를 다시 통과했다. 같은 작업 환경의 별도 routing trace에서 Docker 시험 컨테이너 시작/재생성과 겹친 JavaScript 요청의 `net::ERR_NETWORK_CHANGED`를 확인했으므로 UI 브라우저 검사는 Docker 상태 변경과 직렬화한다. 임시 파일은 여유 있는 저장소를 사용한다.
