# 격리 운영·백업·복원·서명 도구

연결: SB-036/#45, SB-037/#46, SB-038/#47, SB-040/#49 · R-02, R-20, R-21.

이 문서는 `ops/` 도구의 실행 경계와 운영 인수 절차다. 기존 WSL 서버·컨테이너·DB·호스트 Tailscale 설정은 변경하지 않는다. [ADR 0007](adr/private-network-and-app-identity.md)에 따라 현재 PC/WSL이 중단되면 SallimBook도 중단된다. #45의 “개발 PC 종료와 무관한 접근” 조건은 이 승인된 운영 결정과 충돌하므로 PC/WSL 재시작 후 복귀 검증으로 수정해야 한다.

## 1. 현재 실행 범위

| 도구 | 동작 | 실행하지 않는 것 |
|---|---|---|
| `python3 -m ops.deploy MANIFEST NEW_DIRECTORY` | 공개 배포 manifest를 검사하고 Compose/Caddy/Serve/Digital Asset Links/Android 설정 생성 | 컨테이너 시작, 노드 등록, 키 생성 |
| `python3 -m ops.build_context NEW_DIRECTORY --commit SHA` | 깨끗한 commit의 최소 이미지 빌드 입력 생성, frozen 의존성 및 웹 빌드 | 이미지 게시, 운영 배포 |
| `uv run --project services/api python -m ops.preflight CONFIG_DIRECTORY` | 생성 설정·전용 DB·파일 소유권·이미지 확인, APK가 있으면 --sdk로 실제 서명/ID/버전 검사 | 서비스 시작, 노드 등록 |
| `… -m ops.database provision …` / `verify-runtime` | 전용 migration/admin 역할과 제한된 API 역할 분리·권한 확인 | 업무 스키마 변경, 기존 역할 비밀번호 덮어쓰기 |
| `uv run --project services/api python -m ops.backup create …` | 일관된 DB/첨부 스냅샷을 age로 암호화하고 완료 receipt 생성 | 서버 암호화키·서명키·Tailscale 상태·CVC 포함 |
| `… -m ops.backup restore …` | 빈 전용 `*_restorecheck` DB와 새 디렉터리로 복원 | 기존 DB 덮어쓰기, API 시작, 운영 승격 |
| `… -m ops.recovery prepare …` | 격리 복원 DB의 인증 폐기와 두 계정 비밀번호 재설정 | 보관함/금전/진료 기록 삭제 |
| `… -m ops.recovery verify …` | 새 인증·키 회전·첨부 AEAD·운영 인수 증거 검사 | QUARANTINE 제거, 서비스 시작 |
| `python3 -m ops.release …` | release 빌드·보안 검사·기존 외부키 서명·서명 확인 | 서명키 생성, 업로드, 실기기 설치 |
| `python3 -m ops.cvd_retention prune …` | 롤백 창이 끝난 뒤 이전 운영 설정이 남긴 검증된 CVD 세대 정리(`--keep` 필수, `--dry-run` 제공) | 현재·직전·기준선 세대, 검증을 통과하지 못한 세대의 삭제 |

운영 도구는 비밀 값이나 원본 SQL/진료 내용을 출력하지 않는다. 실패 시 원본 예외를 일반 로그로 내보내지 않는다. 자세한 원인은 비공개 터미널에서 조사하고 비밀 경로·값·원문을 이슈/채팅에 복사하지 않는다.

## 2. 이미지와 공개 배포 manifest

이미지는 저장소의 버전+SHA-256 digest 또는 로컬 빌드의 전체 `sha256:` 이미지 ID(64자리 hex)로 고정한다. `latest`, 변경 가능한 태그 단독, 축약 ID는 거절한다. 로컬 image ID를 저장소 digest처럼 태그 뒤에 붙이지 않는다. 로컬 ID는 해당 Docker daemon에 이미지가 있어야 사용 가능하며 preflight가 실제 플랫폼·소스·역할을 확인한다. 공식 registry에서 확인한 기본값은 Caddy 2.11.7, Tailscale 1.104.1, PostgreSQL 18.6이다. Python 3.14.7, 날짜 고정 Debian 패키지 및 ClamAV 1.4.6은 기존 문서 검사 도구의 검증 입력을 재사용한다. age 1.3.2는 공식 release SHA-256을 검사한다.

새 공개 JSON manifest는 다음 필드를 모두 가져야 한다. 실제 노드와 서명 인증서가 확정된 후 값을 입력한다. 아래 값은 형식 설명이며 운영 주소·서명 인증서가 아니다.

```json
{
  "format": 1,
  "project": "sallimbook-prod",
  "fqdn": "DEDICATED_NODE.ACTUAL_TAILNET.ts.net",
  "certificate_sha256": "COLON_SEPARATED_UPPERCASE_SHA256",
  "api_image": "PRIVATE_REGISTRY/API:VERSION@sha256:VERIFIED_DIGEST",
  "web_image": "PRIVATE_REGISTRY/WEB:VERSION@sha256:VERIFIED_DIGEST",
  "runtime_directory": "/srv/sallimbook/sallimbook-prod",
  "version_code": 2,
  "version_name": "0.1.1",
  "source_commit": "EXACT_40_CHARACTER_REVIEWED_COMMIT"
}
```

선택 필드 `setup_identity_sha256`은 최초 사용자의 인증된 `Tailscale-User-Login` 헤더 값을 UTF-8로 인코딩한 SHA-256 64자리 hex다. 생략하면 모바일/웹 자체 초기 등록은 비활성화되며 기존 format 1 manifest도 그대로 유효하다. 빈 문자열·null은 허용하지 않는다. renderer는 설정된 경우에만 API에 `SALLIMBOOK_SELF_SETUP_IDENTITY_SHA256`과 `SALLIMBOOK_SELF_SETUP_PROXY_HOST=node`를 함께 주입한다. proxy hostname은 manifest에서 변경할 수 없다. 실제 로그인 이름을 manifest·Git·로그에 기록하지 않는다. 이 digest는 비밀번호나 단독 인증 토큰이 아니며 공개 설정에 들어간다. `api.env`에는 이 값을 넣을 수 없다.

```bash
python3 -m ops.build_context /PRIVATE_BUILD_PARENT/NEW_CONTEXT --commit REVIEWED_SHA
docker build --build-arg SALLIMBOOK_CVD_REFRESH=YYYY-MM-DD -t PRIVATE_API_TAG /PRIVATE_BUILD_PARENT/NEW_CONTEXT/api
docker build -t PRIVATE_WEB_TAG /PRIVATE_BUILD_PARENT/NEW_CONTEXT/web
# 게시 대상과 접근권한 확인 후 이미지를 게시하고 registry digest를 manifest에 기록한다.
python3 -m ops.deploy /PRIVATE_CONFIG/deployment.json /PRIVATE_CONFIG/NEW_RENDERED_DIRECTORY
docker compose -f /PRIVATE_CONFIG/NEW_RENDERED_DIRECTORY/compose.json config --quiet
uv run --project services/api python -m ops.preflight /PRIVATE_CONFIG/NEW_RENDERED_DIRECTORY
```

`build-inputs.json`은 commit, 원본 API lock SHA와 모든 빌드 입력 해시를 기록한다. 두 이미지 context에는 같은 clean archive SHA와 api/web 역할을 담은 `source-revision.json`을 추가하고 생성 Dockerfile에 literal OCI revision/역할 label을 넣는다. 운영자가 revision build-arg를 따로 입력하지 않는다. `preflight`는 digest로 선택한 실제 로컬 API/웹 이미지의 label이 manifest의 source_commit 및 해당 역할과 모두 같은지 검사하며, 누락·다른 revision·API/웹 바꿔치기는 거부한다. API와 웹은 같은 검토 commit에서 함께 빌드한다. 이 metadata 확인은 이미지 게시자의 암호학적 서명 검증을 의미하지 않는다. API는 `uv export --frozen --no-dev --no-emit-project`의 hash-pinned requirements를 사용한다. 이미지/APK 빌드는 임시 `git archive` checkout에서 수행하므로 원래 작업 트리의 ignored `.env`, 키, 첨부, public 디렉터리의 미추적 파일을 가져가지 않는다. 빌드 명령은 운영자 환경을 허용 목록(`PATH`, `HOME`, `JAVA_HOME`, `ANDROID_HOME`, `GRADLE_USER_HOME`, `LANG`, pnpm 저장소 변수) 외에는 상속하지 않으므로 `VITE_*`도 들어오지 않고, 의존성 설치는 `pnpm install --frozen-lockfile --ignore-scripts`로 install 스크립트를 실행하지 않는다. 최종 Docker context에는 필요한 API/웹 빌드 입력만 넣는다. API 이미지의 PostgreSQL client는 같은 공식 이미지의 loader/공유 라이브러리와 함께 격리하여 API Python의 시스템 라이브러리를 덮어쓰지 않는다.

