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
| 변경 UI 테스트와 HTTPS integration spec 명시적 TypeScript 검사 | 통과 |
| 변경 문서의 로컬 링크 검사 | 3개 통과 |
| `git diff --check` | 통과 |

위 브라우저 수치는 단계별 재검증을 포함하므로 서로 더한 값을 서로 다른 테스트 수로 해석하지 않는다. 모든 fixture는 합성 데이터다. 브라우저 범위는 인증·가계 시작·native adapter·앱 잠금·자산·계좌·카드·월 비교·고정비·보험·가전/재고·첨부·26개 직접 경로를 포함한다.

최종 번들은 JS 924.12 kB(gzip 237.86 kB), CSS 37.72 kB(gzip 8.38 kB), 로컬 폰트 2,057.68 kB다. 기존 500 kB 이상 JS 번들 경고는 남는다.

## 최종 시각 확인

합성 fixture로 PC 1440×1000, 모바일 390×844에서 로그인·홈·자산 목록·보험 사건·소모품·자산 입력 폼·월간 비교의 14개 화면을 최종 캡처했다(14건 통과, 22.0초). 모바일 다크 모드 4개, 200% 글꼴 4개, 빈 상태·로딩·오류의 PC/모바일 6개도 확인했다. 마지막 수정에 해당하는 홈과 오류 화면은 다시 캡처했다. 캡처는 저장소에 포함하지 않는다.

일반 크기 모바일에서 첫 소모품 상태 하단은 y=760.7로 하단 메뉴 위에 있고, 로그인 버튼 하단은 y=602.6이다. 월·확인 상태·범위/기준일 주의가 계속 보인다. 200%에서는 월 선택기가 독립된 행으로 줄바꿈해 내부 글자 잘림을 방지한다. 화면 전체의 가로 넘침을 검사했고, 비교 표는 자체 스크롤을 유지한다. 320px·200%에서 `9,007,199,254,740,993원`을 손실 없이 표시하는 회귀도 통과했다.

Chromium의 실제 렌더 글꼴 조회에서 `Pretendard Variable`, `isCustomFont: true`를 확인했다. 기존 WSL의 한국어 대체 글꼴은 WenQuanYi Zen Hei였다. 본문·보조 글자·주요 버튼·경고·오류의 sRGB 대비 계산은 밝은 화면 최소 5.00:1, 어두운 화면 최소 7.01:1이다. 이는 해당 토큰 조합 확인이며 전체 화면의 WCAG 인증을 뜻하지 않는다.

## 발견 후 수정한 항목

첫 실행은 372건 중 355건 통과, 17건 실패였다. 사이드바와 본문의 계정명을 함께 찾던 locator 13건은 본문으로 한정했다. 기존 홈 heading 검사 2건은 가계 시작 안내와 구분해 자산·소모품 영역의 순서를 검사하도록 수정했다. 모바일에서 숨겼던 월 레이블은 항상 보이도록 복원했다. 6-worker 실행 중 26개 경로를 합쳐 검사하는 desktop 시험 1건은 60초를 넘었다. 제한을 늘리지 않고 2-worker 재실행에서 desktop 38.5초, Android 크기 35.4초로 통과했다.

시각 검토에서는 확대 시 월 입력 내부 잘림과 필터 안에 있던 오류 재시도 동선을 수정했다. 코드 대조에서는 홈의 증감률 미계산 이유·작성본 설명을 기존 비교 설명과 공통화했다. 별도 TypeScript 검사에서 발견한 기존 support fixture의 규칙 변경 입력 타입, 보험 응답의 사유 제외 구성, `no_previous_month` enum을 생성 계약에 맞게 정정했다. 해당 fixture를 사용하는 비교·고정비·보험 이벤트 시험을 다시 통과했다.

## 한계

이번 변경에서 실제 HTTPS API·PostgreSQL 통합 및 Android 실기기 시험은 다시 실행하지 않았다. HTTPS fixture의 타입 검사와 mock 브라우저 시험을 실제 서버 검증으로 간주하지 않는다. Android WebView·키보드·TalkBack·생체 인증 실패·보관함 복호화는 기존 실기기 게이트에서 별도로 확인해야 한다. 문서 manifest의 통합 갱신은 최종 PR에서 수행한다.

## 재현 명령

```sh
pnpm typecheck
pnpm build
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts --workers 2 tests/design-refresh.spec.ts tests/home.spec.ts tests/routing.spec.ts tests/assets.spec.ts tests/accounts.spec.ts tests/comparison.spec.ts tests/insurance-core.spec.ts tests/insurance-events.spec.ts tests/homecare-ui.spec.ts tests/auth.spec.ts tests/auth-native.spec.ts tests/onboarding.spec.ts tests/onboarding-native.spec.ts tests/passkeys.spec.ts tests/app-lock-native.spec.ts tests/cards.spec.ts tests/documents-ui.spec.ts tests/documents-pagination.spec.ts tests/homecare-delete-snapshot.spec.ts
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts --workers 2 tests/design-refresh.spec.ts tests/comparison.spec.ts tests/fixed.spec.ts tests/insurance-events.spec.ts
```

명시적 테스트 타입 검사는 `apps/client`에서 다음을 실행했다.

```sh
pnpm exec tsc --noEmit --strict --skipLibCheck --moduleResolution bundler --module esnext --target es2022 --jsx react-jsx --lib ES2022,DOM,DOM.Iterable tests/design-refresh.spec.ts tests/assets.spec.ts tests/auth.spec.ts tests/auth-native.spec.ts tests/comparison.spec.ts tests/home.spec.ts tests/routing.spec.ts tests/passkeys.spec.ts tests/onboarding.spec.ts tests/onboarding-native.spec.ts integration/*.spec.ts
```
