# PC 웹 보관함 검증

SB-031, Issue #40, R-09/R-10/R-18/R-20. 생성 계약과 표준 WebCrypto로
설정·카드 비밀 입력/열람/폐기·암호 변경·공유/수락/취소/철회·복구·전체 키 교체/재개/중단을 연결한다.
일반 개요 화면의 검증은 [개요 기록](vault-overview.md), 서버 권한은 [서버 기록](vault-server.md)을 따른다.

## 보호 경계

웹 전용 adapter는 생성 API client를 사용하며 Android HTTP fallback을 제공하지 않는다.
입력 암호·PAN·유효기간·복구코드는 uncontrolled DOM에서 읽고 즉시 입력을 비운다.
키와 변경 가능한 byte 배열은 한 mounted 작업이 소유하며 React state/Query cache/브라우저 저장소에
넣지 않는다. 표시 문자열은 전용 일시적 DOM output만 사용한다. 웹 화면 캡처 차단은 보장하지 않는다.
CVC 입력·저장·전송 경로는 없다.

표준 PBKDF2-HMAC-SHA256/HKDF-SHA256/AES-256-GCM과 고정 v1 AAD/바이너리 포맷을 사용한다.
키 확인·strict UTF-8·canonical base64url·한도·가계/카드/구성원/버전을 확인하고 태그/포맷 실패는
평문 표시 없이 종료한다. 공개 Python/Android 벡터와 일치하며 임의 정규화/trim을 하지 않는다.

blur/pagehide/비가시 상태·제한 시간·unmount에 키/입력/표시를 지우고 요청을 취소한다.
한 작업 단계는 최대 60초, 카드 표시는 최대 30초이며 queued timer가 늦어도 monotonic deadline을
직접 검사한다. 표시 중 5초마다 권한·카드 버전을 재확인한다. 종료 후 도착한 파생 키와 byte도 폐기한다.
런타임/브라우저 내부 사본의 완전한 메모리 소거를 보장한다고 표현하지 않는다.

복구코드는 서버 초기화/복구/교체 준비 전에 최대 30초 표시하고 오프라인 보관 확인 뒤 저장한다.
체크박스 입력으로 표시 시한을 늘리지 않는다. 유효한 확인 뒤에는 표시를 지우고 다음 작업의 제한 시간을 적용한다.
모든 mutation은 같은 opaque body/version/Idempotency-Key로 결과를 확인할 수 있다.
408/연결 실패/5xx는 결과 불명확 상태를 보존하며 자동 재전송하지 않는다.
교체의 중간 prepare/stage 재시도 성공을 전체 교체 완료로 표시하지 않는다.

키 교체는 종료 카드까지 서버 manifest의 원본과 staged 평문을 대조한 뒤 전체 finalize를 요청한다.
한 카드마다 제한 시간을 새로 시작한다. 5분 최근 계정 인증 만료에는 raw 키와 입력을 즉시 지우고
같은 화면에서 계정 비밀번호를 재확인한다. 잘못된 계정 비밀번호는 같은 화면에서 다시 입력할 수 있다.
그 뒤 기존/새 보관함 암호로 키를 다시 풀고 원본 manifest와 두 무작위 HVK의 SHA-256 지문이 같을 때만
이미 검증한 카드 다음부터 진행한다. 이 cursor/지문은 메모리에만 있고 화면 이탈 시 폐기한다.
서버 인증 시한을 연장하거나 refresh를 재인증으로 간주하지 않는다.

## 실행 결과

```bash
pnpm --filter @sallimbook/client exec playwright test --config playwright.vault.config.ts tests/vault-crypto.spec.ts tests/vault-workflow.spec.ts tests/vault-private.spec.ts --workers=1
pnpm --filter @sallimbook/client exec playwright test --config playwright.vault.config.ts tests/vault-private.spec.ts --grep 'display expires|live membership' --workers=1
uv run --project services/api python scripts/test_web_auth.py --vault
uv run --project services/api ruff check scripts/test_web_auth.py
pnpm typecheck
python3 scripts/validate_docs.py
```

