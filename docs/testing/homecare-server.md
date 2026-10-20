# 가전·소모품 서버 검증

대상: SB-024~SB-027, Issue #33~#36, R-03/R-16/R-17/R-19/R-22.
가전 metadata와 구매·보증, 같은 SKU의 공용 재고, 기기별 주기, 입고·교체·취소·조정,
오늘 기준 확인/구매 상태를 수동 입력 API 24개로 제공한다.

## 실행 결과

```bash
uv run --project services/api python scripts/test_database.py services/api/tests/test_homecare.py services/api/tests/test_homecare_database.py services/api/tests/test_homecare_storage.py
pnpm api:generate
pnpm typecheck
uv run --project services/api ruff check services/api/src/sallimbook/homecare services/api/tests/test_homecare.py services/api/tests/test_homecare_database.py services/api/tests/test_homecare_storage.py
python3 scripts/validate_docs.py
```

순수 계산·입력 계약 33개, 실제 DB/API 34개, 직접 DB 제약 15개로 총 **82개 통과**했다.
격리 시험 DB에서 Alembic `upgrade head`, drift 검사와 전체 downgrade/upgrade를 통과했으며 시험 컨테이너를 정지했다.
초기 시험에서 버전/멱등 헤더가 빠진 잘못된 payload의 기대 상태를 422로 쓴 fixture 하나를 공통 계약 400으로 고친 뒤 다시 통과했다.
SQLAlchemy 2.1의 PostgreSQL DISTINCT ON API도 현재 지원 방식으로 고정했다.

검증한 항목은 T-20/T-21/T-22/T-24, 두 가전의 동일 재고 공유, 동시 마지막 재고 사용과 중복 재전송,
입고 후 교체일 미변경, 취소 후 마지막 유효 교체 재선택, 사용자가 바꾼 override 보존,
부족 재고·음수·단위 변경 차단, 다른 가계의 ID·부모 교체 차단, 직접 원장 덮어쓰기와 캐시 조작 거부다.
가전 구매액·입고 금액으로 자산 스냅샷이나 현금 사실을 자동 생성하지 않는다.

## 남은 인수

이 기록은 서버 범위다. 웹·Android 관리 화면, 실제 HTTPS 흐름, 구매 문서 연결은 후속 PR에서 통합한다.
Galaxy 두 기기 시험과 홈 상단 월간 자산 변화/오늘 소모품 배치도 전체 기능 구현 뒤 검증한다.

리뷰 보완: 참조 없는 가전·소모품·기기별 연결은 If-Match 확인 후 204 삭제한다.
연결 또는 취소된 재고/교체 이력이 남아 있으면 DB RESTRICT FK가 삭제를 막고 409를 반환한다.
같은 트랜잭션의 감사 기록도 실패 시 롤백한다. 다른 가계·버전 충돌·부부 삭제·삭제와 새 연결 동시성
7개를 추가했다. 취소 fixture의 필수 실제 날짜와 200 응답을 바로잡고 82개 전체를 다시 통과했다.

## 리뷰 보완: 해제한 직접 지정일 복원 (WP07, 마이그레이션 0016)

`consumable_replacements`에 `cleared_next_check_override`와 `cleared_link_version`을 추가했다. 두 열은 함께 있거나 함께 없으며(CHECK),
INSERT 트리거는 기록한 version이 해제 직후 연결 상태(같은 version, override 없음)와 맞는지 확인한다. backfill은 없어 0016 이전 행은 NULL이다.
교체 취소는 그 교체가 해제한 날짜를 연결 version이 해제 직후와 같을 때만 되살리고 version을 1 올린다. 해제 뒤 연결 PATCH가 있으면 현재 설정을 유지한다.

```bash
uv run --project services/api ruff check services/api/src services/api/tests services/api/migrations
uv run --project services/api pytest services/api/tests -m 'not database' -q
TMPDIR="$HOME/.cache/sallimbook-tmp" pnpm test:database services/api/tests/test_homecare_database.py -q
TMPDIR="$HOME/.cache/sallimbook-tmp" pnpm test:database services/api/tests/test_exports.py -q
TMPDIR="$HOME/.cache/sallimbook-tmp" pnpm test:database services/api/tests/test_database.py -q
```

- DB 제약 시험은 구현 전 ORM 열 없음으로, 복원 시험 2개는 복원 안 됨(override None, version 2)으로 실패를 확인한 뒤 통과했다.
  설정 변경 뒤 유지·0016 이전 행 미복원 guard 2개는 구현 전후 모두 통과한다.
- 실제 DB homecare **38개**, exports **17개**, database **5개** 통과. 각 실행 뒤 `alembic check`, downgrade base, upgrade head를 통과했다.
- DB 없는 시험 **912개 통과**(10 skip). ruff check·format 통과.
- 재전송은 멱등 결과를 그대로 돌려주어 다시 복원하지 않고, 복원 뒤 이전 version의 PATCH는 409 `VERSION_CONFLICT`다.
  감사 기록은 해제·복원 모두 `next_check_override` 필드 이름만 남긴다.
- **미실행:** 운영 DB 적용. 배포 때 0016 upgrade를 적용하며 기존 행은 바꾸지 않는다.
