# 가전·소모품 서버 검증

대상: SB-024~SB-027, Issue #33~#36, R-03/R-16/R-17/R-19/R-22.
가전 metadata와 구매·보증, 같은 SKU의 공용 재고, 기기별 주기, 입고·교체·취소·조정,
오늘 기준 확인/구매 상태를 수동 입력 API 21개로 제공한다.

## 실행 결과

```bash
uv run --project services/api python scripts/test_database.py services/api/tests/test_homecare.py services/api/tests/test_homecare_database.py services/api/tests/test_homecare_storage.py
pnpm api:generate
pnpm typecheck
uv run --project services/api ruff check services/api/src/sallimbook/homecare services/api/tests/test_homecare.py services/api/tests/test_homecare_database.py services/api/tests/test_homecare_storage.py
python3 scripts/validate_docs.py
```

순수 계산·입력 계약 33개, 실제 DB/API 27개, 직접 DB 제약 15개로 총 **75개 통과**했다.
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
