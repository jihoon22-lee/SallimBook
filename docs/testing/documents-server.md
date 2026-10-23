# 첨부 서버 검증

대상: SB-023, Issue #32, R-13/R-15/R-20. 보험계약·사건·진료·비용·청구·가전·자산의
typed 연결, 암호화 원본 저장과 인증 다운로드를 API 9개로 제공한다.

## 실행 결과

```bash
uv run --project services/api python scripts/test_database.py services/api/tests/test_documents.py services/api/tests/test_document_storage.py services/api/tests/test_document_validation.py -q
uv run --project services/api --frozen python scripts/test_document_tools.py
pnpm api:generate
pnpm typecheck
uv run --project services/api ruff check services/api/src services/api/tests services/api/migrations
python3 scripts/validate_docs.py
```

API·실제 PostgreSQL 39개, 암호화·파일 저장소 30개, 검사 계약 81개로 **150개 통과**했다.
Alembic `upgrade head`, drift 검사, 전체 downgrade/upgrade도 통과했으며 전용 DB를 정지했다.
초기 실패는 링크 종료 중 autoflush로 문서 버전을 두 번 올린 문제와 긴 임시 Unix socket 경로였다.
버전 갱신 전 링크 수를 조회하고 합성 socket 경로를 짧게 고친 뒤 관련 검사와 135개 전체를 다시 통과했다.

다른 가계의 목록/연결/업로드/다운로드/삭제 차단, 부부 공동 접근, 크기·MIME·경로·해시 검증,
DB 직접 우회, 암호문 치환·훼손·권한·symlink/hardlink 거부, 멱등 참조 보존을 확인했다.
검사 중 세션 철회와 연결 종료, 복호화 후 인증 만료, 느린 본문 수신 중 세션 철회,
동시 삭제/링크 추가도 포함한다. 파일에 원문이 저장되지 않고 복원 checksum이 일치함을 검사한다.

실제 ClamAV 1.4.6·Pillow 13.0.0·pypdf 6.21.1·Poppler·Tesseract 도구 검사 **20개도 통과**했다.
합성 영어/한글 영수증 PNG/JPEG/PDF 허용과 EICAR·카드 라벨/PAN·실행 PDF·빈 이미지·도구 장애 거부,
검사 후 RAM spool 정리를 확인했다. 81개 검사에 있는 가짜 Unix daemon/OCR 경계 시험과 구분한다.
고정 버전·이미지 ID·자원 제한·공식 근거는 [도구 기록](../../infra/documents/README.md)에 있다.

## 상태와 정리

업로드 생성은 최초 링크까지 원자적으로 저장한다. pending은 24시간 후 만료되며 원본 저장 전의
metadata와 연결 이력은 유지된다. 마지막 링크를 종료한 ready 문서는 orphaned_at을 기록하지만
사용자의 명시적 삭제 전까지 원본을 보존한다. 다시 연결하면 이 시각을 비운다.
문서 삭제는 현재 링크를 모두 종료하고 즉시 다운로드를 막으며, 암호문 물리 정리는 24시간 후 가능하다.

```bash
uv run --project services/api python scripts/cleanup_documents.py
# 위 dry-run의 개수를 검토한 뒤 같은 설정으로 실행한다.
uv run --project services/api python scripts/cleanup_documents.py --apply
```

정리는 저장소 안의 서비스 소유·0600·단일 link·규격 UUID 파일만 검사한다. 다른 파일·symlink·
현재 DB 참조·최근 파일은 보존한다. 업로드는 DB commit까지 exclusive advisory lock을 가지며
정리는 exclusive lock 안에서 DB 참조와 파일을 대조해 진행 중인 업로드를 지우지 않는다.
정리 결과에는 개수만 출력하며 파일명·원문·암호키를 출력하지 않는다.

## 남은 인수

이 PR은 서버와 검사 도구 범위다. 웹·Android 파일 선택/저장·연결 화면과 실제 HTTPS 흐름은
클라이언트 변경에서 검증한다. 실제 Galaxy 실패 시나리오와 운영 scanner 배포·백업 복원은
전체 기능 구현 뒤에 수행하며 서버 시험이나 debug 빌드를 실기기 보안 인수로 간주하지 않는다.

