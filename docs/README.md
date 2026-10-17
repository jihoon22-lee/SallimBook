# 설계 문서 안내

SallimBook v1.0.0을 구현하기 위한 문서다. **작성 완료는 기능 구현·보안 검증 완료를 뜻하지 않는다.**

## 시작 순서

[프로젝트 소개](../README.md) → [공통 개발 지침](../AGENTS.md) → [제품 요구사항](product-requirements.md) →
[계산 규칙](domain-and-calculation-rules.md) → 담당 기능의 아키텍처·DB·API·화면 →
[구현 백로그](../planning/ISSUES.md) 순서로 읽는다.

| 문서 | 다루는 내용 |
|---|---|
| [제품 요구사항](product-requirements.md) | 22개 필수 요구사항과 v1 제외 범위 |
| [아키텍처](architecture.md) | 공통 React, Kotlin 경계, 모듈형 단일 서버, 배포 구조 |
| [도메인·계산 규칙](domain-and-calculation-rules.md) | 월 스냅샷·비교 범위·납부·보험금·재고의 기준 |
| [DB 모델](data-model.md) | 논리 테이블, 관계, 필드, 무결성, 트랜잭션 |
| [API 계약](api-contract.md) | 경로, 입력·응답, 인증, 충돌, 멱등성 |
| [화면 명세](screen-specifications.md) | 26개 화면, Android/PC 배치·입력·상태·오류 |
| [보안·인증](security-authentication.md) | 위협 모델, 계정/잠금/복호화, 민감정보 정책 |
| [보관함 키 수명주기](vault-key-lifecycle.md) | 부부 공유, 새 기기, 복구, 회전, 로컬 CVC |
| [첨부 서버 검증](testing/documents-server.md) | 인증 다운로드, 암호화 저장, typed 연결, 정리 정책과 시험 결과 |
| [보험 사건 흐름](insurance-workflows.md) | 진료 트리, 복수 청구, 분할 지급, 정산 예시 |
| [개발 환경](development-environment.md) | WSL, 버전 고정, Android 빌드, 환경 분리 |
| [월 입력 UI 검증](testing/monthly-assets-client.md) | SB-012 확정·정정·멱등 재시도·실제 HTTPS 검증 |
| [자산·계좌 UI 검증](testing/assets-accounts-client.md) | SB-010/011 실제 UI·HTTPS·Android 빌드 검증 범위 |
| [테스트·인수](testing-and-acceptance.md) | 24개 시나리오 및 6개 보안 게이트 |
| [운영·백업](deployment-backup-operations.md) | HTTPS, 서명 APK, 서버/보관함 복구, 장애 |
| [로드맵](roadmap-and-milestones.md) | 9개 마일스톤, 40개 구현 이슈, 선행 작업 |
| [결정·위험·미확정](decisions-risks-open-items.md) | 확정 요구사항과 구현 전 검증 사항 구분 |
| [디자인 시스템](design-system.md) | 모바일 우선, 표·폼·다크모드·접근성 |
| [후속 연동](future-integrations.md) | 금융 거래·자동 수집·OCR의 확장 경계 |
| [저장소 게시](repository-publishing.md) | 실제 생성·업로드 명령과 안전한 재실행 |
| [요구사항 추적](requirements-traceability.md) | 요구사항↔이슈↔검증 연결 |
| [네이티브 경계](native-bridge-contract.md) | Kotlin bridge 명령·허용값·비밀 반환 금지 |
| [공식 참고자료](references.md) | 기술·보안 설계에 사용한 20개 공식 출처 |

## 설계 결정 기록

| ADR | 결정 |
|---|---|
| [ADR: android web shared ui](adr/android-web-shared-ui.md) | Android·PC 공통 UI와 네이티브 보안 경계 |
| [ADR: snapshot first not ledger](adr/snapshot-first-not-ledger.md) | 월간 스냅샷 우선, 전체 거래 원장 연기 |
| [ADR: insurance case and payment](adr/insurance-case-and-payment.md) | 보험 사건·청구·지급 분리 |
| [ADR: vault and local cvc](adr/vault-and-local-cvc.md) | 공유 카드 암호문과 Android 로컬 CVC |
| [ADR: authoritative server online first](adr/authoritative-server-online-first.md) | 서버 기준·온라인 우선·충돌 처리 |
| [ADR: auth domains and recovery](adr/auth-domains-and-recovery.md) | 계정 인증·앱 잠금·암호키 복구 분리 |
| [ADR: private network and app identity](adr/private-network-and-app-identity.md) | 사용자 승인 앱 식별자·API 30·기존 WSL 서버 격리·전용 Tailscale 노드 |

## 문서 유지 규칙

현재 사용자 결정 > 제품 요구사항 > 채택 ADR·계산 규칙 > DB/API/화면 세부 명세 > 구현 순으로 검토한다.
서로 충돌하면 임의로 유리한 문서만 따르지 말고 충돌을 기록한 뒤 관련 문서를 함께 수정한다.
위 우선순위는 검증된 보안 문제를 무시하라는 뜻이 아니다. 보안 문제가 있으면 해당 기능을 중지하고 안전한 설계 변경을 검토한다.

GitHub Issue는 작업 진행 상태, backlog.json은 최초 구현 계획이다. 게시기 재실행은 사람이 수정한 이슈 본문·상태를 덮어쓰지 않는다.
