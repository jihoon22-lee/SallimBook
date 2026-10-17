# ADR · 클라이언트 구현 도구와 검증 기준

상태: 구현과 문서 정합성 기록 · 날짜: 2026-10-18 · SB-003/SB-034/SB-040, R-02/R-19/R-22.

초기 스택 표에는 Tailwind CSS, shadcn/ui, TanStack Query, React Hook Form, Zod, Recharts,
Vitest가 선정 후보로 기재되어 있었다. 현재 `apps/client/package.json`과 pnpm lockfile에는
이 패키지들이 설치되어 있지 않다. 이미 구현한 feature와 검증을 실제 manifest에 맞게 문서화한다.

공통 CSS와 semantic HTML, React hooks로 화면·폼을 구성한다. 일반 데이터는 공통 resource/list
hook과 인증 adapter로 읽고, 작업 취소·현재 요청 세대·버전·멱등 키를 명시적으로 다룬다.
서버가 계산과 권한의 최종 기준이며 TypeScript 계약은 OpenAPI에서 생성한다. 입력 보조 함수는
독립 API 계약으로 유지하지 않고 서버 fixture와 대조한다.

금액 추이는 SVG와 같은 값의 표를 함께 제공한다. 차트 좌표용 비율과 서버의 원 단위 문자열을
구분하며 합계 계산을 부동소수점으로 대체하지 않는다. 웹 모델·폼·수명주기는 Playwright의
실제 브라우저에서 검증하고 서버 Python/Android Kotlin의 공통 벡터와 비교한다.

비밀 입력·키·PAN·복구코드·파일 원문에는 일반 화면 상태나 영구 캐시를 적용하지 않는다.
Android는 네이티브 보호 화면을 사용하며, 웹은 수명이 제한된 별도 작업 소유자와 DOM을 사용한다.
구현 도구 선택은 7개 영역, 26개 화면, 접근성, 실제 기기와 운영 인수 조건을 줄이지 않는다.

반복 코드가 실제 유지보수 문제를 만드는 경우 후속 변경에서 라이브러리 도입을 검토하되,
공식 호환성·lockfile·기존 동작과 비밀 경계의 회귀 검증을 같은 변경에서 수행한다.
