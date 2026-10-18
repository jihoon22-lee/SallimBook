# 실제 운영 백업과 격리 복원 무결성 확인

2026-10-18, R-20/R-21 및 Issue [#45](https://github.com/jihoon22-lee/SallimBook/issues/45),
[#46](https://github.com/jihoon22-lee/SallimBook/issues/46),
[#49](https://github.com/jihoon22-lee/SallimBook/issues/49)의 운영 근거다.
합성 기능 시험과 별도로 실제 운영 암호화 백업을 읽어 복원 가능한지 확인했다.
운영 계정·금액·진료·첨부 원문·행 수·키는 이 문서나 시험 fixture에 복사하지 않았다.

## 실행 환경과 근거

- 배포 앱/API 소스: `f017d8f61bfeae2304f0109d6f62c9fd13643212`, 0.1.2/versionCode 3.
- 도구: 해당 배포 이미지의 `ops.backup`과 `ops.recovery.check_ciphertexts`, age 1.3.2,
  PostgreSQL 18.6. 이 기록은 이후 추가한 정기 작업 코드의 실행 결과가 아니다.
- 백업 완료: `2026-10-18T02:58:52.455218+00:00`.
- 백업 ID: `dfb24f7e-b95f-4bfe-8e51-62f51253a8d4`.
- 암호화 archive SHA-256: `2a05ee14dfb91ab05af8fcc87b88131a6d2d12e9ae0045d15e4c483384cfad83`.
- 복원 완료: `2026-10-18T03:10:58.582211+00:00`, 무결성 확인 완료:
  `2026-10-18T03:10:59.070603+00:00`.
- `restore.json` SHA-256: `20d7262a57bfcc6e211cf56494083d8cf50279c78e64e27e9c6694fac2b76bb8`.
- `backup-manifest.json` SHA-256: `4550b7a3ee90d561f947ad772826b391a176327b321c535ec04f19df9e73183d`.

완료 receipt와 위 archive digest는 백업 worker와 다른 소유자의 비공개 운영 기록에도 남겼다.
같은 PC에 있으므로 이를 독립 재해 복구 사본으로 세지 않는다. 작성자 서명도 아니다.

## 실제 수행한 검사

| 검사 | 결과와 범위 |
|---|---|
| 일관된 운영 백업 | 제한된 application DB 역할, snapshot/storage barrier, `pg_dump`→age pipeline 성공. 완료 receipt 이후 실제 archive SHA-256 재검사 |
| 백업 키 분리 | 생성 worker에는 공개 recipient만 전달. 복호화 identity·서버 field keyring·APK 서명키는 archive에 넣지 않음 |
| 새 DB 격리 | 고정 PostgreSQL 이미지, `--network none`, 호스트 포트 없음. client는 해당 container의 loopback만 공유. 운영 DB/프록시/Tailscale 연결 없음 |
| 빈 복원 대상 | 임의 식별자의 새 `sallimbook_*_restorecheck` DB를 `TEMPLATE template0`으로 생성하고 기존 객체 부재 검사 |
| archive 복원 | 별도 기록한 SHA-256, age 인증, 제한된 tar 경로·entry·크기·암호문 checksum 검사. 평문 SQL 파일 없이 `pg_restore` |
| 복원 후 DB | 읽기 전용 repeatable-read transaction에서 schema revision과 전체 public 테이블 목록·건수 일치 |
| 복원 후 첨부 | 객체 목록·크기·SHA-256 일치. 서버 keyring으로 ready 문서의 인증 복호화·원본 checksum 검사 |
| 복원 후 암호화 필드 | 계좌/보험 번호를 검사 프로세스 안에서 인증 복호화하고 마스킹 suffix와 대조. 평문/개별 결과는 출력하지 않음 |
| 검사 완료 기록 | `restore-integrity.json`, status `restored-integrity-verified`, 네 검사 모두 true. 원래 manifest/receipt의 SHA-256과 연결 |
| 정리 | 새 DB의 tmpfs와 해당 전용 container만 제거. 운영 DB·계정·키·원본 백업 보존. 복원 출력은 비공개 `QUARANTINE` 상태 유지 |

복원 함수 시작부터 추가 무결성 검사 완료까지 **0.945초**였다. 작은 당시 백업에 대한 수치이며
container 시작·호스트 복구·키 확보·사용자 확인·서비스 전환을 포함한 RTO 측정이 아니다.
DB를 재사용하거나 인증 기록을 변경하는 `recovery.prepare`는 실행하지 않았다.

첫 백업 시도는 운영자가 작성한 libpq service 파일의 `host = …` 형식 때문에 실패했다.
완료 receipt는 발급되지 않았다. 기존 파일은 보존하고 공백 없는 `host=…` 형식의 새 service 파일을
작성한 후 실제 `pg_dump`와 전체 백업을 다시 실행해 성공했다. 비밀번호·SQL·subprocess 원문 오류는
채팅이나 공개 로그에 출력하지 않았다. 예제 형식은 [운영 실행 문서](../operations-runbook.md)를 따른다.

## 아직 확인하지 않은 항목

- 이 PC와 독립된 암호화 사본 및 별도 키 보관 위치. 로컬 백업·복원 성공으로 대체하지 않는다.
- 새 정기 백업/복원/보존 작업의 설치·중복 실행·실패·재시작 검증.
- 두 사용자의 보관함 복호화, 새 인증 폐기/발급, 키 회전, RPO 손실 수용과 실제 운영 전환.
- WSL/Windows 재시작과 전체 서비스 복구 시간, 두 실제 기기의 복구 후 동작.

`restore-integrity.json`은 백업의 격리 복원 무결성 근거다. 운영 전환 승인이나 사용자 보관함 복구
완료를 뜻하지 않는다. [전체 복원 게이트](../operations-runbook.md#6-인증과-보관함의-rollback-방지)는 유지한다.
