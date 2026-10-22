# SallimBook 운영 예약 작업

연결: SB-036/#45, SB-037/#46 · R-02, R-20, R-21.
상위 절차: [운영 runbook](../operations-runbook.md), [v1 완료 계획](../v1-completion-plan.md).

`ops.automation`은 전용 Compose 프로젝트의 백업·상태 검사·격리 복원·ClamAV 서명 DB 갱신·시작을
수행한다. `ops.schedule`은 같은 작업을 호출하는 **사용자 systemd** 파일을 생성·검증·설치·활성화한다.
모듈을 import하거나 예약 파일을 생성하는 것만으로 Docker나 systemd 서비스를 시작하지 않는다.
기존 WSL 서버·컨테이너·DB·호스트 Tailscale 설정, 전역 systemd 서비스, loginctl linger는 변경하지 않는다.

## 실행 경계와 시간

| 작업 | 기본 예약, Asia/Seoul | 성공 조건 | 제한 시간 |
| --- | --- | --- | --- |
| `startup` | 사용자 manager의 `default.target` | 실제 배포 preflight, 전용 Compose 시작, 7개 서비스(문서 검사기 포함) 및 스캐너 확인 | 10분 |
| `backup` | 매일 03:15 | 일관된 암호화 백업, 실제 archive SHA-256, 별도 운영 장부 기록 | 45분(백업 worker 30분 + 준비·ack·실패 정리 여유 15분) |
| `health` | 매시간 15분 | 먼저 운영 장부/백업/첨부/build/daemon 이미지 저장소 여유 1GiB 이상(백업 기록이 없어도 확인), 그다음 서비스 상태, 실제 스캐너 응답/신선도, 백업 존재·26시간 이내 | 5분(+ 사전 검사 3분) |
| `disk-check` | health 서비스의 `ExecStartPre` | health 앞부분과 같은 저장소 여유 검사만 실행한다. 복구가 필요한 중단 기록이 있어도 막히지 않는다 | 3분 |
| `cvd-prune` | 수동만(`python -m ops.cvd_retention prune`) | 롤백 창이 끝난 뒤 이전 운영 설정의 CVD 세대를 정리한다. 남길 run id를 `--keep`으로 명시하고 이전 state의 완료 기록으로 검증한 세대만 제거한다 | 예약 없음 |
| `restore-check` | 매월 1일 04:30 | 격리 DB의 스키마·테이블 수·첨부 해시·필드 암호문 인증 | 2시간 |
| `cvd-refresh` | 매일 05:00 | 서명 DB가 4일 이상이면 원래 앱 소스로 API 이미지만 재빌드 후 검사·승격 | 1시간 |
| `recover` | 명시적 실행 | 중단 기록과 실제 소유 리소스 대조, 필요한 복귀/장부 기록 | 10분 |

타이머는 `Persistent=true`이며 최대 120초 분산 지연을 둔다. 프로젝트당 하나의 파일 잠금으로 작업을
직렬화한다. 겹친 작업은 종료 코드 75를 반환하고 예약 서비스가 60초 뒤 재시도한다. 일반 실패는 종료 코드
1이며 자동 성공으로 바꾸지 않는다. 하위 프로세스 제한과 systemd 전체 제한을 함께 적용한다. 강제 종료 시
Docker 컨테이너가 남을 수 있으므로 다음 변경 작업은 중단 기록을 먼저 확인한다.

사용자 manager가 시작되지 않으면 타이머도 실행되지 않는다. 특히 `Linger=no` 환경의 로그인 전 부팅,
Windows/WSL 자동 시작, PC 종료 중 가용성은 이 기능으로 보장하지 않는다. 실제 서비스 재시작과 실제
호스트 재부팅은 별도 인수 항목이다. `enable-linger`나 호스트 시작 설정을 자동 적용하지 않는다.
외부 알림 서비스나 외부 백업 위치도 추가하지 않는다. journal과 `latest-*.json`이 현재 상태를 보여준다.

