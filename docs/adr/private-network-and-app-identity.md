# ADR 0007 — WSL 격리 운영과 사설망·앱 식별자

상태: 사용자 승인, 구현·운영 검증 진행 중 · 날짜: 2026-10-17

## 결정

Android 최소 지원은 API 30, 운영 applicationId는 `io.github.jihoon22lee.sallimbook`이다.
개발 빌드는 `.debug` 접미사를 사용하고 운영 서명과 분리한다.
검증 대상은 Galaxy S25 Ultra와 Galaxy S24 Ultra(Android 16)다.
S25 Ultra의 OS 버전은 실기기 연결 후 확인하며 추정값을 검증 결과에 쓰지 않는다.

사용자는 현재 PC의 WSL을 운영 서버로 선택했다. 기존 서버·컨테이너·DB·Tailscale 설정을 변경하지 않는다.
SallimBook의 프로세스, Compose 프로젝트, 네트워크, 볼륨과 비밀 경로를 별도로 만든다.
개발 기본 포트는 API 18741, Vite 18742, 웹 시험 18743이다. 사용 중이면 자동 종료·대체하지 않고 실패한다.
운영·테스트 DB도 기존 DB를 재사용하지 않는다. PC 종료·WSL 중단 시 서비스가 중단되는 운영 제약을 기록한다.

앱·API는 기존 tailnet에 가입할 **SallimBook 전용 노드**의 HTTPS로 접근한다. 기본은 사설 접속이며,
2026-10-24 사용자 결정으로 배포 manifest에서 명시적으로 선택한 8443 Funnel 공개 모드도 지원한다.
호스트의 기존 tailscaled/Serve/Funnel 설정은 조회만 하고 재설정하지 않는다.
전용 노드 내부의 앱 8443과 인증 파일 443을 분리하며, 443 공개 서비스는
`/.well-known/assetlinks.json`만 200 JSON으로 제공하고 나머지는 404로 처리한다.
공개 정적 서비스에는 API upstream, DB·첨부·비밀 volume을 연결하지 않는다.
노드 등록은 기존 인증정보를 다른 프로젝트에서 복사하지 않고 해당 노드용 인증 절차로 진행한다.

## 2026-10-24 — 앱 8443 공개 선택 (R-02, R-21, #45)

휴대폰·태블릿에서 VPN 연결 없이 접근할 수 있도록 `app_funnel_enabled: true`를 명시하면
전용 노드의 기존 8443 listener를 Funnel에도 제공한다. 생략/false는 기존 사설 동작이다.
이 선택은 **SallimBook 노드에만** 적용하며 호스트의 PointBook 443·FamilyCare 8443 경로와
호스트 포트를 건드리지 않는다. Compose에 `ports`나 host networking을 추가하지 않는다.

공개 모드에는 `setup_identity_sha256`을 함께 지정할 수 없다. 기존 가계의 로그인과
최근 인증된 구성원이 발급한 배우자 연결/초대만 사용한다. 사용자 식별 헤더를 위조해도
신규 가계 생성 권한이 생기지 않는다. 서버 인증·가계 권한·CSRF·재인증·시도 제한을 유지한다.
웹 화면과 APK 다운로드는 공개되지만 가계 데이터·문서·내보내기는 인증된 API로만 접근한다.
RP ID·HTTPS origin·APK 서명·앱 ID는 그대로이므로 같은 origin을 사용하는 기존 앱도 접속할 수 있다.

공개 변경은 렌더·preflight·새 운영 자동화 설정까지 함께 반영한다. CVD 갱신에서도 선택을 보존하며,
운영 API 이미지의 백업 도구가 이 manifest 필드를 인식하는 버전을 사용한다. 실제 인터넷 경로의
미인증 거부·위조 헤더·443 경로 제한과 다른 노드 설정 보존을 검증한다. 사설로 되돌릴 때도
새 렌더/자동화 설정으로 전환하며 호스트의 `tailscale serve/funnel reset`을 사용하지 않는다.

## 인증과 선행 준비

RP ID는 실제 서비스 FQDN(포트 제외), 웹/API origin은 같은 호스트의 HTTPS 8443이다.
Android 패스키 검증 파일에는 앱 ID와 서명 인증서 지문만 포함한다.
개발용 호스트·서명 지문은 운영과 분리하며, SB-006 전에 테스트 환경의 연동을 검증한다.
SB-036/038의 운영·업데이트 인수는 M8에서 수행한다. 선행 작업 그래프에 역방향 의존성을 추가하지 않는다.

## 검증

기존 서비스의 이름·포트·실행 상태 보존, 전용 노드의 허용 기기 접근, 비허용 기기 차단,
외부에서 정적 파일 이외 접근 실패, 실제 Android·PC의 패스키 등록·로그인, 복원 후 RP ID 연속성을 확인한다.
이 문서는 위 동작을 이미 검증했다는 보고가 아니다.

- [Credential Manager 사전 조건](https://developer.android.com/identity/credential-manager/prerequisites?hl=en)
- [Tailscale Serve와 포트 제한](https://tailscale.com/docs/features/tailscale-serve)
- [WebAuthn RP ID](https://developer.mozilla.org/en-US/docs/Web/API/PublicKeyCredentialCreationOptions#rp)
