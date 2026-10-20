# 상용 사용성을 위한 화면 구조 개편 검증

관련 요구사항: R-02(Android·PC), R-03(홈 우선순위), SB-003. 기준 구현은 `173213a`이며 자산·보험·생활관리·인증 기능의 기존 API 계약과 보안 경계를 유지한다.

## 변경과 보존 범위

공통 토큰·직접 작성한 SVG 아이콘·탐색·주요 48px 컨트롤·카드·목록·표·빈 상태·로딩·오류를 정리했다. 로그인은 입력과 실행 버튼을 먼저 보여 주고, 홈은 월간 자산 다음 오늘의 소모품 상태를 보여 준다. 자산 목록의 필터와 반복 상세는 펼침으로, 자산 기본정보 폼은 세 구역으로, 보험 사건은 PC의 관련 원본 두 열 배치로 개편했다.

월 기록·금액·확인 상태는 API 원본을 사용한다. 범위·지분 변경과 기준일 경고는 접지 않는다. 홈의 이전 순자산·동일 범위·증감률·미계산 이유는 상세 펼침에서 기존 비교 화면과 같은 설명을 사용한다. 조회 실패 시 탐색과 명시적 재시도를 유지한다.

마이그레이션, API/생성 client 변경, 네이티브 인증·보관함·CVC 경계 변경, 패키지·잠금 파일 변경은 없다. 로그인 기기 이름은 기본값을 유지한 채 펼쳐 수정하며, 빈 기기 이름의 HTML 검증은 해당 펼침을 자동으로 연다. 비밀번호·패스키·가계 시작 처리기는 유지했다. HTTPS 브라우저 fixture는 기기 이름 변경 전에 펼치는 동작을 추가했다.

Pretendard Variable v1.3.9 원본 WOFF2와 OFL을 앱에 포함했다. 출처·고정 commit·해시·약 2 MB의 초기 다운로드 영향은 [디자인 시스템](../design-system.md)에 기록했다. 라이선스 문구가 배포 산출물에도 포함되는 것을 확인했다. 외부 폰트 CDN 요청은 없다.

## 실행한 검증

| 범위 | 결과 |
| --- | --- |
| `pnpm typecheck` | 통과 |
| `pnpm build` | 통과, 169 modules |
| 관련 19개 브라우저 spec, 2 workers | 482건 통과, 5.8분 |
| 홈 상세 설명·오류 탐색 수정 후 자산/비교/홈/경로/디자인 | 86건 통과, 1.7분 |
| 확대 배치·fixture 타입 정정 후 디자인/비교/고정비/보험 이벤트 | 108건 통과, 1.0분 |
| 최종 자산 재시도·디자인·자산 | 40건 통과, 21.8초 |
| 첫 달 작성/정정 상태·설정 버튼 크기 보완 후 디자인·홈 | 30건 통과, 18.5초. `pnpm typecheck`, `pnpm build`, 해당 테스트 명시적 TypeScript 검사도 통과 |
| 변경 UI 테스트와 HTTPS integration spec 명시적 TypeScript 검사 | 통과 |
| 변경 문서의 로컬 링크 검사 | 3개 통과 |
| `git diff --check` | 통과 |
| 통합 단계 실제 HTTPS `--onboarding`, `--finance`, `--homecare`, `--insurance` | 모두 통과, 실제 API/PostgreSQL 사용 |
| 통합 단계 `pnpm test:docs` | 문서 70개·링크 336개·68 tests 통과 |
| PR #93 최종 원격 CI, `7498c94`, run `39094729822` | 필수 7개 job 모두 성공. Web job 전체 브라우저 1,100건 통과(12.0분), 실제 HTTPS 시나리오 11개 성공 |

위 브라우저 수치는 단계별 재검증을 포함하므로 서로 더한 값을 서로 다른 테스트 수로 해석하지 않는다. 모든 fixture는 합성 데이터다. 브라우저 범위는 인증·가계 시작·native adapter·앱 잠금·자산·계좌·카드·월 비교·고정비·보험·가전/재고·첨부·26개 직접 경로를 포함한다.

최종 번들은 JS 924.27 kB(gzip 237.91 kB), CSS 37.72 kB(gzip 8.38 kB), 로컬 폰트 2,057.68 kB다. 기존 500 kB 이상 JS 번들 경고는 남는다.

## 최종 시각 확인

합성 fixture로 PC 1440×1000, 모바일 390×844에서 로그인·홈·자산 목록·보험 사건·소모품·자산 입력 폼·월간 비교의 14개 화면을 최종 캡처했다(14건 통과, 22.0초). 모바일 다크 모드 4개, 200% 글꼴 4개, 빈 상태·로딩·오류의 PC/모바일 6개도 확인했다. 마지막 수정에 해당하는 홈과 오류 화면은 다시 캡처했다. 캡처는 저장소에 포함하지 않는다.

