# 현행 검사기 포함 릴리스의 업그레이드 리허설

2026-10-25 · R-20/R-21 · SB-036/SB-040 · [#178](https://github.com/jihoon22-lee/SallimBook/issues/178).

## 문제와 수정

`ops.test_upgrade`는 이전 이미지에 검사기가 없다고 가정했다. 검사기를 이미 사용하는 0.1.9를
이전 버전으로 지정하면 API가 의존하는 inspector가 합성 Compose에 없어 실행 시작 전에 실패했다.
이전 commit의 renderer가 inspector를 제공하면 시험용 서비스에도 포함하며, 업그레이드 중지와
되돌리기 기동·health 검사에 같은 집합을 사용한다. inspector가 없는 옛 버전도 지원한다.
알 수 없는 새 의존성을 임의로 빼지 않고 시험 실패로 처리한다.

0018→0021에는 기존 구성원과 같은 UUID의 가족 backfill과 빈 주문 표가 추가된다.
가족은 기존 구성원과 ID·가계·관계·감사 actor가 일치하는지 별도 확인하고 기존 표/열의 해시는
그대로 비교한다. 주문 표는 0021 이전 schema에서 새로 생긴 **빈 표일 때만** 허용한다.
기존 주문 표, 주문 행이 생긴 경우, 기존 표의 hash 변경·누락, 알 수 없는 새 표는 계속 실패한다.
0020은 이력 삭제 제약 변경이며 기존 행을 변환하지 않는다.

## 격리와 검증 수준

무작위 `sallimbook-ops-smoke-*` 프로젝트와 합성 계정/키/DB/볼륨을 사용한다.
호스트 포트와 Tailscale 노드는 만들지 않는다. 종료 시 이 시험 프로젝트의 컨테이너·볼륨만 지운다.
운영 DB 변경이나 실제 기기의 업데이트 검증을 대신하지 않는다.

- 서비스 집합·예상치 못한 의존성, 기존 hash 보존·새 표 제한의 단위 검사 7개 통과.
- 전체 문서/운영 도구 263개 통과. Ruff·문서/링크·diff 검사 통과.
- 실제 이전 이미지 `53a2c72`(0.1.9/schema0018) → 후보 `0d1ea55`(0.1.10/schema0021):
  이전 API로 합성 기록 작성·이전 worker 백업, upgrade-required 확인, migration·새 서비스 health,
  0018로 downgrade·이전 서비스 health, 기존 표의 행 수/해시 보존, 재업그레이드와 회차 5개
  재생성까지 통과했다. 합성 프로젝트와 전용 볼륨을 정리했다.
- 최초 실패는 이전 Compose의 inspector 누락이었다. 실제 운영은 변경하지 않았다.
  고친 시험 도구로 위 전 과정을 다시 실행한 결과이며, 릴리스 APK나 실제 폰 설치 검증과 구분한다.

```bash
python3 -m unittest discover -s tests/operations -p test_upgrade_snapshot.py -v
uv run --project services/api ruff check --config services/api/pyproject.toml ops/test_upgrade.py tests/operations/test_upgrade_snapshot.py
python3 -m ops.test_upgrade --old-image sallimbook-api:0.1.9 --new-image sallimbook-api:0.1.10
```

실제 운영 전환은 [운영 runbook](../operations-runbook.md)의 점검 시간·기존 백업·migration·서명 APK·복원 점검 절차를 따른다.
