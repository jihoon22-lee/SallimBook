# SB-006 웹 패스키 검증

웹은 서버가 발급한 WebAuthn JSON 옵션을 브라우저의 표준 변환 API에 전달한다.
`navigator.credentials.create/get`이 반환한 바이너리만 canonical unpadded base64url로 인코딩하며,
생성 API 타입에 정의된 필드만 서버에 보낸다. 확장 결과는 `credProps.rk`로 제한하고 PRF 출력은 전달하지 않는다.
브라우저 확인이 끝나도 서버 검증을 통과하기 전에는 등록·로그인 성공으로 표시하지 않는다.

등록·패스키 해제에는 5분 이내의 실제 계정 로그인이 필요하다. 초대와 기기 해제의 패스키 버튼은 목적과
대상에 묶인 인증을 새로 수행한다. 발급된 grant는 같은 함수 호출 안에서 해당 요청에만 사용하고,
React state·URL·브라우저 저장소에 넣거나 세션의 최근 인증 시각으로 해석하지 않는다.
로그인된 화면에서는 새 기기·세션을 만드는 패스키 로그인 버튼을 숨긴다. 기존 세션의 최근 로그인 확인은
별도 비밀번호 재인증 경로를 사용하며 기존 세션과 기기를 유지한다. 목적별 grant로 등록·폐기 권한을 넓히지 않는다.
단계별 요청은 AbortSignal로 연결되며 페이지 이탈·숨김·명시적 취소 시 브라우저 인증과 후속 요청을 중단한다.

Android 버튼은 별도 네이티브 플러그인의 UI를 연다. JS로 전달되는 값은 완료·취소 상태와 공개 기기·패스키
메타데이터뿐이며 challenge·서명·device binding·grant·비밀번호·세션 토큰은 전달하지 않는다.
이 문서는 Credential Manager·Keystore·실기기 보안을 검증한 문서가 아니다.

## 실행

```bash
pnpm install --frozen-lockfile
uv sync --project services/api --frozen
pnpm --filter @sallimbook/client exec playwright test --config playwright.passkeys.config.ts
uv run --project services/api python scripts/test_web_auth.py --passkeys
```

UI 검사는 별도 18747 포트를 사용한다. 합성 API 응답과 실패·취소만 모의하며 실제 서명 검증의 근거로 삼지 않는다.

실제 WebAuthn 검사는 [HTTPS 인증 harness](browser-authentication.md)의 전용 테스트 DB·전역 잠금·임시 스키마를
재사용한다. 임시 TLS 인증서와 `sallimbook-passkey.test` RP를 만들고 해당 Chromium 프로세스에서만
127.0.0.1로 해석한다. 시스템 DNS·hosts·신뢰 저장소와 운영 설정은 바꾸지 않는다. 운영 RP 설정은 계속 미지정이다.
Chromium 가상 인증기가 실제 서명을 만들고 API가 실제 PostgreSQL 상태와 공개키로 검증한다. 개인키를 추출하거나
서명을 가짜 성공으로 바꾸지 않는다. 테스트의 계정 인증 시각 조정은 임시 앱·임시 스키마에만 설치되는 비공개
제어 경로에서 수행하며 운영 API에는 해당 경로가 없다.

모든 자격증명과 테스트 제어 값은 임의 생성한 합성 데이터다. trace·스크린샷·영상은 끄고 실행 출력과 실패
산출물은 owner 전용 임시 디렉터리에서 폐기한다. 실패 보고에는 테스트 코드 위치만 남긴다.
이 검증은 공개 배포 TLS 체인·실제 사용자 인증기·Digital Asset Links·Android 서명을 대신하지 않는다.

## 결과

2026-10-18 Asia/Seoul 기준 결과:

- 전체 Playwright UI 검사 **106개 통과**. 이후 숨김·늦은 옵션 응답·네이티브 세션 만료 6개를 추가한 관련 검사 **62개 통과**.
- 실제 HTTPS WebAuthn 검사 **2개 통과**: 등록·로그인·공개 목록·폐기, 폐기 키 재로그인 거부,
  초대·기기 해제용 scoped grant의 실제 소비와 계정 인증 시각 비갱신, 실제 대기 중인 인증의 취소.
- TypeScript 검사와 Vite 빌드 통과. 전용 테스트 DB 서비스 중지와 임시 스키마 정리 완료.
- 테스트 중 발견한 fixture 문제는 이미 로그아웃으로 폐기된 기기를 대상으로 선택한 점과,
  확인 버튼 표시 전환을 실제 서버 폐기 완료로 오인한 점이었다. 별도 활성 기기를 만들고 서버 목록의
  연결 해제 상태를 기다리도록 수정했다. 제품 성공을 모의 응답으로 대체하지 않았다.
- Galaxy 실기기 시험은 전체 기능 개발 이후에 수행하며 현재 미실행이다.

## 표준 근거

- [W3C WebAuthn](https://w3c.github.io/webauthn/)
- [브라우저 등록 옵션 JSON 변환](https://developer.mozilla.org/en-US/docs/Web/API/PublicKeyCredential/parseCreationOptionsFromJSON_static)
- [브라우저 인증 옵션 JSON 변환](https://developer.mozilla.org/en-US/docs/Web/API/PublicKeyCredential/parseRequestOptionsFromJSON_static)