일반 크기 모바일에서 첫 소모품 상태 하단은 y=760.7로 하단 메뉴 위에 있고, 로그인 버튼 하단은 y=602.6이다. 월·확인 상태·범위/기준일 주의가 계속 보인다. 200%에서는 월 선택기가 독립된 행으로 줄바꿈해 내부 글자 잘림을 방지한다. 화면 전체의 가로 넘침을 검사했고, 비교 표는 자체 스크롤을 유지한다. 320px·200%에서 `9,007,199,254,740,993원`을 손실 없이 표시하는 회귀도 통과했다.

Chromium의 실제 렌더 글꼴 조회에서 `Pretendard Variable`, `isCustomFont: true`를 확인했다. 기존 WSL의 한국어 대체 글꼴은 WenQuanYi Zen Hei였다. 본문·보조 글자·주요 버튼·경고·오류의 sRGB 대비 계산은 밝은 화면 최소 5.00:1, 어두운 화면 최소 7.01:1이다. 이는 해당 토큰 조합 확인이며 전체 화면의 WCAG 인증을 뜻하지 않는다.

## 발견 후 수정한 항목

첫 실행은 372건 중 355건 통과, 17건 실패였다. 사이드바와 본문의 계정명을 함께 찾던 locator 13건은 본문으로 한정했다. 기존 홈 heading 검사 2건은 가계 시작 안내와 구분해 자산·소모품 영역의 순서를 검사하도록 수정했다. 모바일에서 숨겼던 월 레이블은 항상 보이도록 복원했다. 6-worker 실행 중 26개 경로를 합쳐 검사하는 desktop 시험 1건은 60초를 넘었다. 제한을 늘리지 않고 2-worker 재실행에서 desktop 38.5초, Android 크기 35.4초로 통과했다.

시각 검토에서는 확대 시 월 입력 내부 잘림과 필터 안에 있던 오류 재시도 동선을 수정했다. 코드 대조에서는 홈의 증감률 미계산 이유·작성본 설명을 기존 비교 설명과 공통화했다. 별도 TypeScript 검사에서 발견한 기존 support fixture의 규칙 변경 입력 타입, 보험 응답의 사유 제외 구성, `no_previous_month` enum을 생성 계약에 맞게 정정했다. 해당 fixture를 사용하는 비교·고정비·보험 이벤트 시험을 다시 통과했다.

통합 재검토에서 첫 달의 모든 금액이 확인됐어도 월 자체는 작성 중·정정 중일 수 있음을 확인했다. 비교 결과가 `no_previous_month`여도 현재 월 상태를 독립적인 배지로 항상 표시하도록 수정하고 두 상태를 PC·Android 크기에서 검사했다. 좁은 화면의 설정 링크도 최소 48×48px로 맞췄다.

별도 원격 기준 `d8585dc`의 2-worker 전체 회귀는 1,072건 중 1,070건 통과·홈 2건 실패였다. 가계 시작 안내까지 포함한 전체 h2 locator가 원인이며, setup fixture 누락으로 Vite 연결 거부도 3회 발생했다. 이번 변경의 `home.spec.ts`는 `.dashboard-grid`의 두 핵심 제목만 검사하고 `/api/v1/household/setup`을 명시적으로 응답한다. 위 30건 실행에 해당 홈 검사를 포함했다.

