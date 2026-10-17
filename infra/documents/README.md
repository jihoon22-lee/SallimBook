# SB-023 문서 검사 도구 검증

R-13/R-15/R-20의 PDF/JPEG/PNG 검사 경계를 실제 도구로 재현하는 전용 이미지다.
운영 배포·서명키 설정·호스트 서비스 설치를 수행하지 않는다. 테스트 자료는 실행 중 메모리에서
만드는 합성 영수증·문서와 공개 EICAR 검사 문자열뿐이며 원문 파일이나 OCR 결과를 저장하지 않는다.

## 고정한 도구

| 도구 | 고정값과 확인 근거 |
|---|---|
| Python | `3.14.7-slim-trixie`, linux/amd64 manifest `sha256:7bf6c3111fe094f8ee1a1cbcdc63c4cfb345b0e3df42d5aa9a90b3b4b022ab6d`; [공식 이미지](https://hub.docker.com/_/python) |
| Debian 저장소 | Debian 및 Debian Security의 `20261017T000000Z` 서명된 snapshot; 전이 apt 의존성도 같은 시점에서 해석 |
| ClamAV | Cisco 공식 `1.4.6-1` x86_64 deb, SHA-256 `d3ee9e401974855a1edc1761b1425417d126de618d5f0c91cd51209f69f6fcc2`; [공식 릴리스](https://github.com/Cisco-Talos/clamav/releases/tag/clamav-1.4.6)와 공식 release API의 asset digest 대조 |
| Poppler | `poppler-utils=25.03.0-5+deb13u4`; [Debian 패키지](https://packages.debian.org/trixie/poppler-utils) |
| Tesseract | `tesseract-ocr=5.5.0-1+b1`; [Debian 패키지](https://packages.debian.org/trixie/tesseract-ocr) |
| OCR 언어 | eng/kor `1:4.1.0-2`; [영어](https://packages.debian.org/trixie/tesseract-ocr-eng), [한국어](https://packages.debian.org/trixie/tesseract-ocr-kor) |
| 합성 한글 폰트 | `fonts-noto-cjk=1:20240730+repack1-1`; [Debian 패키지](https://packages.debian.org/trixie/fonts-noto-cjk) |
| Python 라이브러리 | API `uv.lock`에서 해시와 함께 내보낸 `requirements.txt`; Pillow 13.0.0, pypdf 6.21.1 포함 |

`toolchain.lock.json`은 위 입력과 API lockfile/내보낸 requirements의 해시를 기록한다.
API 의존성이 변경되면 공식 버전·호환성을 검토한 뒤 다음 명령으로 내보내고 두 해시를 갱신한다.

```bash
uv export --project services/api --frozen --no-dev --no-emit-project --format requirements-txt --output-file infra/documents/requirements.txt
```

초기 Debian ClamAV 1.4.3 시험은 정상 동작했으나 FreshClam의 보안 패치 권고를 확인한 뒤
공식 1.4.6으로 교체했다. `sid` 저장소를 섞거나 호스트 apt 패키지를 변경하지 않았다.
악성코드 서명은 바이너리와 달리 최신성을 유지해야 한다. FreshClam이 공식 서명 CVD를 받아
검증하며 다운로드 실패는 빌드 실패다. harness가 UTC 날짜를 빌드 인자로 전달하여 날짜가 바뀌면
서명 다운로드 캐시를 갱신한다. 7일 넘게 오래된 이미지/DB는 검사 성공으로 취급하지 않는다.

## 실행과 격리

저장소 루트에서 실행한다. 다른 브라우저 시험과 Docker 생성·중지를 병행하지 않도록 순서를 조정한다.
독립 `document-tools-test.lock`은 같은 이미지/도구 시험의 중복 실행만 차단하며 DB 서비스를 제어하지 않는다.

```bash
uv run --project services/api --frozen python scripts/test_document_tools.py
# 이미지 빌드만: --build-only
# 이미 검증한 현재 이미지 재시험: --skip-build
```

harness는 `sallimbook-document-test-<random>` 컨테이너 하나만 생성하고 종료 시 그 ID만 제거한다.
포트·호스트 볼륨·DB·운영 인증정보를 연결하지 않는다. network none, 읽기 전용 rootfs,
UID/GID 10001, capability 전부 제거, no-new-privileges, CPU 2개·메모리 4GiB·PID 64 제한을 사용한다.
메모리와 memory-swap을 같은 값으로 지정하고 내부 cgroup의 `memory.swap.max=0`을 확인한다.

API/파서/OCR는 원문과 결과를 메모리 파이프로만 전달한다. 다만 **ClamAV INSTREAM도 데몬 내부에서
임시 파일에 입력을 모은다**. 이를 파일이 전혀 없는 검사라고 표현하지 않는다.
[공식 INSTREAM 구현](https://github.com/Cisco-Talos/clamav/blob/clamav-1.4.6/clamd/server-th.c)은
임시 FD를 사용하므로 daemon의 TemporaryDirectory를 전용 96MiB tmpfs의 0700 디렉터리로 제한한다.
디스크 스왑을 차단하고 noexec/nosuid/nodev를 확인하며 검사 후 RAM spool이 비었는지 검사한다.
ForceToDisk/LeaveTemporaryFiles/메타데이터 생성·상세 로그는 비활성화하고 daemon 출력은 버린다.
원문 경로나 파일명은 daemon에 전달하지 않는다. private Unix socket의 INSTREAM만 사용한다.

ClamAV 설정은 StreamMaxLength 20MiB, MaxScanSize 64MiB, MaxScanTime 10초,
AlertExceedsMax/AlertEncrypted 활성화다. 제한 초과를 검사 성공으로 취급하지 않는다.
PING/VERSIONCOMMANDS, 검증한 engine 1.4.6, INSTREAM 지원과 서명 DB 날짜를 매 업로드에 확인한다.
데몬의 TZ는 Etc/UTC다. CVD 날짜를 UTC로 해석해 7일 초과 또는 미래 5분 초과이면 503이다.

## 지원 범위와 한계

20MiB 이하이며 글자를 읽을 수 있는 영수증·문서만 지원한다. 사진 자체를 보관하는 앨범,
글자 없는 의료 영상, 암호화 PDF, PDF 증분 업데이트, 동작/폼/내장 첨부, APNG,
임의 이미지 텍스트 청크·지원하지 않는 metadata는 검사에서 거부한다.
일부 정상 문서도 이 보수적 범위를 벗어나면 거부될 수 있다.

Pillow verify/load와 PNG/JPEG 구조 종료를 대조하고, PDF strict parse 뒤 도달하지 않는 객체까지
검사한다. 정상 압축 객체/교차참조 스트림은 지원한다. 픽셀 16MP/변당 8192, PDF 20쪽/객체 10,000/
깊이 64, 해제 스트림 하나 8MiB/합계 64MiB를 제한한다. pypdf의 공식 Configuration으로 파싱과
해제 작업도 제한한다. 별도 워커는 주소 공간 768MiB, CPU 45초, wall 60초, core/file 크기 0 제한을
적용하며 출력은 고정 상태 1KiB로 한정한다. API 프로세스당 검사 하나만 실행하고 바쁜 상태는 503이다.
이 제한은 자원 소모 방어이며 파서 취약점이나 모든 악성 문서가 없다는 증명은 아니다.

모든 PDF 페이지는 Poppler로 렌더하고 모든 이미지는 4방향 Tesseract eng+kor OCR로 검사한다.
추출 문자·낮은 신뢰도의 인식 문자에도 Luhn 카드번호와 카드번호/CVC/CVV 등 라벨 검사를 적용한다.
읽을 수 없는 결과는 거부한다. OCR은 모든 카드 사진을 완벽하게 식별하지 못한다.
부모 API의 카드 첨부 typed-link 금지와 사용자 확인을 함께 적용하며 이 검사만으로 카드 사진
저장을 안전하게 허용할 수 있다고 해석하지 않는다. 보관·복원은 정규화한 이미지가 아닌 **검사한 원본 bytes**다.

## 확인한 결과

- `uv run --project services/api --frozen pytest services/api/tests/test_document_validation.py -q`: **81개 통과**.
  실제 Pillow/pypdf·격리 프로세스·출력/timeout/resource 제한과 가짜 Unix daemon/OCR 경계 시험을 구분한다.
- 실제 tool harness: **20개 통과**. 영어 PNG/JPEG, 한글 PNG, 텍스트 PDF, 한글 이미지 PDF 허용;
  EICAR, active PDF, Luhn PAN 텍스트 PDF/PNG, 카드 라벨 텍스트·이미지 PDF/PNG, 빈 이미지,
  20MiB 초과, MIME 불일치, OCR 미설치, 검사기 미설정/중지 거부 및 RAM spool 정리를 확인했다.
- 검증 image ID: `sha256:20f3c24df337d2926a65013b354ece237b04845db3df692f9edeee51716ad604`.
  Python 3.14.7, Pillow 13.0.0, pypdf 6.21.1과 공식 ClamAV 1.4.6을 사용했다.
- API 권한·암호화·DB 제약과 실제 Android 다운로드 동작은 이 도구 시험과 별도 검증이다.

관련 공식 문서: [ClamAV 프로토콜](https://docs.clamav.net/manual/Usage/ClamdProtocol.html),
[서명 갱신](https://docs.clamav.net/manual/Usage/SignatureManagement.html),
[Pillow 보안](https://pillow.readthedocs.io/en/stable/handbook/security.html),
[pypdf Configuration](https://pypdf.readthedocs.io/en/6.21.1/modules/configuration.html),
[Tesseract CLI](https://github.com/tesseract-ocr/tesseract/blob/main/doc/tesseract.1.asc).
