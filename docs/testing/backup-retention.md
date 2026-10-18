# SB-036 암호화 백업 목록·복제·보존 검증

관련 요구사항: R20, SB-036. 기본 정책은 [배포·백업 설계](../deployment-backup-operations.md), 실제 운영 절차는 [운영 runbook](../operations-runbook.md), 잔여 출시 조건은 [v1 완료 계획](../v1-completion-plan.md)을 따른다.

`ops.retention`은 기존 `UUID.tar.age`와 `UUID.complete.json`을 검증한다. DB·문서 원본·키를 읽거나 복호화하지 않는다. 자동화가 수행하는 범위는 목록 확인, 암호문 복제, 삭제 계획 작성까지다. 실제 삭제는 운영자가 검토한 계획의 SHA-256을 별도 전달하는 `apply`로만 실행한다.

## 경로와 실행 권한

- 백업 소유 UID로 실행한다. `expected_uid`는 현재 UID와 일치하는지 확인하는 옵션이며 접근 권한 우회가 아니다.
- 원본, 복제 저장소, 운영 문서, 복원 증거, 계획 저장소는 서로 분리된 절대 경로여야 한다. 중첩 경로와 심볼릭 링크 경로는 거부한다.
- 관리 디렉터리는 현재 UID 소유 `0700`, 읽는 파일은 현재 UID 소유·단일 링크·일반 파일 `0600`이어야 한다. FIFO, 심볼릭 링크, 하드 링크, 공개 권한 파일은 거부한다.
- 파일은 디렉터리 FD 기준 `O_NOFOLLOW`로 열고, 읽기 전후 inode·크기·mtime·ctime·소유권·권한을 비교한다. 해시는 암호화 아카이브 전체를 스트리밍하여 계산한다.
- `catalog`와 `plan`은 원본·복제·복원 증거에 쓰지 않는다. `plan --output`만 별도 계획 디렉터리에 새 파일을 만든다. 기존 계획을 덮어쓰지 않는다.
- `replicate`와 `recover-replica`는 복제 루트의 `.retention.lock`, `apply`는 원본 루트의 `.retention.lock`에 비차단 배타 잠금을 사용한다. 같은 소유자의 협력 프로세스 간 중복 실행을 차단한다. root 또는 같은 UID의 악의적 변경을 방어하는 서명·신뢰 경계는 아니다.

