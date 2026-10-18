# 요구사항 추적표

설계 → 구현 Issue → 실행 근거의 연결이다. 각 검증 기록의 명령·commit·환경·미실행 범위를 함께 읽는다.
테스트 ID와 구현된 코드만으로 실제 기기·운영·출시 인수를 완료 처리하지 않는다.

| 요구사항 | 구현 Issue | 주요 검증 | 근거 문서 |
|---|---|---|---|
| R-01 | SB-005, SB-006, SB-007, SB-032 | 부부 공동 접근/타가계 차단 | [인증 HTTPS](testing/browser-authentication.md), [패스키](testing/passkeys-web.md) |
| R-02 | SB-001, SB-003, SB-031, SB-034, SB-038 | Android/PC 교차조회·업데이트 | [웹·Android adapter](native-bridge-contract.md), [설정·26개 경로](testing/settings-audit.md), [실기기 게이트](testing/native-security-proof.md) |
| R-03 | SB-003, SB-013, SB-027, SB-033 | T-24 / 홈 레이아웃 | [월 비교](testing/assets-comparison-client.md), [오늘 소모품·홈](testing/homecare-client.md) |
| R-04 | SB-010 | T-01/T-03 | [자산·계좌](testing/assets-accounts-client.md) |
| R-05 | SB-012, SB-013 | T-05~T-07 | [월 기록](testing/monthly-assets-client.md), [비교](testing/assets-comparison-client.md) |
| R-06 | SB-011 | T-02/T-04 | [계좌 단일 원본](testing/assets-accounts-client.md) |
| R-07 | SB-014, SB-022 | T-08/T-18 | [생활비](testing/cashflow-client.md), [보험 수령](testing/insurance-client.md) |
| R-08 | SB-015, SB-016, SB-018 | T-09~T-11 | [예정·실제·원금](testing/cashflow-client.md) |
| R-09 | SB-017, SB-018, SB-029 | 일반 응답 비밀 없음·종료 참조 | [카드·종료 연결](testing/cashflow-client.md), [보관함 개요](testing/vault-overview.md) |
| R-10 | SB-008, SB-009, SB-028, SB-029, SB-031, SB-032, SB-039 | G2~G5 / 30초·이탈 잠금 | [서버](testing/vault-server.md), [암호 벡터](testing/native-vault-crypto.md), [Android 수명](testing/native-vault-lifecycle.md), [웹](testing/vault-web.md) |
| R-11 | SB-006, SB-008, SB-009, SB-029, SB-032, SB-039 | G1/G3 / 실제 기기 | [패스키 웹](testing/passkeys-web.md), [네이티브 정책/미실행 실기기](testing/native-security-proof.md) |
| R-12 | SB-008, SB-009, SB-030, SB-039 | G4 / 백업·전송 제외 | [로컬 CVC 경계](testing/native-vault-lifecycle.md), [미실행 실기기](testing/native-security-proof.md) |
| R-13 | SB-019, SB-023 | 보험료 단일원본·문서권한 | [보험](testing/insurance-client.md), [문서 서버](testing/documents-server.md) |
| R-14 | SB-020 | 트리 순환·다중계약 | [진료 트리·다중 계약](testing/insurance-client.md) |
| R-15 | SB-021, SB-022, SB-023 | T-12~T-19 | [보험 비용·수령·반환](testing/insurance-client.md), [문서](testing/documents-client.md) |
| R-16 | SB-024 | 제품 CRUD·보증·문서 | [가전 서버](testing/homecare-server.md), [가전 화면](testing/homecare-client.md) |
| R-17 | SB-025, SB-026, SB-027 | T-20~T-22 | [재고 불변식](testing/homecare-server.md), [입고·교체 화면](testing/homecare-client.md) |
| R-18 | SB-011, SB-014, SB-015, SB-017, SB-018, SB-019, SB-021, SB-022, SB-028, SB-033, SB-035 | 도메인 연결 E2E | [생활비 연결](testing/cashflow-client.md), [보험 연결](testing/insurance-client.md), [재고/홈](testing/homecare-client.md) |
| R-19 | SB-002, SB-005, SB-007, SB-012, SB-017, SB-026, SB-034, SB-035 | T-22/T-23 / 종료·정정 | [월 정정](testing/monthly-assets-client.md), [재전송·충돌](testing/cashflow-client.md), [재고 동시성](testing/homecare-server.md), [감사 조회](testing/settings-audit.md), [네이티브 감사 경계](testing/native-audit.md) |
| R-20 | SB-009, SB-023, SB-032, SB-037, SB-039 | G6 / 복원·민감export 제외 | [첨부 권한](testing/documents-server.md), [내보내기 서버](testing/exports-server.md), [웹](testing/exports-client.md), [Android](testing/native-exports.md) |
| R-21 | SB-001, SB-036, SB-038 | 정식서명·HTTPS·업그레이드 | [고정 도구/실행](development-environment.md), [운영·배포 인수 기준](deployment-backup-operations.md) |
| R-22 | SB-002, SB-004, SB-007, SB-010, SB-013, SB-014, SB-016, SB-021, SB-022, SB-026, SB-035 | T-01~T-24 | [T-01~24 명세](testing-and-acceptance.md), [공통 fixture](../packages/test-fixtures/README.md) |

최종 전체 인수는 SB-040에 모은다. 현재 [통합 검증 기록](testing/final-integration.md)과
[운영 도구·복원 절차](operations-runbook.md)를 연결한다. 요구사항 정의는
[제품 요구사항](product-requirements.md), 검증 방법은 [테스트 명세](testing-and-acceptance.md)를 따른다.

R-20/R-21의 실제 백업·격리 복원 근거는 [운영 백업·복원 기록](testing/operating-backup-restore.md)에 있다.
외부 백업 위치 결정은 사용자 요청으로 운영 시작 뒤로 유예했으며, 현재 로컬 사본을 독립 보관으로 세지 않는다.

실제 Galaxy 2대의 인증·Keystore/CVC·수명주기·접근성·데이터 보존 업데이트와,
실기기의 RP/DAL·패스키 연결, 서명키 독립 보관·운영 복원 인수는 별도 증거가 필요하다. 이 항목들을
JVM·가상 WebAuthn·브라우저 크기 모의시험으로 대체하거나 완료로 표시하지 않는다.

Issue #87은 R-01/R-02의 처음 시작과 배우자 연결을 웹/Android에서 직접 수행하도록 보완한다.
기존 CLI 전용 시작과의 요구사항 충돌 및 새 권한 경계는 [ADR 0008](adr/mobile-first-start.md)에 기록했다.
