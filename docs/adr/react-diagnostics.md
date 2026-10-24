# ADR · React 진단 규칙과 컴파일러 도입 범위

상태: 채택 · 날짜: 2026-10-24 · Issue #117 · R-02/R-19/R-22.

React Compiler 변환은 이번 변경에서 도입하지 않는다. 기존 React/Vite/ESLint 버전과
lockfile을 유지하고 `eslint-plugin-react-hooks`의 진단 규칙 12개를 error로 활성화한다.
[공식 ESLint 안내](https://react.dev/reference/eslint-plugin-react-hooks)는 컴파일러를
설치하지 않아도 이 진단을 사용할 수 있다고 설명한다. 따라서 컴파일러 미사용을 이유로
14개 규칙을 모두 끄던 설정을 수정한다.

컴파일러는 수동 메모이제이션을 줄일 수 있지만, 현재 성능 저하를 입증한 프로파일은 없다.
요청 세대, 월 버전, 재시도 멱등 키와 보관함 비밀의 수명에 의존하는 코드가 있으므로
빌드 변환까지 동시에 바꾸지 않는다. 향후 도입은 [공식 점진 도입 절차](https://react.dev/learn/react-compiler/incremental-adoption)에 따라
공개 metadata 화면부터 측정하고, 전후 요청 횟수와 보안 수명주기를 대조한다.

## 활성화한 규칙과 수정

`config`, `error-boundaries`, `gating`, `globals`, `immutability`, `incompatible-library`,
`purity`, `refs`, `set-state-in-render`, `static-components`, `unsupported-syntax`,
`use-memo`를 error로 적용한다. 기존 `rules-of-hooks`, `exhaustive-deps`도 error를 유지한다.

- 월 작업의 멱등 키는 fingerprint에 대응하는 상태로 관리한다. 같은 입력의 모호한 재시도는
  같은 키를 쓰고, 입력이나 버전이 바뀌면 새 키를 사용한다.
- 완료 안내는 도착한 history entry에 대응하는 상태로 유지한다. router state를 제거한 뒤에도
  현재 화면의 안내는 남고, 새로고침·뒤로가기에서 과거 안내를 다시 만들지 않는다.
- 페이지·스크롤 복원의 최신 위치 ref와 보관함 콜백 ref는 commit 이후 layout effect에서 갱신한다.
- 미저장 안내 문구, JPEG 변환 안내, 보관함의 재시도 버튼은 공개 화면 상태를 읽는다.
  미저장 입력의 동기 검사와 저장 직후 이동 허용은 기존 ref registry로 처리한다.

`VaultActionLauncher`의 render prop에 전달하는 이벤트 콜백에는 한 줄 예외를 둔다.
실제 호출자 `VaultPage`와 `CardVaultActions`는 모두 버튼 이벤트에서만 이 콜백을 실행한다.
렌더링 중 비밀/flight ref를 읽는 것을 허용하는 일반 예외가 아니다. 사용처가 늘어날 때 이
계약을 검토해야 하며, 나머지 앱에는 `refs` 규칙을 계속 적용한다.

## 별도로 유지한 두 규칙

`set-state-in-effect`는 현재 error로 켜지 않는다. 초기/범위 변경 조회의 loading·오류 초기화,
인증 상태 복원, 편집 대상 전환에서 동기 상태 갱신을 사용한다. 이를 타이머나 microtask로
옮겨 진단만 피하지 않는다. 범위 변경 시 이전 가계/항목이 잠깐 표시되지 않는지, 취소된
요청이 뒤늦게 새 화면을 덮지 않는지까지 검증하는 별도 query 상태 설계가 선행되어야 한다.

`preserve-manual-memoization`도 현재 error로 켜지 않는다. 진단은 `useMounted()`가 반환한
수명 ref의 `mounted.current`를 메모이제이션 의존성으로 추론하는 지점이다. 실제 의도는
이벤트/비동기 완료 시 최신 mounted 값을 읽는 것이다. `.current`를 dependency 배열에
추가하거나 취소·수명 확인을 삭제하지 않는다. 컴파일러 도입 시 해당 custom hook의 인식과
메모이제이션 경계를 별도로 검증한다. 이 결정은 컴파일러 적용 시점의 재검토 대상이다.

## 보안 검토와 검증 범위

이번 보관함 수정은 `canRetry` boolean과 최신 콜백 전달만 바꾼다. 암호·복구코드·PAN·키·
workflow 객체는 React state로 옮기지 않는다. 시작/잠금 시 boolean을 false로 초기화하고,
동작 종료 시 현재 workflow이고 수명이 유효한 경우에만 갱신한다. 실제 재시도는 기존
workflow와 lifetime 검사, flight 차단을 그대로 통과해야 한다. 화면 상태는 권한 증명이 아니다.

소스 검토에서는 재시도 준비·폐기, blur 잠금, 재인증 성공/실패, 늦은 완료 응답과 unmount를
대조했다. 별도 검증 단계에서 전체 Playwright, 네이티브 adapter 모의 시험, 실제 HTTPS
계좌·월 기록·첨부·보관함 흐름을 실행한다. HTTPS 월 기록은 첫 작성/확정 POST 각각 1회와
금액 PATCH 2회를 확인하고, 브라우저 시험은 모호한 저장의 동일 암호문·동일 멱등 키 재시도를
검증한다. 명령과 결과는 PR에 기록한다. 실제 Android 기기의 인증·캡처·백업 보호 시험을
이 웹 변경의 증거로 대체하지 않는다.