Python 파일 작업의 근거는 [Python 3.14 os 문서](https://docs.python.org/3.14/library/os.html)와 [fcntl 문서](https://docs.python.org/3.14/library/fcntl.html)다. 새 런타임 의존성은 없다.

## 목록과 복제

```bash
python -m ops.retention catalog --source /private/backups
python -m ops.retention replicate \
  --source /private/backups --replica /private/replicas \
  --documents /private/documents --backup-id UUID
```

위 경로와 `UUID`는 예시이며 실제 운영 경로가 아니다. 복제 저장소는 사전에 `0700`으로 준비한다. 복제 결과는 `/private/replicas/UUID/` 아래 원본 이름의 암호문·완료 영수증과 `replica-verification.json`을 갖는다. 원본 영수증의 UUID, 바이트 수, SHA-256, UTC 완료 시각을 검증하고 복제된 바이트를 다시 해시한다. 완성된 동일 복제본에 대한 재실행은 현재 바이트를 검증하고 기존 파일은 다시 쓰지 않는다.

`independent_storage_verified`는 항상 `false`다. 같은 PC의 두 경로를 복제했다는 사실로 독립 백업을 완료했다고 보고하지 않는다. 실제 별도 저장장치·외부 호스트·클라우드의 보관 주체와 장애 범위 확인은 운영자 책임이며, 외부 전송 프로토콜이나 클라우드 업로드는 이 모듈 범위에 없다.

중단 복제는 자동으로 성공 처리하지 않는다. 다음 명령은 복사된 암호문이 원본과 **전체 크기 및 해시가 이미 일치할 때만** 누락된 완료/검증 영수증을 새로 발급한다.

```bash
python -m ops.retention recover-replica \
  --source /private/backups --replica /private/replicas \
  --documents /private/documents --backup-id UUID
```

짧거나 손상된 파일, 예상 외 파일, 불일치 영수증은 그대로 보존하고 실패한다. 운영자가 내용을 확인하고 별도 새 저장소로 다시 복제해야 한다. 자동 삭제·덮어쓰기·부분 파일 이어 붙이기는 없다.

목록은 정상 완료 쌍만 `backups`에 반환한다. 아카이브/영수증 한쪽만 있는 항목은 `orphan`, `.partial` 및 기존 백업 임시 디렉터리는 `partial`, 끝나지 않은 삭제 저널은 `interrupted-retention`으로 구분한다. 불완전 항목이 하나라도 있으면 전체 삭제 계획이 보류된다. 잘못된 완료 영수증이나 변조된 완료 아카이브는 검증 실패이며 정상 목록으로 포함되지 않는다.

자동백업 worker의 `.automation-실행UUID.json`은 완료 영수증과 동일한 6필드를 갖는다. 실행 UUID·파일 권한·현재 원본 쌍과의 일치를 확인하며, 호스트 실행 기록이 영속화되기 전인 `automation-pending` 항목으로 표시한다. 해당 원본을 보호하고 전체 삭제를 보류한다. 자동화가 호스트 기록 발급·fsync 후 검증된 `backup-ack`로 marker를 제거하면 다음 계획부터 정상 보존 정책을 적용한다. 원본이 없는 marker나 일치하지 않는 marker는 실패이며 임의로 무시하지 않는다.

## UTC 일별 14·주별 8·월별 12 보존

다음 집합의 합집합을 원본에서 보존한다.

1. 현재 UTC 날짜와 이전 13개 날짜별 최신 백업.
2. 현재 ISO 주(월요일 시작)와 이전 7개 주별 최신 백업.
3. 현재 달과 이전 11개 달별 최신 백업.
4. 전체 최신 백업 1개와 제공된 복원 증거가 가리키는 모든 백업. 그중 가장 최근에 무결성을 검증한 복원본을 별도로 표시한다.

같은 완료 시각이면 UUID 문자열 순서가 큰 항목을 선택한다. 빈 날짜·주·달을 더 오래된 백업으로 채우지 않는다. 백업이 1개뿐이거나 보존 창보다 오래되었어도 최신 백업은 삭제하지 않는다. 미래 시각, 비 UTC 시각, 잘못된 날짜, JSON 중복 필드, 불리언/부동소수 금액·크기, 범위 초과 입력은 거부한다.

삭제 후보마다 현재 검증 가능한 복제본이 필요하다. 복제본이 없으면 해당 원본을 `replica-missing`으로 보존한다. 복제본 손상은 계획 실패다. 복제본 자체를 정리하는 기능은 없다.

## 복원 무결성 증거

`--restore-evidence`는 반복 지정할 수 있으며 각 인수는 격리 복원 디렉터리다. `restore.json`만 있으면 해당 원본은 보호하지만 삭제 허가는 계속 보류한다. 완전한 증거는 같은 디렉터리의 세 파일로 구성한다.

- `restore.json`: `status=quarantined`, `backup_id`, `archive_sha256`, `restored_at`, 전용 `sallimbook_*_restorecheck` DB 이름.
- `backup-manifest.json`: 복원된 백업의 원래 manifest.
- `restore-integrity.json`: `format=1`, `status=restored-integrity-verified`, 같은 백업 ID·아카이브 해시·복원 시각, `verified_at`, 현재 manifest와 restore 영수증의 SHA-256, 그리고 `checks.schema`, `checks.table_counts`, `checks.objects`, `checks.field_ciphertexts`가 모두 JSON `true`.

발급자는 격리 DB의 스키마·테이블 행 수, 객체 크기/해시, 서버 필드 암호문의 인증 복호화를 실제 확인해야 한다. 보존 도구는 증거 파일들의 현재 해시와 상호 참조를 대조한다. 영수증은 서명된 원격 증명이 아니며 신뢰할 수 있는 운영 도구와 파일 소유자가 발급해야 한다. 이 증거는 사용자 보관함 복호화, 생체 인증, 운영 DB 승격 또는 새 서버 전환 승인까지 증명하지 않는다.

## 계획 검토와 명시적 적용

```bash
python -m ops.retention plan \
  --source /private/backups --documents /private/documents \
  --replica /private/replicas --replica-scope local \
  --restore-evidence /private/restore-proof \
  --output /private/plans/review.json
```

기본값 `local`은 삭제 0건과 `independent-replica-declaration-required` 보류를 반환한다. 실제 외부 보관 여부를 확인한 운영자만 `--replica-scope external-declared`를 지정한다. 이 선언은 물리적 독립성을 도구가 검증했다는 뜻이 아니다.

계획은 UTC 기준 시각, 정책, 원본 목록, 파일·디렉터리 식별 정보, 복제본 및 복원 증거 스냅샷, `keep` 사유, `delete` UUID 목록, `pending`, `plan_sha256`을 포함한다. 완전한 복원 증거·외부 보관 선언·현재 정상 복제본이 없으면 삭제하지 않는다. 계획 출력과 경로는 운영 메타데이터이므로 공개 저장소에 올리지 않는다.

운영자가 내용을 검토한 뒤 별도로 기록한 해시를 사용한다.

```bash
python -m ops.retention apply \
  --plan /private/plans/review.json \
  --expected-plan-sha256 REVIEWED_SHA256
```

`apply`는 최대 24시간 이내 계획만 허용한다. 파일 자체의 해시 필드만 신뢰하지 않고 별도 인수와 대조하며, 원래 기준 시각으로 계획을 다시 계산한다. 원본·복제본·증거·정책·디렉터리 식별 정보가 바뀌거나 보류 항목이 있으면 삭제 전에 실패한다. 새 백업이 생겼어도 새 계획을 작성해야 한다.

삭제 전 원본 루트에 `.retention-UUID/intent.json`을 fsync하고, 승인된 파일 쌍을 그 전용 디렉터리로 옮긴다. 모든 보호 원본과 후보 복제본, 복원 증거를 다시 검증한 다음 이동한 원본 파일만 삭제하고 `result.json`을 기록한다. 각 단계는 파일/디렉터리 fsync를 수행한다. 최신/복원 보호 원본과 복제본은 삭제 대상에 포함하지 않는다.

다중 파일 삭제는 하나의 DB 트랜잭션이 아니다. 중단 시 이미 승인된 일부 원본이 삭제되거나 저널 안에 남을 수 있다. 미완료 저널과 남은 암호문은 보존되며 새 계획은 전체 삭제를 보류한다. 운영자가 `intent.json`, 원본/저널/복제본 상태를 대조해 복구해야 하며 자동 재시도·자동 저널 청소는 없다. 완료 저널은 감사 기록으로 남는다.

## 실행한 검증과 한계

합성 암호문 바이트와 임시 `0700` 디렉터리만 사용하는 검증:

```bash
uv run --project services/api python -m unittest tests.operations.test_retention -v
uv run --project services/api ruff check --config services/api/pyproject.toml \
  ops/retention.py tests/operations/test_retention.py
```

현재 36개 테스트가 통과했다. UTC 보존 합집합, 최신/복원본 보호, 누락·손상 복제본, 메타데이터만 있는 복원 증거, 불완전 원본, 복제 중단과 명시적 복구, 삭제 중단과 저널 보류, 계획 변조·만료·원본/증거 변경, 잠금 충돌, 링크·FIFO·권한·UID·JSON·미래 시각을 포함한다. Ruff 검사도 통과했다. `pnpm test:docs`는 문서 69개·로컬 링크 331개 검사와 전체 104개 테스트를 통과했다.

이 변경 자체는 실제 고객 백업·키·DB에 접근하지 않았으며 외부 저장소 업로드, 실제 보존 삭제, 독립 호스트 복원, 전원 단절 시 파일시스템 동작은 검증하지 않았다. 실환경 목록 및 삭제 0건 계획 결과는 운영 증거와 별도로 기록해야 한다.

현재 운영 결정: 사용자가 외부 백업 위치 마련을 운영 시작 이후로 유예했다(`pending-as-user-deferred`). 실제 외부 복제는 수행하지 않았으며 replica 없는 운영 계획은 삭제 0건을 유지한다. 도구와 합성 검증 완료를 독립 백업 확보로 보고하지 않는다.