## 소스와 파일 준비

운영 코드를 포함한 깨끗한 커밋의 별도 checkout에서 실행한다. `operator_source_commit`은 그 checkout의
정확한 40자리 Git SHA다. 배포 manifest의 `source_commit`은 실제 API·웹·APK 앱 소스 SHA이며 둘이
달라도 된다. 매 작업은 운영 checkout의 HEAD와 변경 없음, 배포 manifest의 hash와 렌더 결과를 검증한다.
이미지는 OCI revision/role, linux/amd64, UID 10001 및 이미지 내부 소스 JSON을 확인한다.
새 helper 파일은 운영 커밋에서 추출해 SHA로 묶은 읽기 전용 mount로 전달한다. 기존 앱 이미지의 소스
표시나 `ops.backup` 구현을 새 운영 커밋인 것처럼 바꾸지 않는다.

설정은 다음 **필드만** 가진 JSON이다. 아래 값은 예시 경로이며 실제 준비된 경로와 digest로 교체한다.
비밀번호, age identity, 필드 키 원문은 이 JSON에 넣지 않는다.

```json
{
  "format": 1,
  "project": "sallimbook-prod",
  "operator_source_commit": "0000000000000000000000000000000000000000",
  "deployment_directory": "/PRIVATE/deployment/v004",
  "deployment_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "state_directory": "/PRIVATE/automation-state/sallimbook-prod",
  "backup_directory": "/PRIVATE/automation-backups/sallimbook-prod",
  "backup_service_file": "/PRIVATE/automation-credentials/service.conf",
  "backup_recipient_file": "/PRIVATE/automation-credentials/recipient.txt",
  "restore_directory": "/PRIVATE/automation-restores/sallimbook-prod",
  "restore_identity_file": "/PRIVATE/automation-credentials/identity.txt",
  "build_directory": "/PRIVATE/automation-builds/sallimbook-prod",
  "sdk_directory": "/TOOLS/android-sdk",
  "java_home": "/TOOLS/jdk21",
  "python_executable": "/TOOLS/api-venv/bin/python",
  "uv_executable": "/TOOLS/bin/uv"
}
```

- 설정 파일은 실행 사용자 소유 0600 또는 0400, state/build 디렉터리는 실행 사용자 소유 0700이다.
- backup/restore/document 디렉터리는 컨테이너 UID 10001 소유 0700이다. backup 서비스·recipient·restore
  identity·runtime field-keyring 파일도 UID 10001 소유 0600 또는 0400으로 운영자가 미리 준비한다.
  도구가 기존 디렉터리의 소유권을 바꾸거나 키를 생성·교체하지 않는다.
- 네 개 저장소 디렉터리의 마지막 이름은 `project`와 같고, 서로 또는 runtime/source 디렉터리와 겹치지
  않는다. 자격 파일은 이 네 디렉터리 밖에 둔다. symlink, 상위 경로 이동, 공백과 systemd 보간 문자는
  허용하지 않는다. state/build와 backup/restore는 소유자가 다르므로 같은 디렉터리를 공유하지 않는다.
- PostgreSQL 서비스 파일은 `[sallimbook]` 다음에 공백 없는 `key=value`로 쓴다. host=db, port=5432,
  dbname=sallimbook_prod, user=sallimbook_app, password, sslmode=disable이 필요하다. 현재 prod/staging
  Compose의 DB 이름은 모두 `sallimbook_prod`이고 프로젝트별 DB 네트워크/볼륨으로 분리한다.
  ConfigParser의 기본 `host = db` 출력은 libpq와 호환되지 않으므로 사용하지 않는다.
- recipient 파일은 age 공개 수신자 한 개, identity 파일은 별도로 보관한 복원 identity다. 자동 백업에는
  identity/keyring을 mount하지 않는다. 실제 source 백업에는 키·CVC·서명키·Tailscale 상태를 넣지 않는다.
