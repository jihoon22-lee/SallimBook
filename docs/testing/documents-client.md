# 첨부 문서 화면 검증

대상: SB-023, Issue #32, R-13/R-15/R-20. 생성 API 계약의 9개 문서 operation을
보험·사건·진료·의료비·청구·가전·자산 상세에 연결한다. 카드 첨부 대상은 없다.

## 동작과 보안 경계

- 권한 확인을 마친 부모의 상세에서 첨부 패널을 열면 현재 대상 문서를 조회한다.
  공동 가계의 기존 문서·업로드 대기·연결 없는 문서는 별도 목록에서 찾고 명시적으로 연결한다.
  목록/연결 이력은 cursor 페이지를 이어 읽는다. 연결 종료는 원본을 삭제하지 않고 이력을 남긴다.
  문서 삭제는 사유와 모든 연결 대상에 대한 확인을 받아 수행한다.
- 웹 업로드는 실제 File 크기 1바이트~20MiB, 이름 255문자, 경로/제어/방향 제어 문자,
  MIME과 PDF/JPEG/PNG 확장자 일치를 확인한다. 카드 정보 없는 문서라는 확인 후 메모리에서
  SHA-256을 계산하고 metadata POST에 보낸다. 같은 bytes를 raw PUT으로 전송한다. JPEG는 해시 전에
  정규화한 사본을 사용한다(아래 JPEG 정규화 절).
  일반 React state에는 파일 bytes를 보관하지 않는다. input/ref는 화면 종료·pagehide·세션 해제 시
  비우고 보유 ArrayBuffer를 지운다. 브라우저/런타임 내부 사본까지 완전 삭제했다고 주장하지 않는다.
- metadata 응답 유실은 같은 생성 키로 재시도한다. 업로드 응답 유실은 현재 metadata를 조회해
  ready이면 완료로 처리하고, pending이면 같은 파일·키·버전으로 재시도한다. 대기 문서 재개는
  이름/형식/크기/SHA-256이 처음의 값과 일치해야 한다. 만료 pending은 새 업로드로 덮어쓰지 않는다.
- 연결 추가/종료/삭제도 버전과 멱등키를 유지한다. 409에서는 사유를 유지하고 현재 문서와
  모든 연결 이력을 비교한 뒤 사용자가 새 작업을 준비한다. 서버 최신 버전으로 조용히 덮어쓰지 않는다.
- 원본 저장은 별도 확인 후 인증된 GET으로 수행한다. 크기·SHA-256을 확인한 뒤 불투명 object URL을
  저장 클릭에만 사용하고 즉시 해제한다. inline PDF/image 미리보기, 공개 원본 URL, Service Worker,
  localStorage/sessionStorage/일반 데이터 캐시를 추가하지 않는다. 기기에 저장한 사본은 앱 잠금이나
  문서 삭제 뒤에도 남는다는 점을 저장 직전에 알린다.
- Android는 6개 typed JSON metadata 명령과 `uploadDocumentUI(target)`,
  `downloadDocumentUI(documentId)`를 사용한다. JS 파일 input·원본 bytes·picker URI·해시·비밀번호를
  bridge에 전달하지 않는다. 파일 선택·전송·저장은 기존 네이티브 보호 화면이 담당한다.
  앱 잠금/세션 소실은 입력 화면을 해제하고 네트워크 실패는 같은 작업 재시도를 유지한다.
- 408/413/422/503은 제한·안전 검사·보관 공간에 맞는 한국어 안내를 표시한다.
  응답의 임의 오류 message를 렌더링하지 않는다. 보관 한도/용량 부족은 실제 정리 완료 뒤 재시도한다.

## 재현 명령

```bash
pnpm api:generate
pnpm -r typecheck
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts tests/documents-ui.spec.ts tests/documents-native-ui.spec.ts tests/documents-model.spec.ts --workers=1
uv run --project services/api python scripts/test_web_auth.py --documents
uv run --project services/api ruff check scripts/test_document_runtime.py scripts/test_web_auth.py
python3 scripts/validate_docs.py
git diff --check
```

모의 화면 시험은 전용 18756 포트를 사용한다. 실제 HTTPS 검증은 전용 테스트 DB 잠금과
문서 도구 잠금을 잡으며 기존 서버·DB·키·신뢰 저장소를 변경하지 않는다.

## 실제 파일 검사 환경

