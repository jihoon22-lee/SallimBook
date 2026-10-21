# ADR 0010 — 문서 검사기 격리

상태: 구현 진행(2026-10-20 사용자 지시), 운영 배포 전 사용자 검토 · 날짜: 2026-10-20
관련: 리뷰 M15, WP12, [보안·인증](../security-authentication.md), [운영 runbook](../operations-runbook.md)

## 배경

첨부 문서는 ClamAV 검사 뒤 이미지·PDF 구조 검사와 OCR을 거친다. ClamAV는 네트워크 없는 별도 컨테이너다. 그러나 구조 검사 워커와 pdftoppm·tesseract는 API 컨테이너 안에서 API와 같은 UID로 실행된다. 이 구성에서는 파서·OCR 도구의 결함이 필드 암호화 keyring, 문서 저장소, DB 네트워크에 닿을 수 있다. 워커 RLIMIT_AS(768MiB)는 API 컨테이너 한도(768MiB)와 같아서 큰 이미지 OCR이 uvicorn까지 메모리 부족으로 끝낼 수 있다.

## 결정

구조 검사·렌더링·OCR을 검사 전용 `inspector` 컨테이너로 옮긴다.

- 같은 API 이미지를 쓴다. UID 10002·GID 10003, `network_mode: none`, 읽기 전용 root, capability 없음, `no-new-privileges`, PID 32개다. 컨테이너 init(`init: true`)이 PID 1로 고아 OCR 프로세스를 회수한다.
- 비밀·환경 파일·문서 저장소·scanner socket을 mount하지 않는다. 공유하는 것은 전용 이름 볼륨의 Unix socket 하나(0660, 그룹 10003)다. 볼륨 디렉터리는 이미지에서 10002:10003·0750으로 만든다. API는 그룹 10003을 추가로 가진다.
- 메모리 한도는 1152MiB이고 swap은 없다. 계산: peak 800,366,592B(763.3MiB) → max(1024, ceil((1.25 × 763.3MiB + 96MiB) / 128MiB) × 128MiB) = max(1024, 9 × 128) = 1152MiB.
- 워커는 문서마다 새 프로세스로, 기존 RLIMIT를 그대로 쓴다. 동시 검사는 1개이고 바쁘면 대기열 없이 503이다.
- API는 ClamAV 검사, 결과 형식 검증, 암호화·저장을 계속 맡는다. 운영 환경에서 inspector 설정이 없으면 시작하지 않는다.

## 대안

- 같은 컨테이너에서 다른 UID로 실행: `no-new-privileges`와 `cap_drop: ALL`에서는 UID를 바꿀 수 없다. 바꾸려면 setuid helper나 capability가 필요해 기존 경계가 약해진다.
- 워커 RLIMIT만 낮추기: 메모리 위험은 줄지만 keyring·저장소·DB 네트워크 접근은 그대로다.
- ClamAV 컨테이너에 함께 넣기: ClamAV 메모리 예산(1.5GiB)과 서명 갱신 수명주기에 OCR 부하가 섞인다.

## 결과와 비용

- 호스트 메모리 한도 합이 1152MiB 늘어난다(합계 4928MiB / MemTotal 20000MiB, 기준 70%인 14000MiB 이하). 기존 합 3776MiB는 node 256·public 64·web 128·api 768·scanner 1536·db 1024MiB다.
- 서비스가 하나 늘어난다. 자동화의 서비스 목록·CVD 승격·롤백·복구가 inspector를 함께 다룬다.
- 개발·테스트는 inspector 설정이 없으면 기존 로컬 워커를 쓴다. 운영 동작은 실제 inspector를 띄우는 시험(`ops.test_runtime`, HTTPS `--documents`)으로만 확인한다.
- 16MP(4608×3456) 원본 사진 OCR은 측정 환경에서 통과했고 컨테이너 메모리 최고치가 763.3MiB였다. 워커 한 프로세스의 RLIMIT_AS(768MiB)와 별개로 도구 자식 프로세스가 함께 쓰는 값이라 1024MiB 하한보다 높은 1152MiB를 쓴다. 클라이언트 정규화(WP03)는 업로드를 3072px로 줄인다.

## 검증

- `ops.test_runtime`: inspector의 UID·네트워크·mount·capability, 실제 한국어 OCR 업로드, inspector 메모리 소진 시 API 생존, inspector 중지 시 API unhealthy와 복구
- HTTPS `--documents`: 실제 도구 이미지의 inspector로 업로드
- 측정 요약(2026-10-20, 합성 입력, `scripts/test_document_tools.py --measure`, 도구 이미지 `sallimbook-document-tools:sb023-20261018`):

| case | 쪽수 | 전체 초 | 결과 | memory_peak_bytes | max_rss_kib |
| --- | --- | --- | --- | --- | --- |
| pdf-text-a4-1 | 1 | 10.252 | accepted | 505,417,728 | 126,532 |
| pdf-text-a4-2 | 2 | 17.858 | accepted | 387,432,448 | 152,260 |
| pdf-text-a4-4 | 4 | 36.846 | accepted | 419,258,368 | 183,116 |
| pdf-text-a4-8 | 8 | 0.191 | DOCUMENT_TOO_COMPLEX | 218,337,280 | 126,572 |
| pdf-image-a4-1 | 1 | 8.394 | accepted | 338,690,048 | 125,956 |
| pdf-image-a4-4 | 4 | 31.826 | accepted | 416,788,480 | 186,632 |
| jpeg-photo-3072x2304 | 1 | 8.667 | accepted | 460,156,928 | 159,048 |
| jpeg-photo-4000x3000 | 1 | 11.671 | accepted | 646,881,280 | 227,032 |
| jpeg-photo-4608x3456 | 1 | 12.271 | accepted | 800,366,592 | 290,392 |

이 문서는 운영 배포를 이미 검증했다는 보고가 아니다.
