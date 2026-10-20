# 가전·공용 재고·교체·홈 화면 검증

SB-024~SB-027/SB-033, Issues #33~36/#42, R-03/R-16/R-17/R-18/R-19/R-22.
생성된 API 계약과 Android adapter의 24개 업무를 공통 React 화면에 연결했다.
이 client 변경에서 서버 계산·DB migration·native 인증 정책을 새로 구현하지 않는다.
문서의 부모 연결·업로드 화면은 SB-023의 별도 후속 통합 대상이다. 구매 링크·메모를 문서 첨부로 표현하지 않는다.

## 제품·규격·기기 연결

가전 목록·등록·상세·편집에서 제조사/모델/장소/구매일/가격/판매처/보증기한/관리·수리 메모를 다룬다.
가전 목록은 서버의 오늘 교체/구매/미확인 상태를 연결별로 요약하고 홈은 접을 수 있는 보증기한 안내를 제공한다.
미입력과 0원 구매액을 구분하고 가전 가격을 자산이나 금전 원본에 더하지 않는다. 보증 상태·기준일은 서버 응답을 표시한다.
소모품은 이름/규격/단위/부족 임계/메모를 관리하며 초기 재고를 metadata에 넣지 않는다.
기초 재고도 입고 또는 사유 있는 조정으로 남긴다. 사용 이력이 있는 단위의 변경은 서버가 거부한다.

동일 SKU의 공용 재고를 여러 기기에 연결한다. 기기별로 수동/일/개월 주기, 교체당 수량, 직접 지정한 다음 확인일을 관리한다.
다음 확인일·마지막 교체일·교체 필요·구매 필요·부족 임계 상태는 서버가 계산한 값을 표시한다.
교체 기준일 미확인과 아직 확인일이 오지 않은 상태를 구분한다. 재고 부족 임계 이하와 한 번 교체할 수량 부족도 구분한다.
직접 지정일을 비울 때는 해제를 확인한다. 교체 기록에 직접 지정일이 있으면 유지/해제를 명시적으로 선택한다.
지난 주기를 놓쳤다고 재고를 여러 번 차감하거나 구매일·입고일을 교체일로 추정하지 않는다.

목록은 cursor를 지원하며 연결 선택지는 모든 페이지를 조회한다. 중지한 연결은 동일 행으로 다시 사용한다.
가전/소모품 종료는 이력을 보존하며 새 사용을 제한한다. 참조 없는 오등록의 실제 삭제는 확인과 If-Match를 요구한다.
연결·교체·재고·문서 이력이 있으면 409 후 사용 종료/연결 중지를 안내한다. 취소한 과거 이력도 실제 삭제 근거로 없애지 않는다.

## 재고 명령·충돌·원본 보존

입고/반품 입고/반품 출고/사유 있는 조정과 기기별 실제 교체를 별도 화면에서 기록한다.
각 재고 동작은 생성 계약의 Idempotency-Key와 현재 **소모품 version**의 If-Match를 보낸다.
교체는 추가로 현재 기기 연결의 link_version을 보내며 stock version과 혼동하지 않는다.
입고·교체·취소 결과의 불변 참조를 현재 잔량으로 사용하지 않고 GET으로 다시 조회한다.

응답 유실/취소 후 같은 입력은 같은 작업 키로 확인한다. 바뀐 입력·검토한 현재 버전에는 새 키를 사용한다.
늦은 native 응답을 화면에 반영하지 않는다. 409에서는 작성한 날짜·수량·메모·사유를 유지하고 현재 재고/원본/기기 설정을 비교한다.
변경된 버전을 검토한 뒤 확인을 다시 요구하며 마지막 저장 승리로 상대방 편집을 덮지 않는다.
멱등키가 없는 metadata 생성의 응답이 불확실하면 목록 확인 전 재전송을 막는다.

취소는 원본 전체 수량의 반대 movement를 추가하고 원본과 취소 링크를 함께 표시한다.
교체 원본에서 취소하면 현재 주기·직접 지정일과 취소되지 않은 실제 교체 이력으로 서버가 다시 계산한 일정을 조회한다.
교체일 수정도 취소 후 올바른 날짜의 새 교체로 남긴다. 재고 사용 movement에서 교체 취소를 우회하지 않는다.
원장과 교체 상세에서 작성자·서울 작성 시각을 확인한다.

## 홈·플랫폼

홈의 첫 두 영역은 월간 자산 변화와 오늘 소모품이다. 서버 자산 합계/확인 건수/미입력/전월값 미확인/임시 합계와 비교 범위를 표시한다.
소모품 상태 요청에는 자산 월을 보내지 않으며 모든 페이지의 서버 as_of가 같은지 대조한다.
서울 날짜가 바뀌면 다시 조회하고 읽는 도중 날짜가 섞이면 오류로 재확인을 요구한다.
홈은 교체·입고·원본 상세로 바로 연결하며 수입·고정 납부·현재 사건/청구를 보조 영역으로 둔다.
등록 수입과 실제 보험금 순유입, 예정과 실제 납부를 구분하고 청구 상태를 보험금 수령으로 바꾸지 않는다.