`test_document_runtime.py`는 기존 [고정된 검사 도구 이미지](../../infra/documents/README.md)를
새로 빌드하거나 호스트에 도구를 설치하지 않고 임시 container로 실행한다. 네트워크 none,
읽기 전용 root, 모든 capability 제거, no-new-privileges, 4GiB 메모리와 같은 swap 상한,
CPU 2개, PID 64개, core dump 금지를 적용한다. ClamAV 임시 내용은 96MiB RAM tmpfs에만 있다.
호스트 UID/GID와 맞춘 0700 임시 디렉터리/0600 Unix socket만 연결하며 실제 사용자 파일·키를 mount하지 않는다.

생산 worker의 768MiB 주소 공간 한도에서 Go Docker CLI가 실행되지 않는 것을 확인했다.
생산 제한을 완화하지 않고 테스트 전용 private socket broker를 사용한다. broker는 고정된
Tesseract 언어 조회/OCR 및 Poppler 페이지 렌더 argv만 허용하며 입력/출력 최대 48,001,024바이트,
도구별 출력 상한, 8초 실행 제한을 둔다. 원본과 OCR 결과는 stdin/stdout으로만 이동하고 로그나
plaintext 파일에 남기지 않는다. API의 실제 ClamAV 검사와 제한 parser/OCR worker를 대체하거나 mock하지 않는다.
임시 자원은 브라우저 시작 전에 만들고 끝난 뒤 제거한다.

## 검증 결과와 한계

최종 웹 React 62개, native React 12개, 모델 2개로 **76개 전체가 통과**했다.
pending 재개·업로드 409·늦은 웹 취소·pagehide·웹 세션 소실·quota 안내까지 포함한다.
최초 확장 실행은 75개 통과/1개 실패였다. 중첩 pending 패널의 기본 파일 선택 칸이 모바일
화면보다 넓어져 체크박스 터치 위치가 어긋나는 실제 레이아웃 문제를 수정했다.
파일 선택 칸의 폭을 제한하고 긴 파일명 버튼을 줄바꿈한 뒤 PC/모바일 해당 경로 2개와
최종 76개 전체를 다시 통과했다. 가로 넘침 방지 assertion도 포함했다.
실제 production `validate_document`를 통과하는 PNG 1페이지 도구 probe가 성공했다.
최종 `--documents` 실제 HTTPS 전체 시나리오는 45ba714 서버 통합 후 통과했다.
첫 실행은 시험 setup의 의료비 API 경로를 고쳤고, 두 번째는 연속 업로드 때 이전 문서의
완료 표시를 선택한 시험 동기화를 고쳤다. 세 번째 전체 실행에서 아래 항목을 모두 확인했다.

- 실제 ClamAV + parser + OCR로 PNG 원본을 보관하고 다운로드 bytes/SHA-256/크기를 그대로 대조했다.
- 같은 문서를 7개 부모 UI에 연결하고, 가전 연결 종료/재연결 후 8개 연결 이력을 보존했다.
- 두 실제 브라우저 창의 버전 충돌에서 사유를 유지하고 최신 7개 연결/8개 이력을 명시적으로 비교했다.
- 실제 PDF의 구조 검사·Poppler 렌더·Tesseract OCR을 통과하고 원본 해시를 대조했다.
- 합성 카드 표식 PNG는 실제 검사에서 거절됐다. 원본은 저장되지 않고 pending metadata가 남아
  사용자가 사유를 입력해 삭제했다. 합성 이미지에도 실제 카드번호나 고객 정보는 쓰지 않았다.
- 문서 삭제로 모든 연결을 종료했고 이후 원본 GET은 409로 차단됐다. 원래 의료비 금액은 변하지 않았다.
- 인증 응답 no-store, 문서 변경 CSRF/멱등키, raw PUT 버전, 브라우저 저장소/캐시 미사용을 확인했다.

전용 DB는 정지했고 검사 container·broker·임시 키/인증서/스키마/산출물은 정리했다.
현재 branch 전체 652개 브라우저 시험은 이 작업에서 다시 실행하지 않았다.

서버 권한·검사 보안의 별도 근거는 [첨부 서버 검증](documents-server.md)을 따른다.
최신 0013의 영속 용량 예약 및 서버 150개 검사는 서버 작업에서 실행했다. 이 화면 시험을
서버 권한/암호화 또는 Android 실기기 실패 시나리오의 대체 근거로 사용하지 않는다.
Android 실기기 SAF/picker·앱 전환·프로세스 종료 검증과 운영 검사 도구 배포는 남아 있다.
최종 프로덕션 빌드(144모듈, JS 807.06KB)는 성공했으며 기존 단일 JS chunk 크기 경고가 남는다.
실제 HTTPS 전체 검증 후 변경한 것은 이 모바일 폭 제한과 안내/검증 문서이며, 파일/API 동작은 같다.


