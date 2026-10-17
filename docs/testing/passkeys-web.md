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

2026-10-18 Asia/Seoul 기준, 서버 기기 폐기 경합 수정과 동일 세션 비밀번호 재인증을 병합한 결과:

| 검사 | 결과 |
|---|---|
| `pnpm --filter @sallimbook/client exec playwright test --config playwright.passkeys.config.ts --workers=2` | 최신 서버 병합 후 전체 UI **120개 통과** |
| `uv run --project services/api python scripts/test_web_auth.py --passkeys` | 실제 HTTPS WebAuthn **2개 통과** |
| `uv run --project services/api python scripts/test_web_auth.py` | 실제 HTTPS 쿠키·CSRF·동일 세션 비밀번호 재인증 **2개 통과** |
| 최종 서버 `b097ace`의 `uv run --project services/api python scripts/test_database.py` | API·권한·검증 **242개 통과**, Alembic drift 없음, downgrade/upgrade 성공 |
| `pnpm api:generate`, `pnpm typecheck` | 통합 서버에서 API 계약 재생성·타입 검사 통과 |
| `pnpm android:build` 및 `:app:compileReleaseKotlin` | JVM **48개 통과**(인증 29·기존 debug POC 19), 개발 APK·release Kotlin 컴파일 성공 |

최종 병합 후 HTTPS 두 명령도 각각 2개씩 다시 통과했다. 초기 병행 UI 실행은 라우팅 reload 1건에서
5초 timeout이 있었고, 같은 코드의 해당 테스트 단독 실행과 최종 2-worker 전체 실행은 통과했다.
CI에서는 일반 HTTPS 인증에 더해 `--passkeys`의 실제 서명 검증도 실행한다.

WebAuthn 검사는 등록·로그인·공개 목록·폐기와 폐기 키 재로그인 거부를 확인했다. 초대·기기 해제용 scoped
grant를 실제로 소비한 뒤에도 패스키 등록·폐기에 필요한 계정 인증 시각이 갱신되지 않음을 확인했다.
기기 폐기 검사는 별도 브라우저에서 실제 활성 기기를 만들고 서버 목록의 연결 해제 상태를 기다려 판정한다.
대기 중인 실제 가상 인증기를 취소할 때 등록 검증 요청이 전송되지 않음도 확인했다.

모든 DB 실행 뒤 전용 테스트 서비스 중지와 임시 스키마 정리를 완료했다. API 검사에 Starlette의 httpx
폐기 예정 경고 1개가 있었으며 실패·건너뜀은 없었다. Galaxy 실기기 시험은 전체 기능 개발 이후에 수행하며
현재 미실행이다. 이 결과는 운영 RP·인증서·DAL 배포나 실제 생체 인증·보관함 보안 게이트의 완료가 아니다.

## 표준 근거

- [W3C WebAuthn](https://w3c.github.io/webauthn/)
- [브라우저 등록 옵션 JSON 변환](https://developer.mozilla.org/en-US/docs/Web/API/PublicKeyCredential/parseCreationOptionsFromJSON_static)
- [브라우저 인증 옵션 JSON 변환](https://developer.mozilla.org/en-US/docs/Web/API/PublicKeyCredential/parseRequestOptionsFromJSON_static)

Android는 `401 PASSKEY_VERIFICATION_FAILED` 시 기존 로그인 세션을 유지하고 패스키 실패를 알린다. 실제 세션 만료 401은 로컬 세션을 제거한다. 두 경로를 같은 native 실패 처리 helper로 회귀 검증했다.
