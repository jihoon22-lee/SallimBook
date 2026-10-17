# 사용자 내보내기 화면 검증

대상: SB-037, R-20. [서버 계약](../api-contract.md#sb-037-사용자-내보내기감사-조회-구현-계약-r20)의
`POST /api/v1/exports`에 웹·Android 화면을 연결한다. 운영 백업이나 새 서버 복원 완료를 뜻하지 않는다.

## 사용자 동작과 제외 범위

설정의 자료 내보내기에서 JSON·CSV 형식과 문서 원본을 선택한다. 기본값은 두 데이터 형식과
문서 원본 제외다. 현재 가계의 모든 기간 업무 기록·정정 이력·문서 metadata/연결을 포함하며,
화면에서 선택한 월이나 현재 불러온 목록 페이지로 범위를 제한하지 않는다.

문서 원본은 목록의 다음 페이지를 이어 선택할 수 있다. ready 상태와 활성 연결이 있는
문서만 가능하며 10개/40MiB 합계 제한을 먼저 확인한다. 현재 연결을 잃은 문서는 선택 상태를
새로 확인할 때 제외하고 사용자 확인을 다시 받는다. 발급 전의 최종 상태·권한 검증은 서버가 한다.

화면에서 보관함·카드 비밀·CVC·암호문·전체 계좌/증권번호·인증 비밀이 제외됨을 설명한다.
진료 기록·사용자 메모와 선택 원본 안의 내용은 자동 비식별화하지 않는다고 알린다.
ZIP은 암호화 보관함 파일이 아니며 기기 저장본은 앱 잠금·로그아웃·서버 삭제로 회수하거나
만료시킬 수 없다. 이 안내 확인 없이는 내보내기를 시작하지 않는다.

CSV의 문자열에는 금액까지 `text:` 접두사가 있고 null과 빈 문자열은 각각 `\N`, `text:`로
구분됨을 안내한다. 원래 값의 교환에는 JSON을 권장하며 UI에서 금액을 다시 계산하지 않는다.

## 웹 다운로드 경계

- 생성 API client의 POST를 기존 `domainApi.write`로 호출한다. CSRF와 계정 세션은 인증 계층
  안에서 처리하며 화면에 토큰을 반환하지 않는다. 최근 5분 인증 또는 현재 household를 target으로
  하는 `data.export` 패스키 증명을 사용한다. 증명은 이 작업에만 사용한다.
- 매 POST가 새로운 export ID/스냅샷을 발급하므로 멱등키·작업 polling·재사용 다운로드 URL을
  새로 만들지 않는다. 네트워크/408/413/409/503·취소를 자동 재전송하지 않는다. 인증 계층의
  핸들러 실행 전 CSRF 거절에 대한 1회 갱신은 기존 정책을 따른다.
- 응답은 streaming으로 읽고 성공 상태·ZIP MIME·고정 ID 기반 파일명·no-store·nosniff·UUID·
  SHA-256·Content-Length를 검사한다. 64MiB 이하의 크기만 할당하고 더 길거나 짧은 본문을
  거부한다. 최소 ZIP 서명과 전체 SHA-256을 확인한 뒤에만 Blob URL을 만든다.
- bytes는 명령의 지역 변수 안에만 두며 React state·localStorage·sessionStorage·Cache API에
  저장하지 않는다. 인증 세대가 바뀐 뒤 도착한 결과도 지운다. 수신 chunk와 소유 buffer는
  실패·취소·완료 시 가능한 범위에서 덮어쓴다. 런타임 내부 사본 완전 삭제를 주장하지 않는다.
- 저장은 한 번의 anchor 클릭으로 요청하고 anchor와 object URL을 즉시 제거한다. ZIP을 HTML에
  표시하거나 iframe/새 창에서 열지 않는다. 브라우저 저장 성공을 확인할 수 없으므로 저장 요청과
  실제 로컬 저장 완료를 구분해서 안내한다.
- 요청 중복 진입을 막으며 취소·pagehide·화면 해제 시 AbortSignal로 중단한다. 준비·전송 전체
  대기는 150초 상한이다. 실패 후에는 안내 확인을 다시 받아 새 시점의 자료를 요청한다.

## Android 연결

`nativeExports.export({input: {formats, document_ids}})`에서 생성 스키마의 선택 metadata만
`exportArchiveUI`로 전달한다. 네이티브 구현은 인증·ZIP 검증·SAF 저장을 담당하고 JS에
`{status: 'exported'|'cancelled'}`만 반환한다. URI·파일 경로·Blob·원본 bytes·다운로드 URL·
CSRF/세션/인증 증명은 bridge에 전달하지 않는다. 기능 미지원·실패 시 웹 HTTP로 우회하지 않는다.
네이티브 구현·JVM/실기기 결과는 담당 Android 검증 기록을 별도로 확인한다.

## 실행 기록

```bash
pnpm api:generate
pnpm typecheck
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts tests/exports-ui.spec.ts tests/exports-native-ui.spec.ts tests/exports-download.spec.ts --workers=1
pnpm build
uv run --project services/api ruff check scripts/test_web_auth.py
uv run --project services/api python scripts/test_web_auth.py --exports
python3 scripts/validate_docs.py
git diff --check
```

모의 화면 시험은 전용 18756 포트를 사용한다. 신규 76개(웹 48, Android UI 16, bounded stream 12)가
PC/Android 화면 크기에서 통과했다. JSON/CSV·문서 선택과 한도, 상태 변경, 재인증·가계 범위 증명,
CSRF 갱신, 실패·취소·pagehide·401, 파일 응답의 크기/헤더/해시·buffer 정리·URL 해제를 확인했다.
실제 WebAuthn 서명 검증은 이 모의 시험 범위가 아니다.

추가한 설정 진입·비로그인 시험 2개는 링크의 설명까지 포함한 접근성 이름과 exact locator가
일치하지 않아 처음 실패했다. locator를 실제 링크 이름에 맞게 보정한 뒤 2개 모두 통과했다.
기능 코드는 이 locator 수정으로 바뀌지 않았다.

생성 계약 재생성 결과 변경 없음. 타입 검사와 배포용 빌드 통과(158개 모듈,
주 JS 876.68kB/gzip 226.70kB). 기존 500kB 초과 chunk 경고는 남는다.

실제 HTTPS 시험 2회는 합성 PNG 업로드의 보관 완료 확인에서 실패했다. 내보내기 API의 성공 여부는 아직 검증하지 못했으며 원인을 확인 중이다. 기존 document runtime의 실제 고정
ClamAV/parser/OCR를 사용하고 합성 PNG 원본을 검사해 첨부한다. 별도 합성 가계는 일회용 schema에만
준비한다. 임시 TLS·필드 키·문서 저장소·계정 fixture·브라우저 산출물은 전용 private 디렉터리에
두고 종료 시 제거한다. 실패 출력은 코드 위치와 비밀 없는 단계 표지만 남긴다.

[보안 정책](../security-authentication.md) · [운영 백업과 사용자 내보내기](../deployment-backup-operations.md)
