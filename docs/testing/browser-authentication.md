# 브라우저 인증 검증

`apps/client/tests/auth.spec.ts`와 `auth-native.spec.ts`는 합성 응답·Capacitor 모의 플러그인으로
UI 분기, 취소, 기기 목록 충돌과 로그아웃 안내를 검사한다. 서버 권한·쿠키·Android 암호화를 증명하지 않는다.

실제 HTTPS 브라우저와 FastAPI/PostgreSQL을 연결하는 검증은 별도로 실행한다.

```bash
uv run --project services/api python scripts/test_web_auth.py
```

사전 조건은 개발 환경의 `.env`, 고정 의존성 설치, Chromium 설치, Docker 접근과 `openssl`이다.
스크립트는 기존 DB 테스트와 동일한 전역 잠금을 사용한다. 다른 DB 테스트가 진행 중이거나 전용 테스트 DB가
이미 실행 중이면 중단한다. `sallimbook-dev`의 `db-test` 서비스와 18745 포트만 사용하며,
매 실행마다 임의의 `sallimbook_test_*` 스키마에 마이그레이션과 합성 계정을 생성한다.
종료 시 스키마를 삭제하고 해당 테스트 서비스만 중지한다. 개발 DB·기존 서버·Tailscale은 변경하지 않는다.

Vite 빌드 결과를 실제 API와 같은 임시 loopback HTTPS origin에서 제공한다. 임시 인증서의 공개키 지문만
해당 Chromium 프로세스에 신뢰하도록 지정하며, 시스템 신뢰 저장소·운영 인증서 검증은 변경하지 않는다.
이 검사는 운영 인증서 체인·공개 호스팅·프록시 배포를 검증하지 않는다.

검사 범위:

- UI 로그인 → 실제 `HttpOnly; Secure; SameSite=Strict` 세션 쿠키 → 새로고침 후 세션 복원
- JS에서 세션 쿠키 읽기 불가, 브라우저 저장소에 인증 정보 미보관
- 다른 사이트(`localhost` → `127.0.0.1`)의 iframe 요청에 세션 쿠키 미전송·401 응답
- UI 로그아웃 후 쿠키 제거와 실제 `/me`의 401 응답
- 비밀번호 재확인 후 같은 세션 쿠키와 단일 등록 기기 유지
- CSRF 토큰 누락·이전 토큰 거부, 새 토큰으로 로그아웃 성공, 재전송 시 401

응답 가로채기나 HTTP mock은 사용하지 않는다. 비밀번호는 매 실행 임의 생성하며 owner 전용 임시 파일로
테스트에 전달한다. trace·스크린샷·영상은 끄고, Playwright 출력과 실패 산출물은 외부에 노출하지 않고
임시 디렉터리와 함께 폐기한다. 실패 시 일반 오류만 출력하므로 원인을 조사할 때도 토큰·비밀번호·폼
원문을 로그에 추가하지 않는다. 실제 사용자 데이터는 사용하지 않는다.

2026-10-17 실행 결과: **실제 HTTPS 검사 2개 통과**, `ruff check` 통과, 포함된 TypeScript 검사와 Vite 빌드 통과.
종료 시 테스트 스키마 삭제·전용 테스트 서비스 중지가 완료되었다. 교차 사이트 요청은 합성 외부 페이지에서
iframe을 생성해 확인하며, 실제 앱의 `frame-src 'none'` CSP는 유지한다.
Android 네이티브 보안과 Galaxy 실기기 시험은 이 검증에 포함하지 않는다.