`write_config`는 운영자 전용 최상위 출력 디렉터리를 0700으로 유지한다. 컨테이너에 mount하는 공개 설정의 `node/`, `public/`, `public/.well-known/`, `downloads/`는 0755, 생성 설정 파일은 0644로 명시하여 `umask 077`에서도 cap-drop된 node와 UID 10001 Caddy가 읽을 수 있게 한다. 비밀번호·keyring·서명키 등 비밀 파일은 이 출력 디렉터리에 생성하지 않으며 기존 owner-only 권한을 유지한다.

ClamAV DB는 공식 서명 DB만 빌드 시 내려받고 7일을 넘으면 검사에 실패한다. scanner와 API의 Compose healthcheck는 실제 Unix PING과 VERSIONCOMMANDS, 고정 엔진·INSTREAM 지원·DB freshness를 기존 업로드 검사와 같은 함수로 확인한다. API healthcheck는 DB HTTP readiness도 확인하며, scanner가 healthy가 된 뒤 API를 시작하고 API가 healthy가 된 뒤 웹을 시작한다. 실행 중 scanner 중단·stale 상태는 API container를 unhealthy로 바꾼다. 기존 `/api/v1/ready`의 DB 검사 계약은 유지하며 운영 준비 상태는 Compose health를 기준으로 확인한다. unhealthy 표시는 서비스를 자동 중지시키는 기능이 아니며 첨부 업로드는 기존 검사에서도 실패 시 거부한다. `SALLIMBOOK_CVD_REFRESH`를 실제 갱신일로 바꿔 새 이미지로 배포한다. 오래된 이미지의 태그만 다시 붙여 검사 실패를 우회하지 않는다.

### 문서 검사기 배포와 되돌리기