PR 리뷰 보완: 본문을 읽기 전에 API 프로세스당 업로드 한 개로 제한하며 초과는 503이다.
본문 취소·검증 실패 때 슬롯을 반환하고, 검사 중 HTTP 취소는 worker가 끝날 때까지 슬롯을 유지한다.
worker는 요청 dependency와 별도 DB session을 소유해 취소된 요청의 session 종료와 겹치지 않는다.
실제 비동기 ASGI 수신으로 선행 제한·본문 미수신·취소/실패 후 재사용·worker 완료를 4개 추가 검증했다.
새 서명 갱신 날짜 build 인자를 포함한 도구 이미지의 build-only도 통과했다.

두 번째 리뷰 보완: API의 가계 잠금에 더해 연결 종료도 문서→연결 순서로 잠근다.
부모를 잠근 직접 저장소 트랜잭션이 자식 링크를 기다리지 않고 끝낼 수 있으며, 그 뒤 API는
변경된 버전을 409로 반환함을 실제 경합 시험으로 확인했다. 가전의 문서 연결을 종료해도 과거
연결 이력이 있으면 가전 물리 삭제를 막는 회귀를 추가했다. 총141개와 Alembic drift/왕복을 통과했다.


세 번째 리뷰 보완: 저장 전에 독립 DB 트랜잭션으로 파일명·가계·문서·암호문 크기를 예약한다.
기본 가계 한도는 256MiB/200개, 전체는 2GiB/2,000개이며 AES-GCM tag 16바이트도 센다.
실패·취소·DB rollback이나 commit 결과 불명에도 예약은 유지된다. ready 문서의 마지막 연결 종료만으로는
용량을 반환하지 않는다(다시 연결할 수 있다). 사용자가 문서를 삭제하면 같은 트랜잭션에서 그 문서의 예약을
반환해 바로 다른 파일을 올릴 수 있다. 암호문은 24시간 유예 뒤 정리 작업이 지우며, 그동안의 디스크는
업로드 전 여유 공간 검사가 지킨다. 실패 업로드처럼 문서가 가리키지 않는 파일의 예약은 24시간 유예 뒤
정리 작업이 실제 제거와 fsync 또는 파일 부재를 확인해야 반환한다. dry-run은 예약을 바꾸지 않는다. 모든 API worker는 같은 설정과 DB를 사용한다.
저장/정리 공통 exclusive barrier가 프로세스 사이의 디스크 쓰기를 직렬화하며 별도 quota 잠금이
용량 집계·예약 commit을 보호한다. 문서는 NO KEY UPDATE로 잠가 독립 예약의 가계 복합 FK 검사를 허용한다.
현재 파일을 가리키는 용량 예약의 직접 해제·변조·삭제와 예약 없는 ready 전환도 DB가 거부한다.

가계/전체 byte·count 경계, 한도 중 멱등 재전송, 다른 가계 동시 업로드, 저장 후 오류로 남은 파일,
연결 종료/삭제/정리의 용량 반환, 디스크 여유 공간과 직접 DB 우회 9개를 추가해 총150개를 통과했다.
설정은 `SALLIMBOOK_DOCUMENT_HOUSEHOLD_QUOTA_BYTES/COUNT`, `SALLIMBOOK_DOCUMENT_GLOBAL_QUOTA_BYTES/COUNT`,
`SALLIMBOOK_DOCUMENT_MIN_FREE_BYTES`이며 기본 여유 공간 1GiB를 남기지 못하면 쓰기 전에 503을 반환한다.
용량은 413 `DOCUMENT_STORAGE_QUOTA_EXCEEDED`, 디스크 여유는 503 `DOCUMENT_STORAGE_CAPACITY_UNAVAILABLE`다.
이미 내려받은 파일이나 운영 백업 공간은 이 온라인 저장소 한도와 별도로 관리한다.


## PDF 날짜 메타데이터 오탐 회귀 — 2026-10-18