Android는 동일 화면에서 typed native 업무를 호출한다. 잠금/세션 만료 때 입력 화면을 내리고 HTTP로 우회하지 않는다.
웹/Android 크기 검증, mock native React 동작, native JVM 정책, 실기기 검증은 서로 다른 증거다.
실기기 인증·백그라운드 실패 시나리오를 이 결과로 통과 처리하지 않는다.

## 실행한 검증

```bash
pnpm --filter @sallimbook/client typecheck
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp pnpm --filter @sallimbook/client exec playwright test tests/homecare-ui.spec.ts tests/homecare-model.spec.ts --config playwright.homecare.config.ts --workers 1
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp pnpm --filter @sallimbook/client exec playwright test tests/homecare-ui.spec.ts tests/homecare-model.spec.ts tests/homecare-native-ui.spec.ts tests/home.spec.ts tests/routing.spec.ts --config playwright.homecare.config.ts --workers 1
TMPDIR=/home/jihoon/.cache/sallimbook/test-tmp pnpm --filter @sallimbook/client exec playwright test tests/routing.spec.ts --grep 'keyboard skip link' --config playwright.homecare.config.ts --workers 1
pnpm build
uv run --project services/api ruff check scripts/test_web_auth.py
```

첫 46개 중 42개 통과, 두 원인으로 4개가 실패했다. 편집에서 상세로 돌아갈 때 같은 route component가
이전 데이터를 유지하던 문제를 edit 포함 key로 수정했고 select의 exact label matcher를 role/name으로 바꿨다.
삭제 3개와 native React 호출 검증을 추가한 뒤 **84개 중 82개**가 통과했다.
신규 66개(웹 업무 42, 모델 8, native React 16)는 모두 통과했다. 남은 2개는 바뀐 홈 링크 문구를 참조한 기존 키보드 assertion이었다.
현재 문구로 고친 뒤 해당 **2/2**를 다시 통과해 미해결 실패는 없다.
가전 목록 상태·홈 보증기한 표시를 추가한 뒤 관련 웹/native 홈 **4/4**가 통과했다. 최종 신규 검증은 **68개**(웹 44, 모델 8, native React 16)다.
24개 native 업무 모두 실제 React 조작을 통해 호출됐으며 HTTP 요청 0건, 204 삭제, version/멱등키, 잠금·세션·네트워크 및 늦은 응답을 대조했다.

공유 T-20 입고3/교체1, T-21 마지막 공용 재고의 경쟁, T-22 응답 유실 재시도, T-24 과거 자산 월/오늘 소모품 조건을 사용한다.
mock 검증이 실제 DB 동시성·권한을 대신하지 않으며 서버 검증은 [별도 기록](homecare-server.md)을 따른다.
전체 기존 브라우저 452개는 보험 통합 단계의 증거이며 이 homecare head에서 다시 실행했다고 주장하지 않는다.

production build와 타입 검사는 통과했다. Vite의 500KB 초과 단일 chunk 경고(784KB)가 남는다.
실제 HTTPS/API/PostgreSQL 검사는 아래 명령의 첫 실행에 통과했다. HTTP route mock을 사용하지 않았다.

```bash
uv run --project services/api python scripts/test_web_auth.py --homecare
```

실제 검증은 가전·규격·기기 연결 CRUD, 구매액 null/0, 보증기한, 공유 T-20 입고3/교체1을 UI로 수행했다.
두 실제 브라우저 화면에서 마지막 재고를 경쟁해 한 교체만 성공했고 다른 입력은 부족 오류와 함께 유지됐다.
직접 지정일 유지/해제, 교체 취소 뒤 과거 일정 복원, 조정·반품 입고/출고의 취소, 부족 재고 취소 거부,
참조 없는 오등록 삭제와 이력 있는 삭제 거부, 가전·소모품 사용 종료를 검증했다.
최종 공용 재고 2개를 모든 원장 수량 합과 대조하고, 홈 선택 월이 오늘 상태를 바꾸지 않는지 확인했다.
확정 자산의 revision/version/values가 그대로였으며 새 수입 원본 0건, no-store·If-Match·멱등키·브라우저 저장소 비사용을 확인했다.
임시 DB schema·개인 브라우저 산출물을 폐기하고 DB 중지를 확인했다.

18755 포트의 브라우저와 Docker 시험 DB 수명주기를 순차 실행한다. 임시 합성 계정·HTTPS 인증서·DB schema는 기존 harness가 관리한다.
사용자 데이터·기존 서버·기존 DB·호스트 Tailscale 설정을 변경하지 않는다.

## SB-034 삭제 검토 버전 회귀 보완

최종 통합 시험에서 기기별 주기를 수정한 직후 삭제하면, 화면은 새 주기를 표시하지만 삭제는
이전 `If-Match` 버전을 보내 409가 되는 간헐 오류를 확인했다. 빠른 native 응답에서는
`useResource.reload`의 loading 시작/종료가 한 render로 묶일 수 있다. 이때 삭제 컴포넌트가
unmount되지 않으므로 `useState(initial)`이 최초 버전을 계속 보유하는 것이 원인이었다.