- Docker는 `/var/run/docker.sock`의 로컬 daemon만 사용한다. worker에는 Docker socket을 mount하지
  않는다. 이 소켓에 접근하는 호스트 운영 사용자는 Docker의 관리자 신뢰 경계 안에 있다.

## 생성, 검증, 설치, 활성화

다음 명령의 Python은 설정에 적은 실행 파일을 사용한다. 설정 hash는 준비한 파일 바이트의 SHA-256이다.
경로·hash·소스 SHA를 바꿀 때는 새 설정과 새 예약 파일을 검토한다. 활성 unit이 참조하는 설정 파일이나
운영 checkout을 제자리 수정하지 않는다.

```sh
python -m ops.automation validate /PRIVATE/automation.json --sha256 CONFIG_SHA256
python -m ops.schedule render /PRIVATE/automation.json --sha256 CONFIG_SHA256 --output /PRIVATE/schedule-v001
python -m ops.schedule validate /PRIVATE/schedule-v001
python -m ops.schedule install /PRIVATE/schedule-v001
python -m ops.schedule activate /PRIVATE/schedule-v001
```

`validate`는 파일 hash, exact unit 내용, 운영 소스 및 `systemd-analyze --user verify`를 검사한다.
`install`은 사용자 unit 검색 경로의 기존 같은 이름 파일/drop-in/활성 링크가 있으면 거부한다. 새 9개
unit 파일과 health의 디스크 검사 drop-in 1개(`PROJECT-health.service.d/10-disk-check.conf`, 템플릿
버전 주석 포함)만 배타적으로 생성하고 `daemon-reload`한다. drop-in은 `render`가 만들어 `schedule.json`의
해시에 포함되며 `validate`가 내용과 디렉터리 구성을 검사한다. 서비스나 타이머를 시작하지 않는다.
`activate`는 설치 파일과 drop-in이 렌더 그대로인지, systemd가 로드한 drop-in(`DropInPaths`)이 정확히
그 하나뿐인지 다시 확인한 뒤 전용 startup 1개와 timer 4개만 `enable --now`한다. 다른 drop-in이 붙은
unit은 거부한다. 부분 실패 시 이번에
시도한 전용 unit만 disable/stop하며 한 unit의 정리가 실패해도 나머지 모두 정리를 시도한다.
`activation-failed.json`에 각 정리 결과와 남은 unit을 기록한다. 원인을 해결한 뒤 명시적 `activate`를
재시도할 수 있다. Compose 데이터·볼륨·이미지를 삭제하지 않는다.

startup의 SDK/APK preflight를 통과해야 나머지 예약 서비스가 시작된다. 이미 준비한 앱 배포가 바뀌면
기존 baseline 설정과 충돌하므로 최종 배포 후 해당 manifest에 연결한다. 새 앱 소스로 운영 설정을
전환할 때는 이전 중단 작업부터 해결하고 새 운영 state/config/schedule을 사용한다. 이전 장부와 실제
백업은 보존한다. 기존 unit 교체는 별도 운영 절차이며 `install`이 덮어쓰지 않는다.

수동 실행도 같은 설정·잠금·장부를 사용한다.

```sh
python -m ops.automation run /PRIVATE/automation.json --sha256 CONFIG_SHA256 --task backup
python -m ops.automation run /PRIVATE/automation.json --sha256 CONFIG_SHA256 --task health
python -m ops.automation run /PRIVATE/automation.json --sha256 CONFIG_SHA256 --task restore-check
python -m ops.automation run /PRIVATE/automation.json --sha256 CONFIG_SHA256 --task cvd-refresh
```

## 백업, 격리 복원과 중단 복구