일반 CI `39100098307`의 문서 도구 job `117594466154`가 `pdf_image_korean`에서 실패했다.
수정 전 같은 도구 이미지에서 동일한 합성 영수증을 UTC `2026-10-18 05:19:00`과
`05:19:08`로 고정해 만들면 전자는 허용되고 후자는 `DOCUMENT_CARD_DATA`로 거절됐다.
두 파일은 날짜 바이트 외에는 같았다. 전체 검사에서도 각각 2.384초 허용/0.281초 거절이었고,
후자는 OCR 전에 PDF `/Info`의 자동 생성일·수정일 문자열이 Luhn 검사에 걸렸다.
시간 제한이나 CPU 부하 때문에 발생한 실패로 처리하지 않는다.

PDF 표준의 날짜 타입을 식별하는 범위를 trailer의 간접 `/Info` dictionary 안의
`/CreationDate`와 `/ModDate`로 제한한다. ASCII `D:` 날짜 문법과 실제 달력·시각·시차 범위를
모두 통과하는 문자열만 날짜로 취급한다. 해당 문자열을 제목·페이지·배열·고립 객체 등에서
다시 참조하면 그 위치에서는 일반 카드정보 검사를 받는다. 방문 기록도 객체의 해석 문맥을
구분하므로 날짜 위치를 먼저 방문한 순서가 일반 문자열 검사를 생략시키지 않는다.
잘못된 날짜·추가 문구·Unicode 위장·임의 dictionary의 같은 키에는 예외를 적용하지 않는다.
본문·다른 metadata·CVC/PAN·파일 크기·OCR·악성코드·자원 제한은 그대로다.