공통 `DeleteHomecare` 안에서 대상 ID/version을 key로 삼는 검토 컴포넌트를 생성한다.
가전·소모품·기기 연결 모두 같은 수정을 적용받는다. 부모의 ID나 버전이 바뀌면 삭제 검토와
기존 확인을 닫고 새 확인을 받는다. 이미 확인한 요청에 새 버전을 자동 적용하지 않는다.
진행 중인 이전 요청의 대기는 중단하고 늦은 결과는 현재 화면의 삭제 성공으로 반영하지 않는다.
같은 ID/version의 단순 rerender와 409 후 명시적 비교·최신 내용 채택·재확인은 유지한다.

```bash
pnpm typecheck
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts tests/homecare-delete-snapshot.spec.ts --workers=1
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts tests/homecare-delete-snapshot.spec.ts --project desktop --grep 'idle deletion' --workers=1
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts tests/homecare-native-ui.spec.ts tests/homecare-ui.spec.ts --workers=1
pnpm build
python3 scripts/validate_docs.py
git diff --check
```

- 신규 결정적 회귀 **10/10 통과(8.9초)**: 부모를 unmount하지 않고 version/ID를 교체하며,
  새 버전 사용·이전 확인 폐기·동일 snapshot의 충돌 비교 유지·늦은 결과 무시를 확인했다.
  시험은 실제 공통 React 컴포넌트를 별도 root에 렌더하며 서버 권한 검증을 대체하지 않는다.
- 위 단일 desktop 시험을 `f278719`의 수정 전 삭제 컴포넌트로 실행했을 때 **의도한 1개 실패**를
  확인했다. 부모 표시 버전은 2인데 삭제 인자는 1이었다(기대 `[2]`, 실제 `[1]`). 시험 종료 시
  `finally`로 수정된 소스를 복원한 뒤 기존 기능 검증을 진행했다.
- 기존 웹·native 가전/재고 시험 **60/60 통과(1.4분)**. native 기기 연결 수정→삭제가 최신
  `If-Match: "2"`를 단 한 번 보내는 assertion도 추가했다. 기존 409 비교와 참조 삭제 거절을 포함한다.
- 초기 시험 harness의 Vite CommonJS import/중복 runtime 문제는 기존에 로드된 React runtime을
  재사용하도록 고쳤다. 위 통과 결과는 수정된 harness 기준이다.
- 타입·빌드 통과(165 modules, JS 894.22kB/gzip 231.17kB). 기존 500kB chunk 경고는 남는다.

API 계약·DB·migration·native 인증 정책 변경은 없다. 이 수정의 전체 통합 브라우저/실제 HTTPS
재검증은 통합 브랜치에서 별도로 수행하며 위 표적 검증과 구분한다. 18756 브라우저를 종료하고
검증 큐를 반환했다. 이 단계에서 Docker/DB는 사용하지 않았다.

## 리뷰 보완: 곧 교체·홈 순서·해제한 직접 지정일 (WP07)

홈 "살펴볼 소모품"은 교체 확인 필요 → 구매 필요 → 곧 교체 → 재고 부족 → 교체일 미확인 순으로,
같은 순위는 가전·소모품 이름순으로 정렬해 앞 4개를 보여 준다. "곧 교체" 필터와 상태 칩을 추가했다.
곧 교체는 서버 `as_of` 다음 날부터 7일 안의 다음 확인일이며 별도 API 필드 없이 화면에서 계산한다.
홈 보증 카드는 보증기간 안 항목을 만료가 가까운 순으로, 그다음 최근에 끝난 항목 순으로 보여 준다.
교체 취소 검토 안내는 이 교체 때 해제한 직접 지정일이 그 뒤 기기 설정을 바꾸지 않았다면 다시 적용된다고 설명한다.

```bash
pnpm typecheck
pnpm --filter @sallimbook/client exec playwright test tests/homecare-model.spec.ts tests/homecare-ui.spec.ts tests/homecare-native-ui.spec.ts tests/home.spec.ts tests/design-refresh.spec.ts
uv run --project services/api python scripts/test_web_auth.py --homecare
```

- 순서·필터·칩, 보증 순서, 취소 안내의 새 시험은 각각 구현 전에 실패(개수 5 대 6, 오래 만료된 항목 우선, 문구 없음)를 확인한 뒤 통과했다.
- desktop·android-size Playwright **110/110 통과**. 기본 mock에는 곧 교체 항목이 없어 기존 "확인할 소모품 2개"는 그대로다.
- 실제 HTTPS 가전·재고 흐름 통과. 해제 교체 취소 뒤 기대값을 옛 동작(교체 이력 기준 2025-04-05)에서
  되살린 직접 지정일(2027-01-01·override)로 바꿨다. 그 날짜는 아직 오지 않아 홈 기본 필터에 나오지 않으므로,
  사용 중·종료 연결을 비교하는 홈 확인은 "모든 연결" 필터에서 수행한다.
- 생성 client와 Android 정책·브리지는 바뀌지 않아 JVM 시험은 대상이 아니다.
- **미실행:** Galaxy 실기기의 홈 카드 순서·보증 카드 확인. 사용자 확인 전에는 통과로 보지 않는다.