암호 벡터 8 + workflow/lifetime 10 + 실제 React 입력 화면 12 = **30개 통과** 후
30초 표시 종료·실시간 권한 철회 UI 4개를 추가해 **4개 통과**했다. 합계 34개를 실행했다.
첫 UI 실행의 재시도 fixture가 저장 대신 wrapping 조회에 오류를 주던 2개 실패는 fixture를 바로잡은
뒤 해당 2개와 전체 30개를 다시 통과했다. 실제 제품 오류로 숨기지 않는다.

실제 production build + HTTPS + PostgreSQL 전체 시나리오도 통과했다. HTTP route mock은 없다.
처음 명령은 새 worktree의 개발 env 부재로 시작하지 못했고 전용 setup 후 다시 실행했다.

- 두 계정과 일반/종료 카드를 만들고 초기화·실제 브라우저 암호화 저장·복호화 표시를 확인했다.
- 일반 가계 가입만으로 암호문 접근은 403이며 공유 수락 후 배우자가 같은 카드를 복호화했다.
- 배우자 암호 변경, 최근 인증을 실제 만료시킨 뒤 같은 화면의 재인증과 복구코드 교체를 확인했다.
- 교체 준비 전 화면 종료 후 재개, 두 구성원/종료 카드 포함 전체 전환, 중단 후 다음 버전 예약,
  구성원 철회 후 403과 남은 구성원의 키 재교체를 확인했다.
- 카드 비밀 폐기 후 해당 카드만 has_secret=false/원본404, 다른 종료 카드의 비밀 보존을 대조했다.
- vault/cards 요청 본문에 합성 PAN/보관함 암호가 없고 no-store, localStorage/sessionStorage/cache 미사용을 확인했다.

독립 보안 코드 검토에서 복구코드가 idle 60초를 따르던 문제를 발견해 고정 30초 표시로 수정했다.
만료 시 확인 대기 closure·키·입력·표시를 폐기하고, 정상 확인 뒤 표시 deadline을 종료해
긴 후속 교체 작업을 허용한다. 회귀 추가 후 workflow12 + React18 = **30개 전체 통과**했다.
암호 벡터8을 합친 현재 고유 검증은 **38개**다. 위 실제 HTTPS 성공은 이 30초 보강 전의 결과이며,
보강 뒤 HTTP 계약은 같고 정상 확인/만료/긴 후속 단계는 브라우저 회귀로 다시 확인했다.

전용 DB·서버·임시 인증서/설정/스키마는 정리했다. 빌드 151모듈/JS863.47KB 성공이며 단일 chunk 크기 경고는 남는다.
모의 브라우저 크기 검증을 Android 네이티브/실기기 검증으로 표현하지 않는다.
실제 Galaxy 인수와 운영 배포/복원·정식 APK 검증은 별도 수행한다.

첫 PR 검토 뒤 Android 네이티브 구현과 화면 진입점이 함께 있는 `def1c228`을 통합했다.
네이티브 메타데이터 오류는 생성 `ErrorResponse`의 허용된 코드와 HTTP 상태를 보존한다.
누락/오래된 교체·최근 인증 필요·알 수 없는 오류의 세 reader 회귀를 추가했으며,
`pnpm --filter @sallimbook/client exec playwright test tests/vault-native-bridge.spec.ts --workers=2`의
**36개**와 typecheck·문서 검증을 통과했다. 오류 원문은 노출하지 않고 웹 요청이나 자동 재시도를 하지 않는다.

두 번째 PR 검토에서 모든 자리가 0인 PAN의 Luhn 합계가 0이어서 웹에서 허용되던
경계를 확인했다. Android와 동일하게 최소 한 자리의 0이 아닌 숫자를 요구하며,
13~19자리 각각의 입력·암호화·복호화 거절을 검증했다. 공개 교차 플랫폼 벡터를
포함한 `vault-crypto.spec.ts` **10개**가 desktop/android-size에서 통과했다.

기본 전체 브라우저 설정으로 실행할 때에도 비밀 작업의 trace·screenshot·video를 남기지 않도록
암호 벡터·workflow·private UI 시험 파일에 비활성화를 명시했다. private UI와 workflow
**30개**를 workers=2로 다시 통과했다. 합성 데이터 시험도 같은 기록 경계를 사용한다.
