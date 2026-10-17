# 월간 자산 비교·추이 검증

SB-013 / Issue #22 / R-05·R-06·R-19. `/assets/compare`, 홈 자산 요약, 자산·계좌 상세가
생성 API client의 비교·추이 응답을 사용한다. API 계약과 서버 계산은 `docs/api-contract.md`를 따른다.

## 표시와 데이터 경계

두 월의 순자산, 전체 변화, 동일 범위 변화, 증감률을 분리한다. 추가·종료·지분 변경의 영향을
신규 저축이나 투자 수익률로 해석하지 않는다. 이전 순자산이 0 또는 음수이면 증감률 대신 사유를 표시한다.
미입력, 기록 없는 월, 작성·정정 중인 월은 0원이나 확정값으로 대체하지 않는다.

소유자·분류·자산·부채 필터는 당시 월 기록에 적용한다. 항목의 이름·소유·지분·금액 기준·기준일도
당시 기록을 표시한다. 자산과 계좌 상세는 같은 asset_id를 조회하며 계좌 잔액을 다시 합산하지 않는다.
홈은 한 항목만 요청하더라도 서버의 전체 범위 합계를 표시하고 오늘 기준 소모품 영역을 이어 배치한다.

추이는 3·6·12·24·60·120개월이며 확정값만 선으로 잇는다. 빈 달과 미확정 구간은 선이 끊어지고
접근 가능한 표와 월 선택기로 정확한 금액·상태를 확인한다. 금액은 문자열/BigInt로 유지하며
SVG의 제한된 픽셀 좌표만 Number로 바꾼다. 월중·혼합·누락 기준일을 월말 잔액으로 바꾸지 않는다.

페이지 사이 revision/version 변경이나 중복 항목은 결합을 거부한다. 비교와 추이에서 동일 월의
revision/version 또는 상태가 다르면 추이를 숨기고 두 조회를 함께 다시 확인하도록 한다.
월 입력·확정·정정 경로와 연결하지만 비교 조회는 금액을 쓰거나 수입·납부를 자동 반영하지 않는다.

## 실행한 검증

```bash
pnpm --filter @sallimbook/client typecheck
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp pnpm --filter @sallimbook/client exec playwright test tests/comparison.spec.ts --config playwright.comparison.config.ts --workers 1
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp uv run --project services/api python scripts/test_web_auth.py --comparison
```

신규 UI 28개가 desktop/Android 크기에서 통과했다. 실제 HTTPS 검사도 통과했다. 후자는 합성 데이터를
실제 PostgreSQL/API로 등록·확정·정정한 뒤 전체 변화 55,000,001원과 동일 범위 30,000,000원을
대조하고, 기준일·지분 경고, 과거 확정본 보존, 빈 달, 정정 중인 월, 자산 상세·홈 연결과 no-store를 확인한다.
임시 DB schema와 개인 임시 디렉터리를 폐기하고 DB 서비스 중지·전역 잠금 반환을 확인했다.

전용 UI 포트는 18750이며 기존 서버를 재사용하지 않는다. Playwright config는 base 객체를 한 번만
펼쳐 기본 서버와 전용 서버가 함께 시작되지 않게 한다. 전체 회귀 최초 실행은 217개 통과,
Android 크기 route 반복 검사 1개 실패였다. trace에 의존 모듈의 `net::ERR_NETWORK_CHANGED`가
있었고 동시에 실제 HTTPS 검사용 Docker DB를 생성했다. 브라우저 회귀와 Docker 네트워크 생성은
순서대로 실행한다. 같은 코드로 Android route 검사 8개를 단독 재실행해 모두 통과했다. Android 네이티브 bridge 연결과 해당 최종 검증은 통합 이후 결과로 갱신한다.