## PR #85 연결 이력 페이지 회귀 보완

SB-023 / Issue #32 / R-13·R-15·R-20의 [첫 검토 지적](https://github.com/jihoon22-lee/SallimBook/pull/85#discussion_r4305053013)을 보완했다.
당시 UUID 순서(WP08 이후 등록 최신순)로 읽는 연결 이력의 첫 50개가 종료 이력이고 현재 대상의 활성 연결이
51번째에 있으면, 기존 화면은 다음 페이지를 읽기 전에 새 연결을 허용했다.

현재는 이력 조회 중이거나 오류가 있거나 다음 cursor가 남으면 연결 버튼과 실행 경로를
함께 막는다. 기존 수동 더 보기 동작을 유지하며 남은 이력을 모두 확인하라는 안내를 표시한다.
모든 페이지를 확인한 뒤 현재 대상의 활성 연결이 없을 때만 새 연결을 허용한다.
조회 실패 후 명시적으로 다시 확인해도 첫 페이지 성공만으로 제한을 풀지 않는다.
API·생성 계약·DB·권한 정책·버전/멱등성 계약 변경은 없다.

신규 `documents-pagination.spec.ts`는 합성 종료 이력 50개와 마지막 활성 연결 1개를 사용한다.
웹 요청과 typed native bridge 각각에 대해 PC/Android 화면 크기에서 아래를 확인한다.

- 다음 페이지를 읽기 전과 응답 대기 중에는 연결이 비활성화된다.
- 51번째가 현재 대상의 활성 연결이면 전체 조회 후에도 중복 요청을 보내지 않는다.
- 51번째가 다른 대상이면 전체 조회 후 현재 대상에 정확히 한 번 연결한다.
- 두 번째 페이지 503 후 오류를 표시하고 제한을 유지한다. 다시 확인한 첫 페이지에서도
  제한을 유지하며 마지막 페이지까지 성공해야 연결 여부를 판단한다.
- native 경로는 일반 HTTP fallback을 사용하지 않으며 오류 원문은 표시하지 않는다.

재현 명령:

```bash
# 수정 전 ca67c5a의 DocumentDetail에 신규 시험을 적용하여 음성 대조
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts tests/documents-pagination.spec.ts --project desktop --grep 'web document history page two blocks duplicate$' --workers=1 --trace=off
# 수정 후 신규 및 기존 문서 회귀
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts tests/documents-pagination.spec.ts --workers=1 --trace=off
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts tests/documents-ui.spec.ts tests/documents-native-ui.spec.ts tests/documents-model.spec.ts tests/documents-pagination.spec.ts --workers=1 --trace=off
pnpm typecheck
pnpm build
python3 scripts/validate_docs.py
git diff --check
```

수정 전 음성 대조는 첫 50개 조회 뒤 `toBeDisabled()`에서 실제 enabled로 실패했다.
수정 후 신규 16개는 모두 통과했다(23.5초).
기존 76개와 신규 16개를 함께 실행한 최종 **92개 전체도 통과**했다(1.7분).
최초 타입 검사는 다른 worktree를 가리키던 공유 의존성 링크 때문에 실패했으며,
이 worktree에서 `pnpm install --offline --frozen-lockfile`로 기존 캐시만 사용해 설치한 뒤
최종 typecheck와 build가 통과했다. lockfile 변경과 패키지 다운로드는 없다.
빌드는 165모듈, JS 894.41KB/gzip 231.22KB이며 기존 500KB chunk 경고가 남는다.
문서/manifest 검사와 `git diff --check`도 통과했다. 시험 종료 후 전용 Vite 18756을 해제했다.
이 보완에서는 전체 앱 982개, 실제 HTTPS/API/DB, Android 실기기 검증을 다시 실행하지 않았다.
위 모의 화면 검증을 서버 권한이나 네이티브 저장·암호화의 검증으로 간주하지 않는다.


## JPEG 정규화와 검사 한도 안내 — 2026-10-20

휴대폰 카메라 JPEG의 EXIF 방향·위치 정보·제조사 꼬리 데이터 때문에 서버가 정상 사진을
거절하던 문제(H2)를 클라이언트에서 줄인다. 서버는 받은 bytes를 바꾸지 않는다.