문서 검사기(inspector)를 처음 배포하거나 되돌릴 때는 **자동화의 운영 코드(`operator_source_commit`)와 배포 고정값(`deployment_directory`·`deployment_sha256`)을 함께 바꾸고 함께 되돌린다.** 서비스 집합이 6개에서 7개로 바뀌므로 둘 중 하나만 바꾸면 매시간 `health`와 매일 `cvd-refresh`가 `SERVICE_SET`으로 실패한다. 검사기 변경 자체에는 마이그레이션이 없다. 함께 배포하는 릴리스의 스키마가 바뀌면(새 이미지의 `REQUIRED_SCHEMA_REVISION`이 운영 DB와 다르면) 아래 [스키마가 바뀌는 업그레이드](#스키마가-바뀌는-업그레이드--점검-시간-절차) 절차를 따른다.

배포 전 확인:

1. `free -m`의 가용 메모리가 기존 컨테이너 한도 합계에 inspector 1152MiB를 더한 값보다 큰지 확인한다.
2. 현재 설정으로 `python -m ops.automation run CURRENT.json --sha256 CURRENT_SHA256 --task health`가 성공하는지 확인한다. `RECOVERY_REQUIRED`면 같은 운영 소스로 `--task recover`를 먼저 끝낸다.
3. 배포 중 예약 작업이 끼어들지 않게 현재 예약을 멈춘다. 활성 unit은 `systemctl --user list-timers 'PROJECT-*' --all`로 확인하고, 예를 들어 `systemctl --user disable --now PROJECT-startup.service PROJECT-health.timer PROJECT-cvd-refresh.timer`를 실행한다.

배포:

1. 위 절차로 새 이미지와 렌더 디렉터리를 만들고 `docker compose -f NEW/compose.json config --quiet`와 `uv run --project services/api python -m ops.preflight NEW`를 통과시킨 뒤 배포한다.
2. 검사기 변경이 포함된 병합 커밋으로 깨끗한 새 운영 checkout을 만들고, 그 SHA·새 렌더·새 state 디렉터리로 새 자동화 설정 JSON을 만든다. 기존 설정·checkout·state는 고치지 않고 보존한다(되돌리기용).
3. `python -m ops.automation validate NEW.json --sha256 NEW_SHA256` → `python -m ops.schedule render NEW.json --sha256 NEW_SHA256 --output NEW_SCHEDULE` → `python -m ops.schedule validate NEW_SCHEDULE` → 기존 unit 파일 정리(별도 운영 절차, `install`은 같은 이름의 파일·drop-in이 있으면 거부하고 `activate`는 drop-in이 붙은 unit을 거부한다) → **수동으로 만든 health 디스크 검사 drop-in 삭제**: `PROJECT-health.service.d/` 디렉터리(안에 `backup-pause-disk-check.conf`가 있다)를 사용자 unit 디렉터리(`~/.config/systemd/user/`)에서 지우고 `systemctl --user daemon-reload`를 실행한다(`install`은 이 디렉터리가 남아 있으면 `UNIT_ALREADY_EXISTS`로 거부한다) → `python -m ops.schedule install NEW_SCHEDULE` → `python -m ops.schedule activate NEW_SCHEDULE` 순서로 실행한다.
4. `activate`는 9개 unit을 모두 켠다. 백업 유예(2026-10-18 결정, [v1 완료 계획](v1-completion-plan.md))를 유지하려면 바로 `systemctl --user disable --now PROJECT-backup.timer PROJECT-restore-check.timer`를 실행한다. 디스크 검사 drop-in은 다시 만들지 않는다. health가 디스크 검사를 첫 단계로 하므로 백업이 멈춰 있어도 닿는다.
5. 새 설정으로 `--task health`를 수동 실행한다. 백업 유예 중에는 서비스·scanner 검사를 통과한 뒤 `BACKUP_MISSING`(새 state에는 백업 기록이 없다) 또는 `BACKUP_STALE`로 끝나는 것이 정상이다. 그 앞의 `SERVICE_SET`·`SCANNER_STALE` 등으로 실패하면 정상이 아니다. 상태·빌드·Docker·백업·첨부 저장소의 디스크 여유(각각 1GiB 이상)는 health의 첫 단계이므로 백업 기록이 없어도 `DISK_SPACE_LOW`가 `BACKUP_MISSING`보다 먼저 나온다. 디스크 부족은 종료 상태 1이라 예약 서비스가 다시 시도하지 않는다.

배포 후 확인표:

| 확인 | 기대값 |
|---|---|
| `docker compose -f NEW/compose.json ps --all` | 서비스 7개 running, api·db·scanner·inspector healthy |
| `docker inspect --format '{{.HostConfig.NetworkMode}} {{.Config.User}} {{.HostConfig.Memory}} {{.HostConfig.PidsLimit}} {{.HostConfig.Init}}' <inspector 컨테이너>` | `none 10002:10003 1207959552 32 true` |
| 앱에서 인쇄한 합성 영수증 사진 한 장 업로드 | 성공 |
| 다음 예약 `health` | 백업 유예 중에는 `BACKUP_MISSING`/`BACKUP_STALE`(서비스·scanner 통과 뒤), 백업을 재개했다면 성공(`latest-*.json` 또는 journal) |

되돌리기(필요할 때만):

1. 새 예약을 멈춘다(위의 `systemctl --user disable --now` 명령).
2. `docker compose -f PREVIOUS/compose.json up -d --wait --remove-orphans`로 이전 렌더에 되돌린다. `PREVIOUS`는 **이전 state 디렉터리의 `active-deployment.json`이 가리키는 렌더**다. 파일이 없을 때만 이전 설정의 `deployment_directory`를 쓴다. 매일 `cvd-refresh`가 새 렌더를 승격하므로 처음 렌더의 ClamAV DB는 7일이 지나면 clamd가 시작을 거부해 scanner·api·web이 뜨지 않는다. 같은 프로젝트 이름이므로 inspector 컨테이너는 orphan으로 제거되고, 이전 API 이미지는 로컬 워커로 동작한다. 스키마를 올린 뒤라면 먼저 아래 절차의 DB 되돌리기를 끝낸다.
3. 남은 볼륨을 지운다: `docker volume rm PROJECT_inspector_socket`(`PROJECT`는 manifest의 `project`). 다시 배포할 때 새 볼륨이 이미지 디렉터리의 소유권(10002:10003, 0750)을 받는다.
4. 새 unit 파일을 정리한다(별도 운영 절차. 같은 이름의 파일·drop-in이 있으면 `install`이 거부한다). 이전 schedule 디렉터리는 다시 쓰지 않는다. 이미 `install`·`activate`한 기록(`installation.json`·`activation.json`)이 있어 `install`이 `SCHEDULE_ALREADY_INSTALLED`로 거부하고, `render`도 존재하는 출력 디렉터리를 거부한다. **이전 운영 checkout**(이전 설정의 `operator_source_commit`, 청결한 상태)으로 이동해 존재하지 않는 새 경로 `ROLLBACK_SCHEDULE`에 다시 렌더한 뒤 같은 디렉터리로 검증·설치·활성화한다. 렌더는 현재 checkout의 경로와 HEAD를 unit에 고정하므로 다른 checkout에서 실행하면 `validate`가 `OPERATOR_SOURCE_CHANGED`로 실패한다.

   ```bash
   python -m ops.automation validate OLD.json --sha256 OLD_SHA256
   python -m ops.schedule render OLD.json --sha256 OLD_SHA256 --output ROLLBACK_SCHEDULE
   python -m ops.schedule validate ROLLBACK_SCHEDULE
   python -m ops.schedule install ROLLBACK_SCHEDULE
   python -m ops.schedule activate ROLLBACK_SCHEDULE
   ```

   그다음 위 배포 4단계처럼 `activate`가 켠 backup·restore-check 타이머를 다시 끈다. 이전 운영 checkout의 health가 디스크 검사를 첫 단계로 하지 않는 버전(이 변경 이전)이면 백업 유예 중 디스크 검사가 닿지 않으므로, 그 `activate`가 끝난 **뒤에** 기존 수동 drop-in(`PROJECT-health.service.d/backup-pause-disk-check.conf`)을 이전 설정 경로·해시로 다시 설치하고 `systemctl --user daemon-reload`를 실행한다(`activate`는 drop-in이 붙은 unit을 거부하므로 순서를 바꾸지 않는다). 이 변경 이후의 checkout이면 따로 할 일이 없다. 끝으로 이전 설정으로 `--task health`를 실행해 위 5단계와 같은 결과인지 확인한다.
5. 되돌린 경우 문서 검사 격리가 다시 해제된 상태로 기록하고 원인을 조사한다.

### 스키마가 바뀌는 업그레이드 — 점검 시간 절차

새 API 이미지의 `REQUIRED_SCHEMA_REVISION`(`services/api/src/sallimbook/core/database.py`)이 운영 DB와 다를 때 사용한다. 예: 0.1.6(165d46b, `0014_vault`) → `0018_install_device`. API는 시작할 때 마이그레이션하지 않는다. 스키마가 다르면 `/api/v1/ready`가 503이라 api가 healthy가 되지 못하고, web은 api를 기다리므로 사설 사이트가 멈춘다. 아래 명령은 운영자가 실행한다.

**순서 원칙: 서버 먼저 → 확인 → 두 폰 즉시 업데이트.** 그 사이에는 확인 외에 두 폰의 앱과 웹을 쓰지 않는다.
- 0.1.6까지의 APK는 응답에 필드가 추가되면 거부한다. 서버만 올라간 동안 이전 APK의 보험 사건 목록·사건 선택·청구 상세, 설정의 기기 목록과 카드 보관함 화면(기기 목록을 읽는다)이 실패한다.
- APK를 먼저 설치하지 않는다. 새 APK와 이전 서버도 같은 이유로 서로 거부하고, APK는 데이터(Keystore·보관함 등록) 손실 없이 내릴 수 없다.
- 서버가 추가한 응답 필드를 허용·제거하는 APK부터는 이 제약이 다음 릴리스에서 사라진다([브리지 계약 §2](native-bridge-contract.md#응답-호환-서버가-추가한-응답-필드)). 응답 필드를 **제거**하거나 의미를 바꾸는 변경에는 여전히 이 절차가 필요하다.

준비(점검 시간 전):

1. 위 절차로 새 이미지·렌더를 만들고 `docker compose -f NEW/compose.json config --quiet`와 `ops.preflight NEW`를 통과시킨다.
2. release APK를 서명하고(versionCode 증가, 같은 인증서) 새 렌더의 `downloads/`에 넣은 뒤 `--sdk` preflight를 통과시킨다(§7).
3. `free -m`의 가용 메모리를 확인한다(검사기를 처음 배포하면 1152MiB 추가).
4. 마이그레이션용 admin env 파일을 운영자 소유 0600으로 만든다. 한 줄 `SALLIMBOOK_DATABASE_URL=postgresql+psycopg://sallimbook_admin:…@db:5432/sallimbook_prod`만 둔다. 비밀번호는 `db-admin-password`의 값이다. 일반 API 컨테이너에는 주입하지 않으며 되돌리기 창이 끝나면(아래 11단계 뒤) 지운다.

점검 시간:

5. 현재 예약을 멈춘다: `systemctl --user disable --now PROJECT-startup.service PROJECT-health.timer PROJECT-cvd-refresh.timer`. backup·restore-check 타이머는 백업 유예로 이미 꺼져 있어야 한다(`systemctl --user list-timers 'PROJECT-*' --all`).
6. **수동 백업**: 현재 설정으로 `python -m ops.automation run CURRENT.json --sha256 CURRENT_SHA256 --task backup`. 현재(이전) 앱 이미지의 백업 worker가 DB와 암호화 첨부를 일관된 시점으로 묶고 완료 기록을 현재 state에 남긴다. 실패하면 여기서 중단한다.
7. 이전 앱을 멈춘다: `docker compose -f CURRENT/compose.json stop web api`. `CURRENT`는 현재 state의 `active-deployment.json`이 가리키는 렌더(없으면 설정의 `deployment_directory`)다. db·scanner·node는 그대로 둔다.
8. 마이그레이션 전 확인: `JAVA_HOME=/SELECTED_JDK_21 uv run --project services/api python -m ops.preflight NEW --verify-database --sdk /DEDICATED_ANDROID_SDK`의 결과가 `"database_schema": "upgrade-required"`여야 한다. 이 검사는 **새** API 이미지 안에서 런타임 역할로 읽기 전용 실행되며, DB의 revision이 새 이미지가 모르는 값(예: 더 새 스키마)이면 실패한다. 2단계에서 `downloads/`에 APK를 넣었으므로 `--sdk`가 없으면 preflight 전체가 실패한다.
9. 마이그레이션(새 API 이미지, UID 10001, 읽기 전용, 전용 DB 네트워크만):

   ```bash
   docker run --rm --network PROJECT_database --read-only --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges:true --memory 256m --memory-swap 256m --env-file /PRIVATE_CONFIG/migration.env --entrypoint alembic NEW_API_IMAGE -c /opt/sallimbook/alembic.ini upgrade head
   ```

10. 같은 preflight를 다시 실행해 `"database_schema": "current"`를 확인한 뒤 `docker compose -f NEW/compose.json up -d --wait --remove-orphans`로 기동한다. 위 배포 후 확인표(서비스 7개, 검사기 `docker inspect`)와 보안 header를 확인하고, **PC 웹에서** 합성 영수증을 한 장 올린다. 이 시점의 폰은 아직 이전 APK다.
11. **두 폰을 즉시 업데이트한다**(`/downloads/SallimBook.apk` 또는 `adb install -r`). 새 APK에서 보험 사건 목록·청구 상세와 합성 영수증 사진 업로드를 확인한다.

이후:

12. 위 배포 2~5단계로 자동화를 전환한다(새 운영 checkout·state, install 전에 수동 health drop-in 디렉터리 `PROJECT-health.service.d/` 삭제와 `systemctl --user daemon-reload`, backup·restore-check 타이머 다시 끄기, `BACKUP_MISSING`/`BACKUP_STALE`가 정상).
13. 앱의 고정 납부 화면 "예정 회차 생성"을 **오늘부터** 이전에 생성해 둔 가장 먼 달까지 다시 실행한다(요청당 366일, 규칙 100개 이내). 0015는 예외가 풀린 회차의 `manual_override`를 실제 예외 여부로 정규화한다. 재생성은 그중 오늘 이후의 납부 기록 없는 회차를 현재 규칙으로 다시 맞춘다. 오늘 이전 회차는 다시 계산하지 않는다.

**되돌리기 — 11단계(폰 업데이트) 전까지만.** 그 뒤에는 되돌리지 않고 앞으로 고친다.

1. `docker compose -f NEW/compose.json stop web api inspector scanner`
2. DB를 **새** 이미지의 스크립트로 내린다(이전 이미지에는 0015/0016 스크립트가 없다). 위 9단계 명령의 `upgrade head`를 `downgrade 0014_vault`(이전 릴리스의 revision)로 바꿔 실행한다.
   - 0016 downgrade는 교체 기록의 새 두 열을 지운다. 점검 시간에는 새 기능 기록이 없어 잃는 값이 없다.
   - 0015 downgrade는 철회된 규칙 버전이 하나라도 있으면 거부한다. 그때는 6단계 백업을 새 DB로 복원해 전환해야 하는데 현재 도구에는 운영 DB 교체 경로가 없다. 중단하고 별도로 결정한다.
   - 0015가 정규화한 `manual_override`는 되돌리지 않는다(예외가 이미 풀린 회차의 표시만 다르며 금액·납부 기록은 같다).
3. 8단계와 같은 preflight(`--verify-database --sdk`)가 다시 `"upgrade-required"`인지 확인한다.
4. `docker compose -f PREVIOUS/compose.json up -d --wait --remove-orphans`. `PREVIOUS`는 7단계의 `CURRENT`(이전 state의 `active-deployment.json`이 가리키는 렌더)다. 검사기를 처음 배포했다면 `docker volume rm PROJECT_inspector_socket`도 실행한다.
5. 5단계에서 멈춘 이전 예약을 다시 켠다(`systemctl --user enable --now` 같은 세 unit). backup·restore-check 타이머는 켜지 않는다.

리허설: `python3 -m ops.test_upgrade --old-image OLD_API_IMAGE --new-image NEW_API_IMAGE`는 새 `sallimbook-ops-smoke-*` Compose 프로젝트(호스트 포트·노드·실제 키 없음)에서 위 순서를 실제로 수행하고 그 프로젝트만 지운다.
- 이전 릴리스: 자신의 `deploy.py` 렌더·마이그레이션·역할 준비, HTTP API로 합성 데이터(건너뛴/해제한 회차, 교체 기록) 입력, 자신의 `ops.backup create`로 완료 receipt까지 확인.
- 새 이미지: preflight와 같은 schema 검사(`upgrade-required`) → 9단계의 명령 그대로 마이그레이션 → `current` → 기동·health.
- 되돌리기: `downgrade 0014_vault` → 전체 public 테이블의 행 수와 내용 해시(새 열 제외)가 업그레이드 전과 같음 → 이전 릴리스 healthy.
- 다시 업그레이드 → 회차 재생성으로 해제한 회차의 `manual_override=false`를 확인.

자동화(systemd)·web/node·실제 백업 복원(`ops.test_recovery`)·실제 APK 업데이트는 이 리허설에 포함하지 않는다. 2026-10-21에 165d46b 이미지 → 이 절차를 추가한 커밋의 이미지로 통과했다(커밋과 출력은 해당 PR 기록).

### 롤백 창이 끝난 뒤 — 이전 운영 설정의 CVD 세대 정리

운영 설정을 새 운영 checkout·state로 전환하면 이전 설정이 만든 ClamAV DB 세대(`BUILD_DIRECTORY/<run id>/`와 `sallimbook-ops-api:cvd-…` 이미지)는 새 설정의 `cvd-refresh` 정리가 지우지 않는다. 그 세대의 영수증은 다른 운영 commit·앱 commit으로 봉인되었고 완료 기록은 이전 state 디렉터리에만 있기 때문이다. 이 세대도 6개 상한(`CVD_GENERATION_LIMIT`)에 계속 포함되므로 **롤백이 더 필요 없어진 뒤에** 정리한다. 롤백 가능한 동안에는 실행하지 않는다. 롤백 대상 세대를 지울 수 있다.

1. 남길 세대의 run id를 정한다. 새 state의 `active-deployment.json`의 `source_run`(활성 세대)이 하나다. 이전 설정으로 되돌릴 가능성이 남아 있으면 이전 state의 `active-deployment.json`의 `source_run`(롤백 대상 세대)도 남긴다. 현재 배포·직전 배포·기준선 세대는 이 목록과 무관하게 항상 보호된다.
2. 새 운영 checkout에서 먼저 `--dry-run`으로 확인하고, `would_remove_generations`가 기대와 같으면 `--dry-run`을 빼고 같은 명령을 실행한다.

   ```bash
   python -m ops.cvd_retention prune NEW.json --sha256 NEW_SHA256 --keep ACTIVE_RUN_ID --keep ROLLBACK_RUN_ID --previous-state OLD_STATE_DIRECTORY --dry-run
   ```

`--keep`은 한 번 이상 필요하고 현재 build 디렉터리에 없는 id는 `CVD_KEEP_UNKNOWN`으로 거부한다. 매일 정리와 같은 제거 절차를 쓰므로 세대마다 영수증·파일 해시·완료 journal(이전 state는 `--previous-state`로 지정)·정확한 이미지 태그와 라벨·사용 중인 컨테이너 없음·다른 저장 manifest의 참조 없음을 모두 확인하고, 통과한 세대의 정확한 태그만 `docker image rm --no-prune`으로 지운 뒤 기록된 트리를 지운다. 하나라도 통과하지 못하면 그 세대는 그대로 두고 `skipped_generations`에 나온다(운영자가 따로 판단). 복구가 필요한 중단 기록이 있으면 `RECOVERY_REQUIRED`로 시작하지 않는다. 결과는 state의 `latest-cvd-prune.json`에 남는다.

## 3. 전용 네트워크와 비밀 주입

생성 Compose는 프로젝트별 네트워크·볼륨만 사용한다. `ports`, `container_name`, `network_mode: host`, `/dev/net/tun`, `NET_ADMIN`, Docker socket을 사용하지 않는다. PostgreSQL은 내부 DB 네트워크, API는 내부 app/DB 네트워크에만 연결한다. API는 하나의 worker로 실행하여 현재 프로세스별 업로드·내보내기 한도와 맞춘다.

Tailscale은 전용 container의 userspace 네트워크를 사용한다. Caddy 두 프로세스가 이 노드의 network namespace를 공유하고 각각 loopback 8080/8081만 수신한다. Tailscale Serve가 지원하는 loopback HTTP upstream과 일치한다.

- 사설 HTTPS `https://FQDN:8443`: 웹/API와 `GET/HEAD /downloads/SallimBook.apk`만 허용하는 APK 다운로드. RP ID는 포트 없는 FQDN이다.
- 사설 Caddy는 요청의 `Host`(포트 제외)가 manifest의 FQDN과 다르면 웹 루트·APK·API 어디에도 가지 않고 421을 응답한다. 이 규칙은 첫 `handle` 블록이며, 최상위 `respond`는 뒤따르는 catch-all `handle`에 가려져 동작하지 않는다. Tailscale Serve는 들어온 `Host`를 그대로 전달하므로(1.104.1 소스에서 확인) 정상 요청은 영향이 없다. 이 규칙이 처음 켜지는 배포에서는 첫 요청(웹 첫 화면 또는 앱 로그인)이 421이 아닌지 바로 확인하고, 421이면 이전 렌더로 되돌린다.
- 공개 HTTPS `https://FQDN:443`: `/.well-known/assetlinks.json`의 GET/HEAD만 제공한다. 다른 경로는 404다. 공개 Caddy에는 API upstream, DB·첨부·비밀 mount가 없다. 사설·공개 Caddy는 같은 source-bound 웹 이미지를 사용하되 공개 설정은 DAL 경로만 제공한다. 이 이미지는 고정된 Caddy base의 불필요한 cap_net_bind_service 파일 capability를 빌드 시 제거한다. 8080/8081 고포트만 사용하므로 런타임 UID 10001·cap_drop ALL·no-new-privileges는 그대로 유지한다.
- TLS는 전용 노드의 Serve/Funnel에서 종료한다. Caddy는 같은 격리 namespace의 HTTP proxy다. 이전 문서의 “Caddy만 외부 HTTPS” 설명은 이 배치에서는 적용되지 않는다.
- 외부에서 들어온 `Forwarded`/`X-Forwarded-For`는 API에 전달하지 않고, API의 proxy header 해석도 끈다. 내부 HTTP가 인증 쿠키를 비보안 쿠키로 바꾸지 않는다.

### 모바일 최초 등록의 신뢰 경계

초기 등록을 켠 배포에서는 허용된 사용자가 Android 앱 또는 사설 웹에서 직접 첫 계정과 가계를 만든다. 사용자·구성원 기록이 한 번이라도 생긴 뒤에는 초기 등록을 다시 열지 않는다. 두 번째 계정은 기존 구성원의 초대로 등록한다. 운영 CLI의 등록 코드 전달을 사용자에게 필수 단계로 요구하지 않는다. 초기 등록 미설정·인증 헤더 누락/불일치·신뢰하지 않는 연결 상대는 서버에서 거절한다.

[고정 Tailscale 1.104.1 구현](https://github.com/tailscale/tailscale/blob/v1.104.1/ipn/ipnlocal/serve.go#L1023-L1064)은 요청의 사용자 식별 헤더를 먼저 삭제한 뒤, tailnet 연결의 WhoIs 결과로 사용자 로그인을 설정한다. Funnel·태그 기기·사용자 확인 실패에는 로그인 헤더를 넣지 않는다. 따라서 태그가 없는 사용자 소유 Android 기기를 사용해야 한다. ASCII 로그인은 그대로이며 비ASCII 로그인은 RFC 2047 Q-encoding된 **실제 헤더 값**을 해시한다. 앱에서 로그인 헤더를 만들어 보내지 않는다. [Serve 공식 설명](https://tailscale.com/docs/features/tailscale-serve#identity-headers)도 이 헤더를 사용하는 backend의 직접 접근 차단을 요구한다.

사설 Caddy는 node namespace의 loopback만 수신하고 [기본 proxy 동작](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#headers)으로 Serve의 식별 헤더를 API에 전달한다. API는 `request.client.host`가 Docker DNS의 현재 `node` 주소인지 확인한 뒤에만 헤더 digest를 검사한다. `--no-proxy-headers`를 유지하므로 위조한 전달 IP가 연결 상대를 대신하지 않는다. API 직접 호출이나 다른 container에서 같은 로그인 헤더를 보내는 것만으로 초기 등록이 열리지 않는다. node namespace 내부 프로세스와 Docker 운영자는 이 경계의 신뢰 대상이다. 공개 Caddy는 같은 namespace에 있어도 API proxy 경로가 없고, 공개 443은 DAL 파일 외 모두 404다.

배포 검증은 manifest 생략/잘못된 digest, 임의 proxy host, env 파일 우회, 렌더링 이후 설정 변조, loopback·namespace·공개 경로 구성을 검사한다. 격리 Caddy 시험은 인증 헤더의 전달과 전달 IP 제거를 확인한다. 실제 사용자 인증은 이 모의 upstream 시험으로 입증하지 않는다. API 권한 시험에서 허용 identity+신뢰 peer만 성공하고 다른 identity·누락/중복 헤더·직접 peer·위조 Forwarded·DNS 실패·이미 초기화된 DB는 실패하는지 확인해야 한다. Tailscale 버전을 바꿀 때에는 위 소스의 헤더 제거/재설정 동작을 다시 검토하고, 실제 사설 HTTPS 검증에서도 다른 사용자가 보낸 위조 로그인 헤더가 허용 identity로 통과하지 않는지 확인한다.

운영자는 새 전용 노드의 등록과 허용 기기 ACL을 별도로 승인·구성한다. 호스트의 기존 `tailscale serve/funnel/reset/up` 명령을 실행하지 않는다. 기존 노드 상태나 다른 프로젝트의 인증키를 복사하지 않는다. 실제 FQDN/ACL/인증서가 없는 단계에서는 사설 HTTPS·패스키 인수를 통과로 표시하지 않는다.

최초 등록은 아직 FQDN을 모르므로 같은 프로젝트의 `node`만 별도 bootstrap Compose로 시작할 수 있다.
고정 Tailscale 이미지에서 기본 `containerboot` 대신 `/usr/local/bin/tailscaled --tun=userspace-networking
--statedir=/var/lib/tailscale --socket=/tmp/tailscaled.sock`를 실행한다. 최종 설정과 같은
`PROJECT_node_state` 볼륨·edge/app 네트워크를 사용하고 host ports·장치·capability를 추가하지 않는다.
사용자는 로컬 비공개 터미널에서 이 container의 `tailscale --socket=/tmp/tailscaled.sock up
--hostname=PROJECT --accept-routes=false --accept-dns=false`를 실행한다. 로그인 링크는 채팅/로그에 복사하지 않는다.
로그인 후 `status --json`의 `BackendState`와 `Self.DNSName`만 추출한다. 전체 응답이나 인증 URL은 기록하지 않는다.

확정 FQDN으로 최종 설정을 생성한 뒤 **최종 Compose 파일만** 사용해 같은 프로젝트의 node를
재생성한다. bootstrap 파일을 함께 merge하면 raw daemon command가 남아 Serve 설정이 적용되지 않는다.
상태 볼륨을 삭제하거나 두 daemon에 동시에 연결하지 않는다. 최종 node도 Docker logging `none`을
유지하여 재인증 URL이 Docker 로그에 남지 않게 한다. 이는 Tailscale 자체 원격 진단 로그 설정과는 별개다.

전용 runtime 디렉터리의 파일은 아래처럼 분리한다. 실제 생성과 값 입력은 운영자가 비공개 절차로 수행한다.

| 경로 | 소유/권한 | 내용 |
|---|---|---|
| `api.env` | 운영자 소유 0600 | `SALLIMBOOK_DATABASE_URL=postgresql+psycopg://sallimbook_app:…@db:5432/sallimbook_prod` 한 항목만 허용; quote/interpolation 없이 raw 형식 |
| `app-db-password` | 운영자 소유 0400/0600, API container에는 mount하지 않음 | API URL과 같은 24자 이상 runtime DB 비밀번호 |
| `db-admin-password` | 운영자 소유 0400/0600, DB container만 읽음 | 별도의 24자 이상 admin/migration DB 비밀번호; runtime 비밀번호와 다름 |
| `field-keyring.json` | API UID 10001 소유 0400/0600 | 기존 서버 field/document keyring, 백업 데이터와 별도 보관 |
| `documents/` | API UID 10001 소유 0700 | 암호화 `.sbdoc` 객체; 파일은 0600 |

API/scanner/inspector의 root filesystem은 읽기 전용이고 처리 임시 파일은 tmpfs다. 메모리 한도와 같은 swap 한도를 설정한다. scanner는 네트워크가 없고 Unix socket만 공유한다. 문서 구조 검사·OCR을 맡는 inspector는 UID 10002·GID 10003, 네트워크 없음, 비밀·문서 저장소·scanner socket mount 없음이며 전용 볼륨의 socket 하나만 API와 공유한다(메모리 1152MiB, PID 32, 고아 프로세스를 회수하는 컨테이너 init). API는 그 socket을 읽기 위해 그룹 10003만 추가로 가진다. 이 설정 외에 호스트 swap/WSL 메모리 설정을 자동 수정하지 않는다. 실제 cgroup/tmpfs/스캐너 신선도·서비스 재시작 인수는 배포 전에 확인한다.

DB 최초 owner/migration 역할은 `sallimbook_admin`이며 API에는 전달하지 않는다. API의 `sallimbook_app`은 LOGIN만 허용하고 superuser/DB 생성/역할 생성/replication/RLS 우회/역할 상속을 주지 않는다. schema CREATE, TRUNCATE, 테이블 소유권, trigger 비활성화, Alembic version 수정 권한도 없다. 업무 테이블의 필요한 SELECT/INSERT/UPDATE/DELETE와 sequence/function 사용만 허용한다. 감사 이력 `audit_events`는 SELECT/INSERT만 허용하고 UPDATE/DELETE는 금지한다. `public` schema/database의 PUBLIC 기본 권한을 회수하고 migration admin이 만드는 후속 객체의 default privileges도 설정한다.

다음은 운영 실행이 별도로 승인된 뒤의 순서다. 전용 DB만 먼저 시작하고 admin credential로 migration을 적용한다. 외부 비공개 admin service 파일과 app 비밀번호 파일을 **일회용 운영 도구 container에만** 읽기 전용으로 주입하여 실행한다. 일반 API container에는 admin service/비밀번호를 mount하지 않는다.

```bash
# 전용 database 네트워크에 연결한 운영 도구 container 안에서:
python -m ops.database provision \
  --admin-service-file /run/operator/admin-service.conf \
  --application-password-file /run/operator/app-db-password
# operator host에서, DB/migration/역할 준비 뒤 API 시작 전:
uv run --project services/api python -m ops.preflight /PRIVATE_CONFIG/RENDERED_DIRECTORY --verify-database
```

`admin-service.conf`는 아래 백업 service 형식에서 user를 `sallimbook_admin`으로 설정한다. `provision`은 전용 cluster_name/DB 소유자/단일 애플리케이션 DB를 검사하고 기존 app 역할이 있으면 덮어쓰지 않는다. 기존 역할은 `verify-runtime`으로 검사한다. 이 검사는 모든 public 업무 테이블의 필수 권한, 모든 시퀀스의 USAGE/SELECT, public USAGE, DB CONNECT를 확인한다. 일반 테이블은 SELECT/INSERT/UPDATE/DELETE, 감사 이력은 SELECT/INSERT, Alembic 테이블은 SELECT만 허용하며 감사 이력의 열 단위 UPDATE 권한도 거부한다. 비밀번호는 libpq의 표준 SCRAM 변환 후 SQL에 전달하여 평문을 SQL·활동 조회·서버 명령 로그에 넣지 않는다. migration은 계속 admin 역할로만 수행한다. `preflight --verify-database`는 프로젝트 label이 맞는 내부 DB 네트워크에서 일회용 읽기 전용 client로 실제 역할을 확인하며, 기존 서비스를 시작/재설정하지 않는다.

## 4. 일관된 암호화 백업

백업 도구는 API와 같은 사용자로 실행하고 DB/암호화 첨부에만 접근한다. 백업 목적지와 문서 저장 디렉터리는 서로 독립된 경로여야 한다. 같은 경로, 문서 내부의 목적지, 문서를 포함하는 상위 목적지를 모두 쓰기 전에 거부한다. 백업 수신자의 **공개** age recipient만 주입한다. 개인 age identity, 서버 field keyring, APK 서명키, vault 복구코드는 이 백업 묶음에 넣지 않는다.

libpq service 파일은 전용 0600 파일이고 한 섹션만 허용한다. 비밀번호는 이 파일에만 입력하며 명령행에 넣지 않는다.

```ini
[sallimbook]
host=DEDICATED_DB_HOST
port=5432
dbname=sallimbook_prod
user=DEDICATED_DATABASE_ROLE
password=ENTER_PRIVATELY
sslmode=disable
```

`sslmode=disable`은 동일 전용 Docker 내부 DB 연결에만 사용한다. 원격 DB를 도입한다면 별도 TLS/인증서 정책을 먼저 설계한다. 도구는 환경의 다른 `PG*` 설정을 dump/restore에 상속하지 않는다.

```bash
uv run --project services/api python -m ops.backup create \
  --service-file /PRIVATE_CONFIG/backup-service.conf \
  --documents /PRIVATE_RUNTIME/documents \
  --destination /PRIVATE_BACKUP_DIRECTORY \
  --recipient PUBLIC_AGE_RECIPIENT \
  --deployment-manifest /PRIVATE_CONFIG/deployment.json \
  --source-commit REVIEWED_SHA
```

실행 순서는 다음과 같다.

1. pool을 쓰지 않는 물리 DB 연결에서 `STORAGE_BARRIER=91544042505043`의 exclusive session lock을 확보한다. 기다리는 동안 RR snapshot을 미리 만들지 않는다.
2. 잠금 확보 뒤 `REPEATABLE READ READ ONLY` transaction을 시작하고 snapshot을 export한다. `pg_dump --snapshot`이 같은 시점을 읽는다.
3. custom-format dump를 pipe로 age에 전달한다. 평문 SQL dump 파일은 만들지 않는다.
4. 잠금을 유지한 채 암호화 객체를 복사하고 DB 참조·크기·SHA-256 inventory를 대조한다. 업로드/cleanup의 같은 barrier 덕분에 DB와 파일이 어긋나지 않는다. 금전/일반 데이터는 PostgreSQL snapshot에 고정된다.
5. snapshot 시각·schema revision·source commit·공개 배포 manifest(이미지/RP/FQDN/서명 인증서/앱 버전)·전체 public 테이블 행 수·가계별 최대 vault key version·암호화 dump/object checksum을 manifest에 넣는다. 이 manifest와 암호화 dump/object를 다시 tar→age로 묶는다. manifest는 생성과 복원 모두 같은 2MiB 상한을 적용한다.
6. fsync된 암호화 `.partial`을 새 UUID 이름으로 게시하고 `.complete.json`을 마지막에 기록한다. 완료 receipt 없는 파일은 복구 가능한 완료 백업으로 세지 않는다.

작업 중 디스크에는 암호화 dump·기존 암호화 객체·비공개 inventory만 있다. 오류 시 새 완료 receipt를 만들지 않는다. 15분 subprocess 제한을 두고 객체별 20MiB+태그, 전체 8GiB, 객체 10,000개를 넘으면 실패한다. 일반 HTTP 문서 다운로드 한도와 별도 운영 한도다.

age는 기밀성과 암호문 변조 검사를 제공하며 백업 작성자의 서명은 제공하지 않는다. 완료 receipt의 archive SHA-256은 접근 통제가 다른 운영 기록에도 보관한다. 같은 저장소에서 함께 바뀐 archive/receipt만으로 출처를 확인했다고 주장하지 않는다.

보존 정책은 최근 14일·8주·12개월의 각 기간에서 가장 최신 사본을 유지하며, 전체 최신 백업과 복원 근거에 연결된 원본을 추가 보호한다. RPO 24시간/RTO 4시간은 목표다. [실제 첫 복원 기록](testing/operating-backup-restore.md)의 짧은 무결성 검사 시간은 전체 서비스 RTO가 아니다.

단일 실행 백업 명령은 예약 작업이나 삭제를 설치하지 않는다. [운영 예약 작업](testing/operations-automation.md)은 별도 설정으로 백업·상태 검사·월간 격리 복원·첨부 검사 DB 갱신을 실행한다. [보존 도구](testing/backup-retention.md)는 읽기 전용 계획을 만들고, 독립 사본 선언·실제 사본 해시·복원 무결성 증거·명시한 계획 해시를 모두 확인해야 원본 삭제를 허용한다. 예약 작업은 자동 삭제를 호출하지 않는다. 현재 외부 보관 위치 결정은 사용자 요청으로 운영 시작 뒤로 미뤘으며, 그동안 삭제 대상은 0건이다. 키 보존 기간은 가장 오래된 복원 대상과 맞추며 필요한 키를 먼저 폐기하지 않는다.

## 5. 새 환경으로 격리 복원

동일 PostgreSQL 18.6에서 `CREATE DATABASE … TEMPLATE template0`으로 **새 빈** `sallimbook_*_restorecheck` DB를 준비한다. 기존 DB/첨부 경로를 재사용하지 않는다. 새 DB는 외부 API·Tailscale 노드에 연결하지 않는다. operator service 파일과 age identity는 각각 0600으로 별도 전달한다.

```bash
uv run --project services/api python -m ops.backup restore \
  --archive /PRIVATE_BACKUP/UUID.tar.age \
  --expected-sha256 SHA_FROM_SEPARATELY_TRUSTED_COMPLETION_RECORD \
  --identity /SEPARATE_PRIVATE_CUSTODY/age-identity.txt \
  --service-file /PRIVATE_CONFIG/restore-service.conf \
  --output /PRIVATE_RESTORE_PARENT/NEW_RESTORE_DIRECTORY
```

도구는 archive digest, age 무결성, 제한된 tar 경로/형식, 모든 entry SHA/크기를 검사한다. symlink/hardlink/상위 경로/임의 파일/중복 entry를 추출하지 않는다. 복원 전에 PostgreSQL 18 initdb의 기본 객체만 허용하고 사용자 테이블·함수·타입·확장·event trigger·빈 사용자 schema·large object·DB별 subscription/설정을 거부한다. 기존 객체를 지우거나 `--clean`으로 맞추지 않는다. 암호화 dump는 age→pg_restore pipe를 사용하고 `--single-transaction --exit-on-error --no-owner --no-acl`로 복구한다. schema revision과 전체 public 테이블 목록/행 수를 대조하고 `QUARANTINE`, `restore.json`, `backup-manifest.json`을 남긴다. 실패한 DB/디렉터리는 격리 상태이며 자동 삭제·재시도 덮어쓰기를 하지 않는다.

정기 `restore-check`는 이 복원에 서버 필드/첨부의 실제 인증 복호화 검사를 더하고, 원래 두 기록의 해시와 연결한 `restore-integrity.json`을 발급한다. 사용자 비밀번호 변경·보관함 키 회전·운영 전환을 수행하지 않으므로 다음 절의 전체 복구 인수와 구분한다. 아직 두 번째 구성원이 연결되지 않은 가계에서도 백업 무결성 검사는 가능하다.

백업 시점 이후의 기록이 원본 손실로 사라졌다면 최신 삭제/철회/금전 이력을 자동으로 재구성할 수 없다. 복원 시각을 현재 시각으로 바꾸거나 자동 재전송으로 채우지 않는다. 두 사용자가 RPO 구간의 자산 스냅샷·수입/보험금/납부·재고·삭제 기록·가계 구성원을 다시 확인한다. 확인 결과와 수용한 손실 범위를 비밀 원문 없는 인수 기록에 남긴다.

## 6. 인증과 보관함의 rollback 방지

격리 복원에서 기존 API/pool 연결을 모두 끊은 뒤 비공개 대화형 터미널에서 실행한다.

```bash
uv run --project services/api python -m ops.recovery prepare \
  --service-file /PRIVATE_CONFIG/restore-service.conf \
  --directory /PRIVATE_RESTORE_PARENT/RESTORE_DIRECTORY
```

도구는 두 active 구성원·한 가계인지 검사하고, 각 구성원 슬롯의 **새 로그인 비밀번호**를 터미널에서 두 번 입력받는다. 기존 비밀번호와 같으면 거절한다. 실제 로그인 비밀번호를 AI/이슈/로그에 입력하지 않는다. 모든 기존 session/device/passkey/invitation을 폐기하고 refresh/challenge/step-up grant를 소모 처리한다. disabled 계정을 되살리지 않고 이전 인증 행은 삭제하지 않는다. 보관함·nonce ledger·의료/금전 기록은 그대로 보존한다.

별도 승인된 복구 전용 사설 접근에서 두 사용자가 새 비밀번호로 새 기기 ID를 발급받는다. 기존 device ID에 묶인 로컬 wrapping은 재사용하지 않는다. 두 기기의 기존 로컬 인증/보관함/CVC 상태는 실제 기기에서 제거하고 재설정 여부를 확인한다. 서버 도구만으로 떨어져 있는 기기의 이미 저장된 평문/비밀을 원격 소거했다고 주장하지 않는다.

보관함은 기존 wrapping/복구코드로 권한과 복호화를 확인한 다음 정상 보관함 API로 전체 HVK 회전을 수행한다. 백업에 staging rotation이 있으면 먼저 abort하고, **백업에 존재한 최대 key version보다 높은 버전**으로 다시 회전한다. 두 구성원의 새 wrapping, 새 recovery wrapping, 모든 카드 envelope가 준비되어 정상 finalize되어야 한다. 새 보관함 비밀번호와 새 복구코드는 두 사용자가 별도 확인·보관한다. 복구키를 잃은 경우 초기화는 별도 사용자 선택이며 이 도구가 자동 초기화하지 않는다.

`ops.recovery.ACKS`의 모든 항목을 true로 한 별도 인수 JSON에는 다음 필드만 둔다: `format: 1`, `backup_id`, `acknowledgements`, `evidence_sha256`. 마지막 값은 두 사용자 인수 기록의 SHA-256이다. 비밀번호·복구코드·진료 원문은 넣지 않는다. 확인하지 않은 항목을 true로 채우지 않는다.

```bash
uv run --project services/api python -m ops.recovery verify \
  --service-file /PRIVATE_CONFIG/restore-service.conf \
  --directory /PRIVATE_RESTORE_PARENT/RESTORE_DIRECTORY \
  --keyring-file /SEPARATE_PRIVATE_CUSTODY/field-keyring.json \
  --evidence-file /PRIVATE_ACCEPTANCE/recovery-acceptance.json
```

검사는 이전 인증 폐기, 새 비밀번호 버전·새 기기 로그인, 완료된 새 vault 버전, 두 구성원 wrapping/recovery, pending rotation/share 부재를 대조한다. 서버 keyring으로 모든 ready 첨부의 AEAD/원본 checksum과 계좌·증권번호 복호화를 메모리에서 확인하고 평문을 출력/저장하지 않는다. 클라이언트 소유 HVK의 실제 복호화/재암호화는 별도 사용자 인수 증거이며 서버 metadata 검사로 대체하지 않는다.

성공해도 `QUARANTINE`은 남고 결과는 `ready-for-operator-review`다. 성공할 때마다 새 `verification_id`와 `recovery-check-UUID.json`을 기록하며 반환값의 `receipt`로 해당 파일을 확인한다. 이전 인수 기록은 덮어쓰거나 삭제하지 않고 실패한 검사는 성공 receipt를 추가하지 않는다. 원본 노드/서버가 다시 접속하지 않는지, RP ID/서명 연속성, 앱 호환성, 두 기기 동작, RPO 손실 수용을 확인한 후 운영자가 승인된 배포 단계에서 전환한다. 검사 후 DB가 변경되면 결과를 그대로 재사용하지 말고 다시 검사한다. DB downgrade나 과거 이미지 실행은 데이터 복원과 다른 작업이다.

## 7. 서명 APK와 업데이트

서명키·키 비밀번호 파일은 저장소 밖의 owner-only 파일로 보관한다. 도구는 기존 키만 사용하며 개인키나 비밀번호를 Gradle property/environment/명령행 값에 넣지 않는다. apksigner에는 private 파일 경로만 전달한다. store/key 비밀번호가 같더라도 apksigner가 각 입력을 순서대로 소비하므로 서로 다른 두 파일을 사용한다. manifest의 인증서 SHA-256은 공개 정보다.

```bash
python3 -m ops.release \
  --manifest /PRIVATE_CONFIG/deployment.json \
  --sdk /DEDICATED_ANDROID_SDK \
  --keystore /SEPARATE_SIGNING_CUSTODY/release.jks \
  --store-password-file /SEPARATE_SIGNING_CUSTODY/store-password \
  --key-password-file /SEPARATE_SIGNING_CUSTODY/key-password \
  --alias RELEASE_ALIAS \
  --previous-version PREVIOUS_DISTRIBUTED_VERSION_CODE \
  --previous-apk /PRIVATE_RELEASE_PARENT/PREVIOUS_RELEASE.apk \
  --output /PRIVATE_RELEASE_PARENT/NEW_RELEASE.apk
```

빌드와 서명은 별개 단계다. 빌드(`pnpm install --frozen-lockfile --ignore-scripts` → `pnpm android:sync` → Gradle)는 서명 키·비밀번호 경로를 받지 않고 허용 목록의 환경 변수(`PATH`, `HOME`, `JAVA_HOME`, `ANDROID_HOME`, `GRADLE_USER_HOME`, `LANG`, pnpm 저장소 변수)만 받으며, 명령은 그 허용 목록만 환경으로 받는다. Gradle은 `--no-daemon`과 Kotlin in-process 컴파일로 실행한다. 서명(zipalign·apksigner)은 모든 빌드 명령이 끝난 뒤에 시작한다. 의존성의 install 스크립트는 실행하지 않는다. pnpm 9의 lockfile에는 install 스크립트 여부가 기록되지 않으므로, CI(`types-contract`)가 `pnpm install` 뒤 설치된 의존성 트리에서 preinstall/install/postinstall 스크립트와 `binding.gyp`가 있는 패키지, 그리고 워크스페이스 프로젝트의 수명주기 스크립트를 찾는다(`scripts/check_install_scripts.py`). 결과가 `ops.build_context.INSTALL_SCRIPT_PACKAGES`와 다르면 실패하므로, 필요한 패키지가 생기면 그 목록에 기록하고 그 스크립트만 명시적으로 실행하는 빌드 단계를 추가한다. 현재 설치 트리에는 그런 패키지가 없다. `ops.build_context`의 이미지 빌드 입력(`pnpm install`, `pnpm build`)도 같은 허용 목록과 `--ignore-scripts`를 쓴다. 빌드는 제3자 코드를 같은 사용자로 실행하므로 서명 전에 두 가지를 더 확인한다. (1) 빌드 전에 서명 경로의 도구 전체(SDK의 `build-tools/36.0.0`, `cmdline-tools/15859902`와 `JAVA_HOME` JDK 트리: zipalign, apksigner와 jar, apkanalyzer, `bin/java`, `lib/modules` 포함)의 파일별 모드·SHA-256 지문을 만들고, 서명 직전에 다시 비교한다. 하나라도 달라지면 `SIGNING_TOOLS_CHANGED`로 중단하고 서명하지 않는다. (2) 릴리스 프로세스는 빌드 전에 자신을 child subreaper(`prctl(PR_SET_CHILD_SUBREAPER)`)로 설정한다. 그러면 빌드가 띄운 프로세스의 부모가 끝날 때 그 프로세스(Gradle·Kotlin 데몬처럼 `setsid`나 이중 fork로 세션을 벗어난 것 포함)는 init이 아니라 릴리스 프로세스의 자식이 된다. 빌드 명령이 끝날 때마다 남은 자식을 모두 SIGKILL로 종료·회수하고 남은 것이 없음을 확인한다. 정해진 시간 안에 사라지지 않으면 `BUILD_PROCESS_LEFT_RUNNING`으로 중단한다. 빌드 전에 `setsid`로 분리한 시험 프로세스가 실제로 자식으로 돌아오는지 확인하며, subreaper를 설정할 수 없거나 확인에 실패하면 `BUILD_CONTAINMENT_UNAVAILABLE`로 중단하고 다른 방식으로 대신하지 않는다. 사용자 systemd 관리자나 linger는 필요 없다. 빌드가 끝나면(남은 프로세스 회수 뒤) 출력 디렉터리 옆에 비공개 임시 디렉터리(0700)를 새로 만들어 서명되지 않은 APK를 즉시 0600으로 복사한다. 이 디렉터리는 빌드가 끝난 뒤에 생기므로 빌드 코드가 볼 수 없다. 검사·정렬·서명은 그 복사본만 읽는다. 빌드 트리의 파일을 바꿔도 서명 대상에 영향이 없다. zipalign·apksigner·apkanalyzer는 검증한 JDK의 `JAVA_HOME`, 그 `bin`+`/usr/bin:/bin`인 `PATH`, `LANG`만 가진 고정 환경으로 실행하며 `JAVA_TOOL_OPTIONS`·`_JAVA_OPTIONS`·`JDK_JAVA_OPTIONS`·`CLASSPATH` 등 다른 변수는 받지 않는다. 중단 코드는 명령 출력에 고정된 코드로만 나오고 원인 세부는 출력하지 않는다.

**남는 위험:** 남은 프로세스 회수는 빌드가 끝난 뒤 살아남은 프로세스가 출력이나 서명 도구를 바꾸지 못하게 하는 장치이고 서명 키의 비밀 유지 장치가 아니다. 빌드 코드는 같은 사용자로 실행되므로 빌드가 도는 동안 같은 사용자가 읽을 수 있는 파일을 모두 읽을 수 있다. 키 저장소와 비밀번호 파일의 경로는 `ops.release` 명령줄(`/proc/<pid>/cmdline`)에 보이므로 빌드 중에 그 파일을 읽을 수 있다. 빌드가 이 프로세스 트리 밖의 실행기에 작업을 맡기면(예: 이 사용자가 쓸 수 있는 Docker socket으로 `docker run -d`, 사용자 systemd 관리자가 떠 있을 때의 `systemd-run --user`) 그 프로세스는 회수 대상이 아니고 서명 뒤에도 남을 수 있다. 빌드가 끝나기 전에 지문 대상이 아닌 같은 사용자의 파일을 바꾸는 것도 막지 못한다. 서명 도구와 JDK의 지문 비교는 이런 변경 중 서명 경로의 변조만 잡는다. 완전한 격리는 빌드를 별도 사용자 또는 컨테이너에서 실행하고 서명 자료를 그 밖에 두는 것이 필요하며, 현재 구현하지 않았다. 서명키 보관 위치와 권한은 §7 앞부분의 조건을 유지한다.

깨끗한 source commit, JDK 21, 고정 SDK/build-tools 36.0.0을 요구한다. `ops/release.init.gradle`은 이 실행에만 versionCode/versionName과 debuggable=false를 적용한다. 이전 배포 versionCode보다 커야 하며 이전 APK의 실제 앱 ID·버전·서명 인증서도 확인한다. 최초 배포만 `--previous-version 0`과 previous-apk 생략이 가능하다. 검사 항목은 release 앱 ID, manifest backup/cleartext/debug 설정, bundled WebView URL/allowNavigation/mixed-content 부재, native 공개 설정 값, debug proof class 부재, zipalign, apksigner 서명과 인증서 지문이다.

검증된 최종 signed release APK만 생성 설정의 `downloads/SallimBook.apk`에 운영자가 0644로 복사한다. 이 디렉터리는 사설 Caddy에만 읽기 전용으로 mount하며 다른 파일·디렉터리·trailing-slash 경로는 404다. 다운로드 주소는 `https://FQDN:8443/downloads/SallimBook.apk`이고 허용된 tailnet 기기만 접근한다. APK는 첨부 다운로드 형식과 no-store 응답으로 제공하며, 공개 443에는 mount나 경로를 추가하지 않는다. 서명키·비밀번호 파일·debug/unsigned APK를 이 디렉터리에 넣지 않는다. 다운로드용 APK를 배치한 뒤 웹을 시작하거나 해당 다운로드 디렉터리로 전환하기 전에 아래 preflight를 통과해야 한다. APK가 존재하는데 --sdk가 없으면 실패한다. SDK의 apkanalyzer/apksigner/zipalign으로 manifest의 앱 ID·인증서·버전·debug/backup/원격 WebView 설정을 실제 파일과 대조하고 검사 전후 SHA-256 및 파일 식별자가 같은지 확인한다. 이웃 receipt의 signed=true나 이전 checksum만으로 통과하지 않는다.

```bash
JAVA_HOME=/SELECTED_JDK_21 uv run --project services/api python -m ops.preflight \
  /PRIVATE_CONFIG/RENDERED_DIRECTORY --sdk /DEDICATED_ANDROID_SDK
```

APK가 없으면 결과는 not-present이며 다운로드를 승인한 것이 아니다. 설정을 새 디렉터리에 다시 생성할 때 기존 검증된 APK를 잃거나 미검증 파일로 바꾸지 않는다. 신뢰한 원본 APK를 새 downloads 디렉터리에 복사하고 새 manifest로 재검증한 뒤 전환한다. 검사는 해당 시점의 파일에 대한 것이므로 이후 APK를 바꾸면 다시 실행한다. 이 운영 도구 보완은 기존 d9eb6e2 이미지·앱 payload·서명을 바꾸거나 이미지/앱 재빌드를 요구하지 않는다.

서명 검사와 실제 업데이트는 별개다. S25 Ultra/S24 Ultra에서 이전 **같은 인증서의 release APK** 위에 새 APK를 설치하여 DB·로그인·Keystore·보관함/로컬 CVC 동작을 확인한다. 다른 인증서/낮은 versionCode 설치 거부도 확인한다. debug APK를 정식 배포하거나 일반 빌드 artifact에 signing material을 넣지 않는다. private 배포 경로에 대한 인증은 APK 밖에 두며 GitHub token을 앱에 내장하지 않는다.

## 8. 검증 명령과 남은 운영 인수

```bash
python3 -m unittest discover -s tests/operations -v
python3 -m ops.test_deployment --web-image LOCALLY_BUILT_WEB_IMAGE
python3 -m ops.test_runtime --image LOCALLY_BUILT_API_IMAGE
python3 -m ops.test_upgrade --old-image PREVIOUS_RELEASE_API_IMAGE --new-image LOCALLY_BUILT_API_IMAGE
JAVA_HOME=/SELECTED_JDK_21 python3 -m ops.test_release --sdk /DEDICATED_ANDROID_SDK
PATH=/VERIFIED_AGE_AND_POSTGRES_TOOL_DIRECTORY:$PATH \
  uv run --project services/api python -m ops.test_recovery
```

`test_deployment`는 새로 빌드한 웹 이미지와 network-none 단발 컨테이너로 Compose/Caddy 설정·이미지 버전·파일 capability 제거·umask 077에서의 cap-drop root 설정 읽기·UID 10001 설정 읽기를 검사한다. 공개 JSON/404 및 사설 APK의 GET/HEAD·내용·다운로드 header·그 외 경로/POST 거부도 확인한다. API나 실제 APK 서명 검사를 대신하지 않는다. 실제 tailnet 노드를 만들지 않는다. `test_recovery`는 공통 DB 시험 lock과 `sallimbook-dev`의 `db-test`만 사용하고 새 UUID 이름의 합성 source/restore DB를 만든다. 종료 시 자신이 만든 DB만 제거하고 test 컨테이너를 중지한다. 임시 합성 age/field key는 시험 종료 후 제거하며 실제 키를 사용하지 않는다. vault rotation fixture는 서버 metadata/상태전이를 검사하는 opaque fixture이며 클라이언트 암호학 증거가 아니다.

`test_runtime`은 새 `sallimbook-ops-smoke-*` Compose 프로젝트·내부 네트워크·합성 볼륨에서 migration, 제한된 DB 역할, UID10001/scanner socket/tmpfs, 실제 한국어 OCR/ClamAV 업로드와 암호화 저장·다운로드, inspector 격리(UID·네트워크·비밀·저장소·capability·socket 권한)·메모리 소진 격리·고아 프로세스 회수·inspector 중지 복구를 검사하고 그 프로젝트만 제거한다. 호스트 포트/노드를 만들지 않는다. `test_release`는 임시 합성 서명키로 연속 두 release를 만들고 서명/버전/변조 거부를 검사한 뒤 키·APK를 제거한다. 실제 서명키나 기기 설치는 사용하지 않는다. Docker 네트워크를 생성/제거하는 시험과 Chromium 전체 검사는 순차 실행하여 `ERR_NETWORK_CHANGED` 간섭을 피한다.

운영 완료에는 별도로 실제 허용/비허용 기기의 사설 접근, 외부 443의 JSON 이외 차단, DB 비노출, 실제 패스키, 이전 앱-새 API, 두 기기 데이터 보존 업데이트, WSL 재시작 복귀, 서명키/서버키/복구코드 별도 보관, 전체 도메인 fixture·G1~G6 인수, 실제 새 환경 복원 시각과 RPO/RTO 측정이 필요하다. 이 문서나 단위검사만으로 SB-036~040을 완료 처리하지 않는다.

공식 근거: [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve), [컨테이너 설정](https://tailscale.com/docs/features/containers/docker/docker-params), [Funnel](https://tailscale.com/docs/reference/tailscale-cli/funnel), [Caddy proxy header](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [PostgreSQL pg_dump snapshot](https://www.postgresql.org/docs/18/app-pgdump.html), [age 공식 CLI](https://github.com/FiloSottile/age), [Android 앱 서명](https://developer.android.com/studio/publish/app-signing), [Android 개발자 검증 정책](https://developer.android.com/developer-verification/guides/faq). 배포 시점의 Android 지역·배포경로 정책은 다시 확인한다.