근거는 Adobe가 게시한 [ISO 32000-1:2008](https://opensource.adobe.com/dc-acrobat-sdk-docs/standards/pdfstandards/pdf/PDF32000_2008.pdf)의
§7.9.4, Table 15, §14.3.3/Table 317과 PDF Association의
[ISO 승인 날짜 정오표](https://pdf-issues.pdfa.org/32000-2-2020/clause07.html#794-dates)다.
일반 합성 PDF에서는 자동 시각 metadata를 생략해 fixture를 결정적으로 만들고,
별도의 실제 도구 사례에서 오탐을 재현한 날짜를 명시해 정상 허용을 검증한다.
카드정보가 있는 제목과 날짜 뒤의 추가 카드 문구는 거부 사례로 유지한다.

이 변경은 PDF 내용 검사이며 API 계약·DB schema·저장 원본을 바꾸지 않는다.
사용자의 파일을 수정하거나 metadata를 삭제하는 기능이 아니다.


다음 실제 PostgreSQL 실행은 **225개 통과**, Alembic drift 없음과 downgrade/upgrade 왕복,
시험 DB 정지까지 확인했다. 가계 경계·첨부 접근 권한·저장 무결성·기존 검사와 날짜 회귀를 함께
실행한 결과이며 이전 150개와 합산하지 않는다. 기존 Starlette TestClient의 httpx 교체 안내
경고 1개가 있었고 실패는 없었다.

```sh
uv run --project services/api python scripts/test_database.py services/api/tests/test_documents.py services/api/tests/test_document_storage.py services/api/tests/test_document_validation.py services/api/tests/test_pdf_metadata_dates.py -q
```


그 뒤 추가한 PDF fixture의 페이지 수 회귀를 포함해 날짜·기존 검사 **157개**가 통과했다.
worker 본문은 위 DB 실행 후 변경하지 않았다. 실제 network-none·4GiB·2CPU 도구 이미지에서도
**23개 모두 통과**했다. `pdf_dated_korean` 허용과 `card_pdf_metadata`, `card_pdf_date_suffix`
거절을 포함하며 timeout·OCR·서명 DB 기준을 낮추지 않았다. 초기 새 fixture의 writer context
진입이 clone 페이지를 초기화하는 문제를 명시적 close로 고쳤고, 정상 페이지 1개를 별도 검사한다.
최종 검사 이미지 ID는 `sha256:1bcd3e967ad706a3df96cc8ab4ae333e6a8eae6f9621650ad114fa0ee8ed4ed3`이다.
전용 임시 컨테이너는 종료·제거했고 검토용 이미지는 보존했다. 이는 운영 배포 완료 기록과 구분한다.

## 문서 검사 정확도(H2·M16·L12) — 2026-10-20

검토에서 정상 사진·PDF가 거절되거나 검사 시간을 넘기는 문제 세 가지를 확인했다.
H2는 압축된 사진·PDF 데이터 안의 우연한 바이트가 위험 표식으로 판정된 문제,
M16은 쪽수·해상도 제한 없이 OCR이 worker 시간을 넘기던 문제, L12는 날짜 두 개나
옆으로 누운 글자의 OCR 숫자가 카드번호 후보로 판정된 문제다.

### 위험 표식 검사 구간

- JPEG는 엔트로피 부호화 데이터, PNG는 IDAT, PDF는 strict parser가 길이를 확인한 스트림
  데이터만 표식 검사에서 뺀다. 헤더·segment·chunk·사전·꼬리 등 나머지는 모두 검사한다.
- 제외 구간의 경계는 표식 길이만큼 겹쳐 검사하며 파일 끝 ZIP 중앙 디렉터리 표식은 항상 검사한다.
- 구조를 해석할 수 없으면 제외 없이 파일 전체를 검사한다. 허용 profile 밖의 JPEG segment·PNG chunk·
  EOI/IEND 뒤 데이터는 `DOCUMENT_IMAGE_UNSUPPORTED`, 깨진 구조는 기존 `DOCUMENT_UNSAFE`다.
- 다운로드의 nosniff·CSP sandbox·attachment 경계와 ClamAV·카드 정보 검사는 그대로 유지한다.

### 처리 한도

격리된 도구 container(network none, CPU 2개, 메모리 4GiB)에서 실제 worker로 측정했다.
4방향 OCR을 한 번에 두 방향씩 병렬 실행하도록 바꾼 뒤의 값이다(사용자 결정, 2026-10-20).

| 합성 입력 | 결과 | 시간 |
|---|---|---|
| 글자 PDF A4 1/2/4/8쪽 | 허용 | 8.7/18.6/37.6/72.0초 |
| 이미지 PDF A4 1/4쪽 | 허용 | 7.4/33.3초 |
| JPEG 3072×2304/4000×3000/4608×3456 | 허용 | 8.1/10.7/11.8초, 최대 메모리 441/615/762MiB |

쪽당 비용 s = 9.04초(글자 PDF 기울기)에서 `floor((90 − 10) / (1.5 × 9.04)) = 5`이므로
`MAX_PAGES = 5`, `DEADLINE_SECONDS = 80`, API의 `WORKER_SECONDS = 90`, 도구 호출당 10초다.
6쪽 이상 PDF, 1,600만 화소 또는 한 변 8,192px 초과, 검사 시간 초과는 422 `DOCUMENT_TOO_COMPLEX`로 답한다.
병렬 OCR 전 측정(s = 15.52초)으로는 3쪽이 한계였다. 운영 CPU가 더 느리면 5쪽 PDF가
같은 오류로 거절될 수 있으며 이 경우 worker 비정상 종료가 아니라 안내 가능한 오류다.

### 카드번호 후보

카드번호 후보는 실제 카드 번호 묶음(공백 없는 13~19자리, 4-4-4-4와 끝 1~3자리, 4-6-5, 4-6-4,
한 자리씩 띄운 숫자 연속; 공백·하이픈·전각 숫자 포함)만 Luhn 검사한다. 날짜 쌍·계좌번호처럼 다른 묶음의 숫자는 후보가 아니다.
탭·연속 공백·줄바꿈은 공백 하나로 본다. OCR·PDF가 카드 격자의 구분을 일부 잃은 묶음(`4123 4567 89012349`,
`41234567 89012349`, `3712 34567890120`, 17~19자리의 `6212 3456 7890 1234569`처럼 경계가 모두
4-4-4-4(-끝자리) 또는 4-6 격자 위에 있는 묶음)도 후보다. 마지막 구분이 빠져도 같다.
단 이렇게 합쳐진 묶음이 19xx·20xx 날짜(YYYYMMDD)로 시작하면 날짜 쌍·승인번호로 보고 후보에서 뺀다.
2026년부터 1,460개 날짜 쌍(7일 간격)을 네 날짜 형식과 다섯 구분자로 쓴 29,200개 문장에서 오탐은 0이다.
OCR TSV는 따옴표를 인용 문자로 해석하지 않는다. 따옴표로 시작하는 단어가 뒤 단어를 삼키지 않는다. OCR에서 공백 없이
13자리 이상 이어진 한 단어는 신뢰도 30 이상일 때만 후보로 본다(사용자 결정, 2026-10-20).
옆으로 누운 글자의 숫자 덩어리는 신뢰도 4~22였고 바로 선 실제 번호는 95 이상이었다.
묶음 숫자·PDF 글자 layer·EXIF·카드 라벨 검사는 바꾸지 않았다.

### 실제 도구 검사

```bash
uv run --project services/api --frozen python scripts/test_document_tools.py
uv run --project services/api --frozen python scripts/test_document_tools.py --measure
```

기존 단계에 아래 8개를 더해 모두 통과했다. `pdf_max_pages`(5쪽 이미지 PDF)는
`max_pages_seconds` 4.102초로 `WORKER_SECONDS` 90초 안에서 끝났다.

- 허용: `jpeg_marker_in_scan`, `jpeg_reencoded_phone`, `png_dates_korean`, `pdf_max_pages`
- 거절: `jpeg_phone_original`(`DOCUMENT_IMAGE_UNSUPPORTED`), `jpeg_comment_marker`,
  `jpeg_trailer_zip`, `pdf_too_many_pages`(`DOCUMENT_TOO_COMPLEX`)

`--measure`는 합성 입력별 결과 코드·시간·메모리 숫자만 출력한다. 검사 container는
`sallimbook-document-test-*` 이름만 만들고 끝나면 제거한다. 실제 HTTPS `test_web_auth.py --documents`와
`--exports`도 통과했다. 실제 Galaxy 카메라 사진 확인은 [첨부 UI 검증](documents-client.md)에 기록한다.

## 문서 검사 격리(M15) — 2026-10-20

구조 검사·렌더링·OCR을 API 컨테이너 밖의 검사 전용 `inspector` 컨테이너로 옮겼다
([ADR 0010](../adr/document-inspection-isolation.md)). inspector는 API와 같은 이미지를 UID 10002·GID 10003으로
실행하며 네트워크·비밀·문서 저장소·scanner socket이 없다. API와는 전용 볼륨의 Unix socket 하나만 공유하고,
연결마다 요청 하나(종류·길이 머리말과 문서 bytes)를 받아 기존 `_validation_worker.py`를 기존 RLIMIT로 새로 실행한다.
응답은 1KiB 이하 고정 JSON이다. 시간 초과는 `DOCUMENT_TOO_COMPLEX`, 그 밖의 실패와 동시 검사는
`DOCUMENT_SCAN_UNAVAILABLE`로 답하고, ping은 검사 중에도 바로 답한다. API는 ClamAV 검사, 결과 형식 재검증,
암호화·저장을 지금처럼 맡는다. 개발·테스트는 inspector 설정이 없으면 로컬 워커를 쓰고, 운영은 inspector 없이
시작하지 않는다. API 응답 형태·오류 코드·워커 규칙·RLIMIT는 바뀌지 않았다.

실행한 시험과 결과:

| 시험 | 결과 |
|---|---|
| `services/api/tests/test_document_inspector.py`(프로토콜·분류·검사 중 ping·잘못된 요청·socket 교체 거부) | 11 passed |
| `test_document_validation.py`의 원격 검사 시험(로컬과 같은 결과, API 측 결과 검증, 없음·world-writable·무응답 inspector의 503) | 7 passed |
| `python3 -m ops.test_runtime --image <로컬 빌드 이미지 ID>` | inspector 프로브(UID·네트워크·비밀·저장소·capability·socket 권한), 메모리 소진 격리(합성 할당이 137로 종료되고 API는 healthy·재시작 0), inspector 중지 시 API unhealthy와 복구 모두 PASS |
| `scripts/test_document_tools.py` | 31개 검사 PASS |
| `scripts/test_web_auth.py --documents`·`--exports` | 통과(도구가 운영과 같이 워커 RLIMIT 안에서 실행) |

운영 배포와 확인표는 [운영 runbook](../operations-runbook.md)의 "문서 검사기 배포와 되돌리기"를 따른다.
운영 배포 결과는 아직 없다.