- 웹은 크기 확인 뒤 `createImageBitmap(imageOrientation: "from-image")`로 방향을 적용하고
  CPU canvas에서 긴 변 3,072px 이하, 품질 0.9 JPEG로 다시 인코딩한다. 같은 파일은 같은 bytes가
  되므로 pending 재개의 이름·형식·크기·SHA-256 대조가 유지된다. 변환 결과가 20MiB를 넘으면
  업로드하지 않고 사진 크기를 줄이라고 안내한다. 브라우저가 디코딩/인코딩하지 못하면 선택한 bytes를
  그대로 올리고 서버 검사가 판단한다. 이 경우 EXIF가 남을 수 있으며 가계 보관함에 암호화해 보관한다.
- Android는 네이티브 보호 화면에서 `ImageDecoder`(software allocator, target size)로 방향을 적용하고
  같은 긴 변·품질 90으로 다시 압축한다. 변환 bytes는 JS bridge로 전달하지 않으며 실패하면 선택한
  bytes를 올린다. 웹과 Android의 긴 변·품질 값은 JVM 시험이 `normalize.ts`와 대조한다.
- 업로드 안내에 PDF 최대 5쪽과 JPEG 사본 업로드를 표시한다.
- 새 422 코드의 안내 문구는 웹 `DocumentSupport`와 `NativeDocumentPolicy.errorMessages`에 있다.
  - `DOCUMENT_IMAGE_UNSUPPORTED`: 지원하지 않는 부가 정보(편집 정보·동영상 등)가 있으니
    JPEG로 다시 저장하거나 다시 캡처해 첨부하라는 안내
  - `DOCUMENT_TOO_COMPLEX`: 쪽수나 해상도가 커서 검사 시간 안에 확인하지 못했으니
    PDF를 5쪽 이하로 나누거나 해상도를 낮추라는 안내
  - 구버전 APK는 두 코드를 일반 실패 문구로 표시한다. 서버와 APK를 같은 배포에서 갱신한다.

```bash
pnpm --filter @sallimbook/client exec playwright test --config playwright.documents.config.ts tests/documents-normalize.spec.ts tests/documents-ui.spec.ts tests/documents-model.spec.ts --workers=1
cd apps/client/android && ./gradlew --no-daemon testDebugUnitTest --tests 'io.github.jihoon22lee.sallimbook.auth.NativeDocumentImageTest' --tests 'io.github.jihoon22lee.sallimbook.auth.NativeDocumentPolicyTest'
```

웹 정규화 시험은 합성 canvas JPEG에 EXIF 방향·XMP·MPF·카메라 꼬리 데이터를 붙여 업로드 bytes에
허용 segment만 남고 꼬리가 없음을, 방향 6의 회전과 긴 변 제한, pending 재개의 동일 해시,
디코딩 불가 파일의 원본 업로드를 확인한다. Android의 방향·메타데이터 제거·결정성은
`NativeDocumentImageDeviceTest` 계측 시험에 있으며 로컬 기기가 없어 아직 실행하지 않았다
(push 후 클라우드 Android instrumentation job에서 실행).

Android 14(API 34) 이상에서 Ultra HDR 사진은 gain map과 함께 디코딩된다. 다시 JPEG로 만들기 전에 gain map을 떼어
SDR 기본 영상만 올린다. `ultraHdrGainmapIsNotUploaded` 계측 시험은 framework가 실제로 만든 Ultra HDR JPEG(MPF와
EOI 뒤 보조 영상)를 정규화해 보조 영상이 남지 않음을 확인한다. 정규화 중 메모리가 부족하면 앱을 종료하지 않고 원본
bytes 업로드로 돌아간다. 업로드는 서버 검사 후 세션을 다시 확인하므로 전송 제한(180초)+5초보다 오래 남은 access token만
쓰고, 그보다 짧으면 먼저 갱신한다. 내보내기와 같은 규칙이다(`NativeDocumentTransferTest`).

### 실기기 확인(Galaxy 카메라 사진)

합성 내용만 적은 종이를 기본 카메라로 찍어 합성 기록에 첨부한다. 사진·스크린샷은 저장소·Issue·PR에
올리지 않고 단계별 성공/오류 코드만 적는다. 모션 포토·Ultra HDR이 정규화 실패로 거절되면 통과로 적지 않는다.

| 항목 | Android 앱 | PC 웹(같은 원본 파일) |
|---|---|---|
| 기본 설정 세로 사진: 첨부, 방향, 다운로드 긴 변 3,072px 이하 | 미실행 | 미실행 |
| 모션 포토 켬 | 미실행 | 미실행 |
| 가로로 돌려 찍은 사진 | 미실행 | 미실행 |
| Ultra HDR 켬(지원 기기) | 미실행 | 미실행 |
| 스캔 앱 5쪽 PDF 첨부 / 6쪽 PDF `DOCUMENT_TOO_COMPLEX` 안내 | 미실행 | 미실행 |