백업 worker는 non-root/read-only/cap-drop ALL로 전용 DB 네트워크에만 참여한다. 자격과 원본 첨부는
읽기 전용 mount다. 완료 archive를 실제 재해시한 후 `.automation-<runUUID>.json`에 기존 6필드 receipt를
남긴다. 호스트는 별도 UID 소유 state/backups 장부에 fsync한 다음 worker의 `backup-ack`로 해당 임시
표시만 지운다. 중단된 표시가 있으면 보존 도구가 백업을 보호한다. 자동 삭제나 외부 복제는 실행하지
않는다. health는 archive 존재/크기/완료 receipt를 확인하며 매시간 전체 해시를 다시 읽었다고 주장하지
않는다. 전체 해시는 백업 완료·중단 복구·복원 전에 확인한다.

복원은 run UUID마다 새로운 내부 네트워크, PostgreSQL 볼륨, 임시 계정 비밀번호를 사용한다. 비밀번호는
UID 10001 worker가 private 파일에 생성하며 Docker argv·로그에 원문을 넣지 않는다. PostgreSQL의 초기
`postgres` DB에서 실제 대상 `sallimbook_<uuid>_restorecheck`를 `TEMPLATE template0`으로 생성한다.
운영 DB 자격은 복원 worker에 전달하지 않고 API·웹·Tailscale 노드·공개 포트도 연결하지 않는다.

기존 `ops.backup.restore`를 실행한 뒤 읽기 전용 repeatable-read 트랜잭션에서 실제 스키마·테이블 수·첨부
해시와 `ops.recovery.check_ciphertexts`의 필드/문서 인증 복호화를 검증한다. 성공 시
`restore_directory/<runUUID>/check/restore-integrity.json`을 배타적으로 생성한다. 내용은 다음과 같다.

```text
format, status=restored-integrity-verified, backup_id, archive_sha256,
restored_at, verified_at, restore_manifest_sha256, restore_receipt_sha256,
checks={schema:true, table_counts:true, objects:true, field_ciphertexts:true}
```

`restore.json`과 `backup-manifest.json` 바이트 hash를 묶고 검증 도중 바뀌면 실패한다. 결과에는 복호화
평문·고객 ID·행 수를 출력하지 않는다. `QUARANTINE`은 유지한다. 이는 사용자 보관함 복구·두 기기 확인·
세션 철회·RPO 손실 수용·운영 승격을 증명하지 않는다. 정식 재해 복구는 기존 recovery 인수 절차를 따른다.
성공하면 임시 DB 볼륨을 제거한다. 실패하면 DB 볼륨과 복원 디렉터리를 보존하고 컨테이너/네트워크만
제거한다. 삭제 전에는 project/run/operator-source 소유 label을 확인한다.

state/runs/<UUID>에는 started, 단계별 기록, finished가 남는다. 비정상 종료 또는 정리 실패가 있으면
`health`도 `RECOVERY_REQUIRED`로 실패하고 새로운 변경 작업은 중단한다. 같은 운영 소스/설정으로 다음
명령을 실행한다.

```sh
python -m ops.automation run /PRIVATE/automation.json --sha256 CONFIG_SHA256 --task recover
```

복구는 장부에 기록된 소유 컨테이너/네트워크만 정리하며 실패 복원 볼륨을 지우지 않는다. 백업 완료
표시가 있으면 실제 archive 해시를 재검증해 장부를 보완한다. worker가 완료 표시를 쓴 뒤 응답을
잃은 경우도 복구 대상으로 유지하며, 컨테이너 정리 성공만으로 백업 미생성을 추정하지 않는다. 표시가 없거나 partial 파일만 있으면 성공
백업으로 기록하지 않고 새 백업은 새 UUID를 사용한다. 형식/해시가 틀린 표시는 자동 무시하지 않는다.
명령 실패 로그에는 고정 오류 코드만 출력한다. journal 원문에 비밀이 포함된 외부 명령 stderr를 남기지
않는다. 비정상 설치로 남은 unit은 byte hash를 대조해 운영자가 정리해야 하며 재설치가 덮어쓰지 않는다.

## 서명 DB 갱신의 승격 조건

