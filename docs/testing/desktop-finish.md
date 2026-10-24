# PC 금액 표·앱 식별 자산 검증

Issue #167 · R-02/R-03/R-04/R-05/R-06/R-19. P15와 관련 작은 표시 수정을 기록한다.

## 동작

- 1000px 이상에서 월 기록·비교를 실제 표로 표시한다. 좁은 화면에는 카드 한 벌만 렌더링하며 금액 입력 편집기·409·확정 명령을 공유한다.
- 월 기록은 서버 가계 보유분을 앞세우고 등록 순/이름 순/보유분 큰 순을 제공한다. 미입력은 0원과 구분한다. 전월 복사 미확인 안내는 접지 않는다.
- 비교는 같은 대상/지분 변경/편입·제외/비교 대기·참고 묶음을 유지한다. 각 묶음의 변화 크기는 서버 순자산 영향 문자열을 BigInt 절댓값으로 비교한다. 부채 부호를 다시 뒤집거나 지분을 재적용하지 않는다. 금액 없음은 묶음 마지막이다.
- 계좌 상세의 선택 월 평가액은 연결 자산의 월 기록과 동일한 원천이다. 자산 기본정보 목록은 금액 조회가 아니며 이번 달 기록 바로가기는 과거 월 선택과 독립적이다.
- 설정은 로그인 상태에서 구성원 관리로 연결하며 웹 버전과 설치된 Android 버전·빌드를 함께 표시한다. 앱 정보 조회 실패는 별도 재시도를 제공한다.
- 기본 비용 분류 `other`는 기타로 표시하되 API 값은 유지한다. 사용자 입력 분류는 그대로 표시한다. 문서 크기는 바이트/KiB/MiB로 표시한다. 실제 이름과 이유 문자열 뒤에 붙던 고정 조사를 문장 구조로 해결한다.
- 앱 책 도형은 기존 SVG와 동일하다. 웹 파비콘/theme-color, Android adaptive icon과 vector splash를 맞추고 기본 템플릿 PNG를 제거했다. 최소 Android API 30을 유지한다.

## 검증 경계

모든 자료는 합성 데이터다. API·DB 계약이나 금액 계산·보관함 경계는 변경하지 않는다. 기존 설치 앱 업데이트와 런처별 아이콘 마스크·네이티브 화면 색/말투는 사용자가 직접 확인하는 실기기 인수로 남긴다. 개발용 APK 빌드는 정식 배포와 구분한다.

## 실행 결과

- `pnpm test:web desktop-finish.spec.ts months.spec.ts comparison.spec.ts assets-months-native.spec.ts settings-audit.spec.ts settings-audit-native.spec.ts --workers=4`: 첫 실행 159개 통과, PC 전월 복사 안내가 접혀 있던 1건 실패. 안내를 항상 노출하도록 수정했다.
- `pnpm test:web desktop-finish.spec.ts assets-months-native.spec.ts design-refresh.spec.ts insurance-events.spec.ts --workers=4`: 안내 수정과 화면·테마 회귀 122개 통과. 변경된 환불 문구의 옛 문자열을 기대한 2건은 테스트 기대 문구를 수정했다.
- `pnpm test:web documents-ui.spec.ts documents-native-ui.spec.ts homecare-workflow.spec.ts insurance-events.spec.ts --workers=4`: 162개 통과. 환불 정정 원본 사유 보존, 문서·소모품 웹/native 흐름 포함.
- 최종 `pnpm test:web desktop-finish.spec.ts --workers=4`: 12개 통과. 2^53 초과 정수 정렬, null/0, 지분·범위·부채, 우측 금액, 표 5개 항목 높이, 편집 중 PC↔모바일 전환 초안 보존, 설치 버전 실패·재시도 포함. 합성 PC 캡처도 확인했다.
- `uv run --project services/api pytest services/api/tests/test_asset_calculations.py services/api/tests/test_asset_months.py services/api/tests/test_asset_comparison.py services/api/tests/test_accounts.py -m 'not database' -q`: 117개 통과. `pnpm test:database services/api/tests/test_asset_comparison.py -q`: 실제 PostgreSQL 40개 통과, migration 왕복·모델 일치 확인.
- `uv run --project services/api python scripts/test_web_auth.py --comparison`: 실제 HTTPS/API/PostgreSQL에서 월 작성·확정·정정·비교·추이 통과. HTTP mock 없음.
- `pnpm android:build`(JDK 21·전용 SDK 명시): debug 빌드 및 JVM 467개 통과. 벡터 리소스 compile·package 포함. release 배포 및 실제 기기 인수와 구분한다.
- `pnpm typecheck`, `pnpm lint`, `pnpm format:check`, `pnpm build`, `python3 scripts/validate_docs.py`, `python3 -m unittest discover -s tests -v`: 통과. 문서 도구 258개. 기존 Vite 큰 청크·Gradle deprecation 경고는 남는다.