이후 [PR #93의 원격 전체 실행](https://github.com/jihoon22-lee/SallimBook/actions/runs/39094729822)에서 해당 실패가 해소됐고 7개 job이 모두 성공했다. 브라우저 1,100건과 HTTPS 11개는 같은 Web job의 서로 다른 검사 단계이며, 다른 job의 첨부·내보내기 결과를 이 11개에 포함하지 않았다. PR #93은 main에 병합됐다. 원격 CI 성공은 운영 웹·APK 배포 완료나 실제 Galaxy 인수를 뜻하지 않는다.

## 한계

통합 단계에서 첫 시작·배우자 연결, 금융 자산·재인증, 가전/소모품, 보험의 실제 HTTPS API·PostgreSQL 흐름을 재실행해 통과했다. 모두 합성 계정과 일회용 schema를 사용했으며 HTTP route mock을 사용하지 않았다. 금융 시험은 가상 인증기의 실제 WebAuthn 서명도 확인했다. 시험 schema·서버를 정리하고 전용 시험 DB를 중지했다.

Android 실기기 시험은 다시 실행하지 않았다. Android WebView·키보드·TalkBack·생체 인증 실패·보관함 복호화는 기존 실기기 게이트에서 별도로 확인해야 한다. 문서 manifest는 통합 단계에서 갱신·검증했다.

## 재현 명령

```sh
pnpm typecheck
pnpm build
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts --workers 2 tests/design-refresh.spec.ts tests/home.spec.ts tests/routing.spec.ts tests/assets.spec.ts tests/accounts.spec.ts tests/comparison.spec.ts tests/insurance-core.spec.ts tests/insurance-events.spec.ts tests/homecare-ui.spec.ts tests/auth.spec.ts tests/auth-native.spec.ts tests/onboarding.spec.ts tests/onboarding-native.spec.ts tests/passkeys.spec.ts tests/app-lock-native.spec.ts tests/cards.spec.ts tests/documents-ui.spec.ts tests/documents-pagination.spec.ts tests/homecare-delete-snapshot.spec.ts
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts --workers 2 tests/design-refresh.spec.ts tests/comparison.spec.ts tests/fixed.spec.ts tests/insurance-events.spec.ts
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts --workers 2 tests/design-refresh.spec.ts tests/home.spec.ts
```

명시적 테스트 타입 검사는 `apps/client`에서 다음을 실행했다.

```sh
pnpm exec tsc --noEmit --strict --skipLibCheck --moduleResolution bundler --module esnext --target es2022 --jsx react-jsx --lib ES2022,DOM,DOM.Iterable tests/design-refresh.spec.ts tests/assets.spec.ts tests/auth.spec.ts tests/auth-native.spec.ts tests/comparison.spec.ts tests/home.spec.ts tests/routing.spec.ts tests/passkeys.spec.ts tests/onboarding.spec.ts tests/onboarding-native.spec.ts integration/*.spec.ts
```

## 웹 사용성 보완 (2026-10-20)

변경: React Router data router 전환(경로·제목 불변), 뒤로가기의 스크롤·불러온 페이지 복원, 미저장 입력 확인창과 저장·취소·삭제 뒤 기록 교체,
쉼표 금액 입력 공통 파서와 저장 시 필드 오류 안내, 입력 테두리·보조 글자 대비 상향, 좁은 화면 월 라벨·12px 최소 글자·48px 구간 버튼,
월 행 편집 뒤 초점 복귀와 동작 줄이기, 홈 제목 순서·메뉴 `aria-current`·표 스크롤 영역 이름, 취소·재시도 문구 통일, 사용하지 않는 CSS·중복 선택자·`!important` 정리.
DB 마이그레이션, API 계약·생성 client, 서버, Android 네이티브 코드 변경은 없다.

추가·변경한 시험:

| spec | 확인 내용 |
| --- | --- |
| `history-restore.spec.ts` | 뒤로가기에서 목록 스크롤과 불러온 페이지 수 복원, 새 화면 진입 시 맨 위 |
| `unsaved-changes.spec.ts` | 탭·취소·브라우저 뒤로가기·Android 뒤로가기에서 확인창, 저장 뒤 목록 착지, 창 닫기 확인 |
| `krw-input.spec.ts` | 숫자·쉼표·공백·전각 숫자·끝의 `원` 허용, 잘못 묶은 자릿수·소수·음수·20자리 초과 거부 |
| `design-refresh.spec.ts` | 두 테마의 입력 테두리 3:1·보조 글자 4.5:1, 좁은 홈의 월 라벨·12px 글자·48px 구간 버튼, `!important` 정리 전후 계산 값 고정 |
| `months.spec.ts` | 행 편집 저장·취소 뒤 행 버튼으로 초점 복귀, 동작 줄이기에서 즉시 스크롤 |
| `home.spec.ts`, `routing.spec.ts` | 로그아웃 홈의 첫 제목이 화면 h1, 메뉴의 `page`·`true` 구분 |
| `income.spec.ts`, `fixed.spec.ts` | 수입 화면 동시 실패 시 재시도 버튼 하나, 고정 납부 목록 제목의 선택 월 |
| 각 도메인 spec | 금액 오류를 저장 시 필드 아래에 알리고 저장 버튼을 미리 막지 않음 |

CSS 정리는 임시 계산 스타일 비교로도 확인했다. 밝은·다크 테마 × 390·1280px × 16개 경로의 모든 요소·모든 계산 속성을 정리 전후로 비교해 차이 0건이었다.
이 비교 스크립트는 저장소에 남기지 않았다.

| 범위 | 결과 |
| --- | --- |
| `pnpm typecheck` | 통과 |
| `pnpm --filter @sallimbook/client build` | 통과, 182 modules. CSS 44.36 kB(gzip 9.44 kB), JS 1,030.99 kB(gzip 270.91 kB). 기존 500 kB 경고 유지 |
| 전체 브라우저 시험 `pnpm --filter @sallimbook/client exec playwright test` | 1,370건 통과, 8.3분 |
| 이 변경 범위의 API·서버·플러그인·Android 차이 | 없음 |
| 실제 HTTPS 시나리오(인증·`--finance`·`--months`·`--cashflow`·`--insurance`·`--homecare`, 하나씩 실행) | 6개 모두 통과, 실제 API/PostgreSQL. 첫 `--insurance` 실행은 배분 합계 불일치 때 저장 버튼 비활성을 기대하던 기존 시험 1곳 때문에 실패했다. 저장을 누르면 이유에 초점이 가는 새 동작으로 시험을 바꾼 뒤 통과했다 |

Android 실기기 확인(하드웨어 뒤로가기 확인창, 저장 뒤 뒤로가기 착지, 쉼표 금액 저장)은 사용자 확인 전까지 미실행이다.