배포 앱 커밋의 `git archive`로 API context만 만들고 frozen uv lock을 사용한다. 현재 UTC 날짜를
`SALLIMBOOK_CVD_REFRESH`로 전달해 실제 CVD 다운로드 빌드 단계를 갱신한다. 엄격한 umask에서도 이미지
내 공개 설정·소스 디렉터리는 UID 10001이 읽을 수 있는 권한을 유지한다. 웹 빌드나 APK 재서명은 하지
않는다. candidate 이미지의 실제 소스 marker와 별도 network-none scanner PING/VERSIONCOMMANDS,
고정 엔진·INSTREAM·4일 미만 CVD를 확인한다.

`docker build --iidfile` 결과는 저장소 digest가 아닌 로컬 image ID이므로 전체 `sha256:` ID를 직접 고정한다. 저장소 이름과 합성하지 않는다. candidate worker는 이미지 안에 포함된 `ops.deploy.validate`로 새 manifest를 검증하여, 이후 그 이미지의 `ops.backup`이 같은 manifest를 처리할 수 있는지도 승격 전에 확인한다. 전체 로컬 ID를 지원하지 않는 과거 앱 소스는 여기서 거절되며, 해당 지원을 포함한 앱을 먼저 배포해야 한다. 운영 helper가 과거 이미지의 백업 구현이나 정책을 몰래 교체하지 않는다. [Docker build의 iidfile 정의](https://docs.docker.com/reference/cli/docker/buildx/build/#iidfile)를 따른다.

새 manifest에서는 API 이미지 참조만 바꾼다. 웹·APK·앱 소스·서명·origin은 그대로 유지하며 APK를 복사한
새 배포 디렉터리도 preflight한다. 이후 전용 scanner·inspector·API만 이 순서로 갱신하고(inspector는 API와 같은
이미지를 쓴다) 실제 health/신선도를 확인한 다음 state/active-deployment.json을 atomic rename+fsync한다.
실패하면 이전 scanner·inspector·API로 복귀한다. 중단된 승격의 복구도 같은 세 서비스를 다시 올린다. pointer
rename은 끝났지만 fsync 결과가 불확실하면 새 서비스를 임의로 되돌리지 않고 `PROMOTION_COMMIT_UNCERTAIN`
및 복구 필요 기록을 남긴다.

새 CVD 빌드 전에는 기준 배포, 현재 배포와 직전 rollback 배포를 보호하고 이전에 **완료된 자체 CVD
세대**만 정리한다. 새 이미지에 project/run/operator-source/kind 소유 label을 붙이고, 승격 검사 후
세대 디렉터리의 전체 파일 SHA-256·권한·정확한 tag/image ID를 private receipt로 묶는다. 삭제는 같은
앱/운영 소스, 완료 장부, 단일 링크 파일과 디렉터리 소유권, receipt 및 실제 이미지 label을 모두 재확인한다.
다른 manifest가 참조하거나 다른 RepoTag가 붙은 이미지, 실행 중이거나 정지한 컨테이너가 사용하는
이미지는 보존한다. 정확한 자체 tag에 `docker image rm --no-prune TAG`만 실행하며 image ID 삭제,
force 삭제, 전역 prune은 하지 않는다. ID가 남거나 untag 결과가 불확실하면 빌드 파일도 보존한다.

receipt 없는 과거 산출물, 미완료/변조/공유/symlink/hardlink 산출물은 삭제하지 않는다. 이 항목과
orphan 자체 image tag까지 합쳐 6세대가 남으면 새 빌드를 중지한다. 정상 갱신은 현재·직전 세대를
보존하며 새 세대를 만든다. BuildKit의 공유 cache를 강제 정리하지 않으므로, 새 빌드 전에 build와
Docker 이미지 파일시스템의 여유가 각각 2GiB 이상인지 확인한다. health도 두 저장소의 여유를 기록하며
1GiB 미만이면 실패한다. Docker Desktop처럼 daemon 저장소가 호스트에서 보이지 않는 경우에도
network-none/read-only/UID 10001 worker가 이미지 루트의 statvfs를 조회한다.

기준 이미지·현재/직전 APK·운영 백업·사용자 소스는 이 정리 대상이 아니다. 제한에 걸린 불확실한
산출물은 운영자가 장부와 참조를 대조해 처리해야 하며 자동으로 삭제 범위를 넓히지 않는다.

## 검증 범위

합성 단위 시험 명령:

```sh
python3 -m unittest tests.operations.test_automation tests.operations.test_schedule tests.operations.test_cvd_retention -v
python3 -m unittest discover -s tests/operations -v
ruff check --config services/api/pyproject.toml ops/automation.py ops/automation_runtime.py ops/automation_worker.py ops/restore_check.py ops/schedule.py ops/build_context.py tests/operations/test_automation.py tests/operations/test_schedule.py
```

시험은 실제 파일 권한·hash·잠금·프로세스 timeout, 비밀 출력 차단, libpq 필수 필드, template0 생성 요청,
복원 증거 실패 조건, 소유 리소스 정리, candidate 실패/rollback/불확실한 pointer commit, 예약 파일 충돌과
부분 활성화 실패를 확인한다. 외부 DB/Docker/systemctl 변경은 mock으로 차단한다. 이 단위 시험 통과가
실제 예약 활성화·새 이미지 빌드·장기 운영·호스트 재부팅 성공을 뜻하지 않는다. 실제 운영 실행은 최종
배포 소스/manifest/config SHA, 시각, 명령 결과, 장부 경로를 별도 인수 기록에 남긴다.

### 2026-10-18 구현 검증 기록

- 실제 `systemd-analyze --user verify`: 생성된 service 5개/timer 4개, exit 0. 설치·활성화는 실행하지 않았다.
- 실제 배포 앱 소스 `f017d8f61bfeae2304f0109d6f62c9fd13643212`의 git archive와 frozen uv export:
  umask 0077에서 API context 파일 144개 생성, 모든 파일/하위 디렉터리의 읽기·탐색 권한과 소스 marker 확인.
  웹 빌드와 이미지 빌드는 수행하지 않았다.
- 운영 코드 `f2f7f14ef0bc4c47d6037d4dd79f3f74df8e12a1`과 위 앱 소스의 기존 API 이미지로
  `tests.operations.automation_integration` 실행: 실제 worker 백업·archive hash·호스트 장부·ack·
  `Runtime.restore_check` 성공, 총 12.564초. 스키마/테이블 수/첨부/필드 암호문 검사가 모두 통과했다.
- 합성 DB는 백업과 무결성 helper가 읽는 5개 테이블과 계좌번호·보험번호·첨부 각 1건으로 구성했다.
  실제 앱의 암호화 함수를 사용했으며, 전체 앱 마이그레이션·API 권한·보관함·두 기기 복구 시험은 아니다.
- 최초 시험은 새 fixture 소유권을 UID 10001로 넘긴 뒤 불필요하게 chmod해 준비 단계에서 실패했다.
  이미 설정한 private 권한을 유지하도록 harness를 수정한 다음 새 디렉터리에서 전체 시험이 통과했다.
  두 시도의 project/run label별 컨테이너·네트워크·볼륨 목록이 모두 비어 있음을 실제 확인했다.
- 운영 프로젝트·DB·키는 읽거나 변경하지 않았다. 시험 산출물은 저장소 밖 private 디렉터리에 보존했다.
  로컬 검증은 원격 CI, 예약 활성화, 장기 운영 또는 재부팅 성공을 대체하지 않는다.

재현할 때는 깨끗한 운영 checkout, 검증된 앱 이미지/소스 쌍, 공식 age-keygen 1.3.2와 새 저장소 밖
디렉터리를 지정하고 다른 Docker/DB 시험과 실행 구간을 조율한다. 기존 경로를 덮어쓰지 않는다.

```sh
python3 -m tests.operations.automation_integration \
  --image API_TAG_AT_SHA256 \
  --app-source APP_COMMIT_SHA \
  --age-keygen /TOOLS/age-keygen \
  --output /PRIVATE/new-synthetic-automation-check
```

이 harness는 명시적 실행만 허용하며 일반 단위 시험 discovery에 포함되지 않는다. source DB도 새로운
내부 네트워크와 tmpfs에서 만들고, 실제 운영 Compose를 호출하지 않는다. helper가 성공 후 남기는
`integration-result.json`과 각 run의 private 장부를 검토한다. 실패한 restore 볼륨은 자동 삭제하지 않는다.

PR 검토 후 로컬 이미지 참조를 보완했다. 실제 기존 API 이미지에서 시험 전용 레이어를 빌드하고 iidfile/inspect ID 일치를 확인한 뒤, 그 전체 ID로 network-none·UID 10001·읽기 전용 Compose 컨테이너를 실행해 통과했다. 운영 DB/키는 연결하지 않았으며 시험 컨테이너와 전용 태그를 정리했다. 현재 daemon은 RepoDigest도 1개 제공하므로 이 실행을 다른 Docker 저장 방식에서의 기존 오류 재현이라고 주장하지 않는다. 단위 회귀는 축약 ID 거절·전체 ID 보존·candidate manifest의 앱 내 정책 호환·CVD 승격 후 정확한 이미지 ID를 확인한다. 실제 CVD 다운로드와 운영 승격 전체는 이 작은 참조 시험과 구분한다.


### CVD 보존/백업 제한 후속 검증 (2026-10-18)

- 백업 전체 제한은 2700초이며 worker의 1800초 외에 git/네트워크/이미지/helper/ack/실패 정리 시간을
  포함하는 회귀 시험을 추가했다. 생성된 systemd service에도 `TimeoutStartSec=2700`을 확인했다.
- 합성 단위 시험은 정확한 자체 tag 삭제, 기준/현재/직전 및 다른 manifest 참조 보호, 공유 태그,
  정지 컨테이너, 소유 label 불일치, 파일 변조·symlink·hardlink·미완료 기록 보존, untag 불확실성,
  6세대 제한과 build/daemon 공간 부족 차단을 확인한다.
- 실제 Docker의 새 scratch 이미지 2개와 private 시험 디렉터리로 자체 tag/tree 정리를 확인했다.
  외부 시험 tag 또는 정지 시험 컨테이너가 붙어 있으면 보존했고, 그 시험 참조를 제거한 뒤에만 정리했다.
  image ID rm, force, 전역 prune은 호출하지 않았다. 모든 시험 tag/컨테이너를 정리했다.
- 별도 실제 API v4 이미지의 network-none/read-only/UID 10001 컨테이너에서 새 `storage` worker가
  daemon 파일시스템 여유 약 632GiB를 반환했다. 새 helper 파일의 hash를 묶은 합성 bundle 시험이며,
  운영 예약 활성화나 CVD 다운로드·승격 전체의 증거는 아니다. 운영 DB·백업·키는 접근하지 않았다.

### CLI 진입점의 복원 준비 재시도 수정

`python -m ops.automation run ... --task restore-check`에서 PostgreSQL의 첫 `pg_isready`가
아직 준비되지 않았음을 반환하면, 90초 동안 재시도해야 한다. 기존 모듈 실행은 `__main__`에 정의된
`Runner`와 `AutomationError`를 사용했지만, runtime은 `ops.automation.AutomationError`를 import했다.
이 두 클래스가 달라 초기 `COMMAND_FAILED`를 재시도 처리에서 잡지 못하고 즉시 실패했다.
`import ops.automation; ops.automation.run(...)` 진단에서는 같은 클래스이므로 재현되지 않았다.

CLI 진입점은 canonical `ops.automation.main`에 위임하여 설정 검증·Runner·runtime의 예외 타입을
일치시킨다. PostgreSQL 준비 기한, 백업/복원 로직, 자격 mount, 소유 리소스 정리 정책은 바꾸지 않는다.
준비 기한까지 계속 실패하면 `RESTORE_DATABASE_UNAVAILABLE`로 실패하고 격리 볼륨을 보존한다.

[CLI 회귀 시험](../../tests/operations/test_automation_cli.py)은 별도 Python subprocess의 실제
`-m ops.automation`과 import형 진입점을 모두 호출한다. 설정과 Docker 응답만 합성 값으로 대체하고
실제 main/run/Runner/restore_check를 유지한다. 첫 준비 확인이 exit 2, 다음 확인이 exit 0일 때
수정 전 `-m`은 한 번 만에 실패하고 import형은 성공하는 것을 재현했다. 수정 후 둘 다 재시도·복원 단계·
성공 정리에 도달한다. 계속 준비되지 않는 경우 실패 유지, 볼륨 보존과 고정 오류 코드만의 출력을 확인한다.

```sh
python -m unittest tests.operations.test_automation_cli -v
python -m unittest discover -s tests/operations -v
```

이 회귀 자체는 실제 Docker나 고객 DB를 실행하지 않는다. 운영 고정 checkout/config는 제자리 수정하지
않고 검토된 새 운영 소스로 전환해야 한다. 이전 실패의 격리 볼륨과 장부는 보존한다.

### 실제 명령행 재검증 — 2026-10-18

앱 배포 소스 `fb16191f2613bf757aadb2e50a651f5be08fdb61`(0.1.3/versionCode 4)은 유지하고,
운영 코드는 새 고정 checkout `a69d3abc5557b7140f193b86ae12c8b63b4d9f0a`로 분리했다.
새 설정의 SHA-256은 `d028dd57d3004589049be7cd572c81220dee58d3b1740330560d5a82a0e5790d`다.
기존 자격 파일을 사용했으며 새 state/backup/restore/build 경로를 준비했다. 기존 백업·실패 볼륨·
장부·운영 checkout을 덮어쓰지 않았다. 모든 작업은 실제 `python -m ops.automation`으로 실행했다.

| 작업 | UTC 완료 시각 | 결과·소요 시간 |
| --- | --- | --- |
| startup | 04:50:51 | 6개 서비스와 실제 scanner 정상, 6.486초 |
| backup | 04:50:53 | 암호화 archive 재해시·별도 장부·ack 완료, 1.821초 |
| restore-check | 04:50:58 | 실제 백업의 새 격리 DB 복원·무결성 확인, 5.543초 |
| health | 04:51:00 | 서비스·scanner·최근 백업·저장소 여유 확인, 2.218초 |
| cvd-refresh | 04:51:06 | 실제 서명 DB가 4일 미만이므로 `refresh-not-due`, 5.514초 |

복원 run `b06d18e4-df9f-4bf3-8642-55cbfc5b17f8`의 별도 `restore-integrity.json`에서 schema,
table_counts, objects, field_ciphertexts 네 검사가 모두 true임을 재확인했다. 원문 데이터·행 수·
복호화 값은 보고하지 않았다. 완료한 임시 DB 볼륨·컨테이너·네트워크는 소유를 대조해 정리했다.
이는 서버 백업 무결성 확인이며 사용자의 보관함 키 복구나 실제 두 기기 인수를 뜻하지 않는다.

수정 전 표준 CLI의 두 실패와 import형 진단의 성공은 함께 보존했다. 첫 DB 준비 실패에서 종료되는
증상을 실제 subprocess 회귀로 재현한 뒤 수정했으므로 단순 재시도로 해결됐다고 기록하지 않는다.
CVD 갱신 경로의 이번 실행은 신선도에 따른 보류 확인이며 새 다운로드·이미지 승격 성공이 아니다.
이 표는 수동 명령행 검증 기록이다. 예약 활성화와 재시작의 최신 운영 기록은
[최종 추적 Issue #49](https://github.com/jihoon22-lee/SallimBook/issues/49)에 연결한다.
