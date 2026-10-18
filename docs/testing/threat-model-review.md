# SB-009 · 인증·복구·공유 보관함 위협모델 설계 리뷰

2026-10-18 · [Issue #18](https://github.com/jihoon22-lee/SallimBook/issues/18) · R-10/R-11/R-12/R-20.
검토 대상은 **`3ca1bd3b7c80613fa67fb3ee287292ad2e5eec54`**의 소스·설계·시험 코드다.
이후 커밋이나 실제 배포 환경으로 판정을 자동 확대하지 않는다.

## 판정과 범위

**검토한 경계에서 새로 확정한 인증 우회·평문 전송·복구 키 혼용 설계 결함은 없다.**
계정 복구와 보관함 복구가 분리되고, 지원하는 CVC 기능에 서버·웹·일반 백업 경로가 없으며,
미검증 암호/기기 가정과 G1~G6의 증거·완료 조건을 아래에 추적한다.
따라서 SB-009의 설계 리뷰 완료와 실제 기기/출시 인수 완료를 별도로 판단할 수 있다.
#18 종료가 #17/#37~41/#48 종료, CVC 활성화 또는 v1 출시 승인을 뜻하지 않는다.

이번 작업은 기존 기능 구현 보고를 그대로 인용하는 대신 호출 경로·키 흐름·거절 조건을 대조한
별도 내부 설계 검토다. 작성자는 이전 Android 보관함 구현에도 참여했으므로 전 구성요소의
구현자로부터 독립된 외부 보안 감사로 표현하지 않는다. 서버·웹 소스의 교차 검토와 기존
[서버 리뷰](vault-server.md), [웹 리뷰](vault-web.md), [네이티브 별도 리뷰와 수정](native-vault-lifecycle.md)의
근거를 함께 사용한다. 문서의 최종 수용은 다른 검토자가 이 기준 커밋과 근거를 확인하는 절차다.

실제 키·사용자 자료·운영 DB·비공개 백업·기기에는 접근하지 않았다. Docker, ADB, 생체 인증,
침투 시험, DB/브라우저/JVM 시험을 이번 리뷰에서 실행하지 않았다. 기존 실행 기록과 시험 코드의
존재는 새 실행 성공으로 세지 않는다. 암호학적 형식 증명이나 전체 의존성 감사도 범위 밖이다.

## 보호 자산과 공격자

| 자산/경계 | 신뢰하는 것 | 신뢰하지 않거나 별도 검증하는 것 |
|---|---|---|
| 계정·가계 접근 | 서버의 현재 session/device/member 상태와 목적별 재인증 | JS bool, 보유 ID, CORS, UI의 숨김, 철회 전 응답 |
| PAN·유효기간/HVK | 정품 클라이언트와 입력 시점의 OS/브라우저, 별도 보관함 암호 | DB·암호화 백업 사본만 가진 공격자, 다른 가계, 미공유/철회 구성원 |
| Android Device KEK | Android Keystore의 인증별 키 연산 | 앱 잠금 성공만으로 키를 사용할 수 있다는 가정, Intent/bridge 인증 결과 |
| CVC | 직접 입력한 해당 Android의 별도 로컬 키/화면 | 서버·PC·export·클라우드/기기 이전·앱 복원 |
| 일반 금융·의료 데이터 | 서버 운영자와 서버 field keyring | 비인증 접근·타가계 ID·비공개 파일 URL 추측 |
| 복구·배포 | 별도 보관한 복구 자료와 검증된 배포/복원 절차 | 로그인 암호 재설정의 자동 HVK 해제, 과거 백업의 무조건 운영 전환 |

검토한 공격자는 네트워크 관찰/재전송자, 다른 가계 사용자, 일반 가계 가입만 한 사용자,
철회된 구성원/기기, 세션을 탈취한 공격자, DB/백업을 얻은 공격자, 웹 코드 주입자와 분실 기기
보유자다. 이미 HVK를 얻은 공동 구성원, 악성 배포 서버, 루팅/손상된 OS, 악성 키보드·접근성
서비스, 화면 외부 촬영자는 완전 차단을 보장하지 않는 경계로 명시한다.
앱 전체가 E2EE인 것은 아니며, 카드 보관함도 악성 웹 배포까지 방어하는 구조는 아니다.

## 키 흐름과 인증 분리

```text
계정 비밀번호/패스키 ── 서버 session/device/member 검증 ── opaque API 접근
앱 잠금 인증 ────────── 현재 기기의 UI/요청 gate 해제
                           (위 두 경로는 HVK를 만들거나 복호화하지 않음)

별도 보관함 암호 ─ PBKDF2-HMAC-SHA256 ─ Member KEK ─ member wrapping ─ HVK
오프라인 랜덤 코드 ─ HKDF-SHA256 ───── Recovery KEK ─ recovery wrapping ─ HVK
Android CryptoObject + 인증별 Device KEK ──────────── 로컬 wrapping ─ HVK
HVK + 가계/카드/버전 AAD ─ AES-256-GCM ─ PAN·유효기간 (CVC 없음)
별도 인증별 Local CVC key + 기기/카드/envelope AAD ─ 로컬 CVC (네트워크 없음)
```

계정 비밀번호는 서버의 Argon2id 검증 재료다. 보관함 암호는 클라이언트 PBKDF2 입력이며
계정·refresh·passkey 처리에서 HVK로 파생되는 연결은 없다. 현재 identity router에는 계정
비밀번호 재설정으로 보관함을 여는 endpoint가 없다. 계정 복구 기능을 향후 추가해도
기존 member ID/권한 처리와 HVK 복구를 별도로 설계해야 하며, 이 리뷰가 그 미래 구현을 승인하지 않는다.
근거: [인증 서비스](../../services/api/src/sallimbook/identity/service.py)의 `reauthenticate`,
[인증 router](../../services/api/src/sallimbook/identity/router.py),
[분리 ADR](../adr/auth-domains-and-recovery.md).

서버의 `get_recovery_wrapping`과 `recover`는 현재 계정·기기·가계뿐 아니라 활성 vault membership과
최근 계정 인증 또는 해당 목적/대상의 증명을 요구한다. 복구코드 원문을 서버에 보내지 않는다.
클라이언트는 복구코드로 HVK를 풀고 현재 key check를 검증한 뒤 본인의 새 member wrapping과
새 recovery wrapping을 함께 제출한다. 철회 계정에 복구코드만 있다고 온라인 접근을 되살리지 않는다.
모든 복구 수단을 잃으면 서버 관리자가 복호화할 수 없고 재등록이 필요하다.
근거: [vault service](../../services/api/src/sallimbook/vault/service.py)의 `get_recovery_wrapping`,
`recover`; [Android actions](../../apps/client/android/app/src/main/java/io/github/jihoon22lee/sallimbook/auth/NativeVaultActions.kt)의
`recover`; [웹 workflow](../../apps/client/src/features/vault/workflow.ts)의 복구 분기.

Android 앱 잠금에는 기기 credential을 사용할 수 있지만 보관함 Device KEK는
`setUserAuthenticationParameters(0, AUTH_BIOMETRIC_STRONG)`을 사용한다. 실제 요청의
`CryptoObject.cipher`가 동일한지 검사하고 한 번만 `doFinal`을 수행한다. 성공 bool·프런트 플래그로
대체하지 않는다. strong 생체 사용이 불가능하면 명시적 보관함 암호 경로를 제공하며 무보호
Keystore 키로 자동 대체하지 않는다. PIN에서 자체 AES 키를 만들지 않는다.
근거: [NativeVaultStore](../../apps/client/android/app/src/main/java/io/github/jihoon22lee/sallimbook/auth/NativeVaultStore.kt)
`prepareEncryption`/`finish`,
[NativeVaultActivity](../../apps/client/android/app/src/main/java/io/github/jihoon22lee/sallimbook/auth/NativeVaultActivity.kt)
`beginPrompt`/`finishPrompt`/`viewForm`.

## 공격 경로별 검토

| 공격/오용 시도 | 확인한 제어와 코드 근거 | 시험 근거/남은 한계 |
|---|---|---|
| 일반 가계 가입 또는 타가계 ID로 암호문 읽기 | `vault/service.py:_lock`, `_enrolled`, scoped 조회. membership과 대상 가계를 재검사 | `test_vault.py:test_unshared_and_foreign_household_cannot_fetch_opaque_data`; 가계 초대는 vault 공유가 아님 |
| 세션 만료/기기 폐기와 읽기·쓰기 경합 | `_lock`이 session→device→가계/보관함을 잠그고 `_read`/`_run`이 commit 직전 `recheck` | `test_revocation_barrier_wins_before_opaque_read`, 최근 인증/step-up 시험. 이미 전송된 응답/평문을 원격 회수하지는 못함 |
| 거짓 `key_check_confirmed=true`로 인증 우회 | strict bool은 사용자 확인 기록. 서버는 별도 권한·최근 인증을 검사하며, 클라이언트는 실제 unwrap/key check | `schemas.py`의 `VaultModel`/`Confirmed`, `NativeVaultActions.unlock`, 웹 `unwrapMember`/`unwrapRecovery`. 서버가 키 소유를 암호학적으로 증명한다고 해석하지 않음 |
| 암호문·AAD·카드·키 버전 치환, KDF 자원 고갈 | 고정 길이, canonical UUID/base64url, KDF 600k~2M, 원래 UTF-8, purpose별 AAD, GCM tag·payload·last4 대조 | [공통 벡터](../../packages/test-fixtures/vault-v1.json), `test_vault_schemas.py`, `vault-crypto.spec.ts`, `NativeVaultCryptoTest.kt`. 실제 Android provider 호환은 별도 |
| nonce 재사용, 중복 mutation, stale 저장 | [storage](../../services/api/src/sallimbook/vault/storage.py)의 nonce 원장, DB 제약, If-Match, Idempotency-Key. 중단한 키 버전도 재사용하지 않음 | `test_nonce_is_unique_across_crypto_purposes`, `test_card_secret_revision_cas_and_changed_idempotent_payload`, `test_abort_burns_key_version_and_retains_prepared_nonce_reservations` |
| 불완전 키 교체를 current로 활성화 | source 카드/revision·구성원/version manifest 고정, staging 중 변경 동결, `_complete_snapshot` 후 원자 전환 | [DB 우회 시험](../../services/api/tests/test_vault_database.py)의 partial activation/manifest 조작. 클라이언트의 평문 동일성 확인과 실제 중단/재개는 추가 인수 |
| JS에서 비밀·토큰·임의 암호문 요청 | native private HTTP와 status/ID UI 계약 분리. `vaultMetadata`는 status/shares/rotation의 안전 DTO만 투영 | [bridge 계약](../native-bridge-contract.md), [NativeVaultUiPolicy](../../apps/client/android/app/src/main/java/io/github/jihoon22lee/sallimbook/auth/NativeVaultUiPolicy.kt), `vault-native-bridge.spec.ts`. 실제 WebView instrumentation 별도 |
| 외부 Activity/프레임의 인증 성공 위조 | vault Activity 비공개·정확 extras, session generation/foreground gate. legacy bridge 설치 차단, 번들 origin 제한 | [MainActivity](../../apps/client/android/app/src/main/java/io/github/jihoon22lee/sallimbook/MainActivity.kt), [SecureBridgeWebView](../../apps/client/android/app/src/main/java/io/github/jihoon22lee/sallimbook/SecureBridgeWebView.kt). 동일 origin의 악성 코드까지 신뢰할 수 있다는 뜻 아님 |
| 취소/화면 이탈/시간 만료 뒤 늦은 결과 표시 | 작업 세대·단조 시계·최종 소비 검사, 최대 30초 표시, native pause/초점 상실 즉시 폐기, 웹 blur/pagehide/unmount 폐기 | [NativeVaultLifetime](../../apps/client/android/app/src/main/java/io/github/jihoon22lee/sallimbook/auth/NativeVaultLifetime.kt), [웹 lifetime](../../apps/client/src/features/vault/lifetime.ts), fake-clock/지연 회귀. OS 스케줄링·화면 캡처는 실기기 확인 필요 |
| 재등록 취소·일시적 Keystore 오류로 기존 키 파괴 | 정상 키 재사용, orphan record 거부, 영구 무효화 확인·명시 동의 후만 삭제, AtomicFile 실패 복원 | `NativeVaultKeyPreparationTest.kt`, `NativeVaultStore.prepareEncryption`/`clearInvalidatedRegistration`/`finish`. JVM adapter를 실제 Keystore 결과로 보지 않음 |

시험 이름의 전체 파일은 [서버 API 시험](../../services/api/tests/test_vault.py),
[서버 schema 시험](../../services/api/tests/test_vault_schemas.py),
[웹 암호 시험](../../apps/client/tests/vault-crypto.spec.ts),
[네이티브 암호 시험](../../apps/client/android/app/src/test/java/io/github/jihoon22lee/sallimbook/auth/NativeVaultCryptoTest.kt),
[네이티브 키 보존 시험](../../apps/client/android/app/src/test/java/io/github/jihoon22lee/sallimbook/auth/NativeVaultKeyPreparationTest.kt)에 있다.

## CVC·백업·내보내기 경계

CVC는 `NativeVaultActivity.cvcForm`에서 직접 받는 3~4자리 로컬 값이다. `NativeVaultStore`는
HVK와 다른 purpose/alias와 가계·사용자·member·device·keyVersion·card·envelope ID/revision AAD를
사용한다. 저장 위치는 `noBackupFilesDir`, 파일은 암호문이며 일반 HTTP serializer에 연결되지 않는다.
카드 envelope의 고정 27바이트 payload에는 PAN·유효기간만 있다. 서버/생성 API에 CVC 필드를
추가하지 않으며 strict extra-field 검증으로 CVC 등 평문 필드를 거부한다.

**현재 일반 CVC 저장/열람은 닫혀 있다.** `NativeVaultStore.LOCAL_CVC_ACCEPTANCE_VERIFIED=false`이며,
[release gate](../../apps/client/android/app/src/release/java/io/github/jihoon22lee/sallimbook/auth/NativeVaultAcceptanceGate.kt)의
`allows`도 항상 false다. debug 합성 인수 namespace는 일반 저장소/계정/bridge의 활성화 옵션이 아니다.
실기기 증거와 사용자 선택 없이 이 상수나 release gate를 바꾸는 것은 별도 보안 변경이다.

[manifest](../../apps/client/android/app/src/main/AndroidManifest.xml)의 `allowBackup=false`,
`fullBackupContent=false`와 [전송 제외 규칙](../../apps/client/android/app/src/main/res/xml/data_extraction_rules.xml)의
cloud-backup/device-transfer 전체 제외를 함께 확인했다. 이 설정은 설계 근거이며 제조사 이전 시험의
대체물이 아니다. 재설치/새 기기에서는 CVC를 다시 입력하고 기기 키를 복사하지 않는 것이 요구 결과다.

[사용자 export 공개 목록](../../services/api/src/sallimbook/exports/catalog.py)은 보관함·인증 테이블과
전체 계좌/증권번호를 제외한다. [운영 백업](../../ops/backup.py)의 입력은 서버 DB와 서버 암호화 문서로,
Android 로컬 디렉터리를 수집하지 않는다. 서버 백업에는 **PAN 암호문과 과거 wrapping**이 들어갈 수 있다.
이를 CVC 백업 또는 PAN 평문 저장과 혼동하지 않는다. 사용자 export는 운영 복원용 백업과도 다르다.

이 판정은 지원하는 필드·serializer·저장 경로에 대한 것이다. 사용자가 일반 메모에 비밀을 직접 적거나
공격자가 임의 bytes를 opaque 필드에 넣는 행위까지 서버가 해석해 차단한다는 주장은 하지 않는다.
카드 사진은 typed target 금지·사용자 확인·검사기 거절 정책으로 제한하지만 OCR의 완전 식별을 보장하지 않는다.

## 발견사항과 잔여 위험

심각도는 전제가 성립했을 때의 영향을 뜻한다. **확정 결함**, **추가 방어 과제**, **명시된 잔여 위험**을
같은 상태로 취급하지 않는다. 아래 잔여 위험은 안전을 증명한 결과나 새 우회 취약점 발견이 아니다.
확정된 설계 결함이 추가로 발견되면 #18의 완료 판정을 다시 열고 수정·회귀 근거를 남긴다.

| ID / 분류 / 심각도 | 증거와 정확한 위치(기준 커밋) | 완화·처리와 남은 조건 |
|---|---|---|
| TM-01 / 추가 방어 / 낮음 | `apps/client/index.html:5`의 CSP는 `frame-src 'none'; object-src 'none'`만 설정. 소스 검색에서 별도 script-src/default-src 또는 HTML 삽입 sink는 발견하지 못함 | 이 CSP를 XSS 전체 방어라고 설명하지 않는다. G5/#40/#48에서 배포 응답 header를 포함한 script/connect 정책 및 번들 호환을 검토한다. CSP 부재만으로 현재 XSS exploit을 주장하지 않으며, 주입 경로가 확인되면 높은 심각도 결함으로 재분류한다 |
| TM-02 / 신뢰 경계의 잔여 위험 / 높음 | `crypto.ts:VaultKey`, `WebVaultAction.tsx`, `lifetime.ts`; 웹이 보관함 암호·키·평문을 처리한다 | 악성 동일 origin 코드·확장·서버 배포가 해제 시 데이터를 읽을 수 있다. TLS·의존성/배포 통제·CSP·코드 검토가 필요하며 WebCrypto/메모리 전용 저장으로 해소되지 않는다. 일반 React cache에 넣지 않는 것과 실행 중 JS 접근 불가는 다르다 |
| TM-03 / 권한 있는 공격자의 무결성·가용성 위험 / 중간 | `vault/schemas.py:Confirmed`, `vault/service.py:recover`, `write_card_secret`, `finalize_rotation` | 서버는 키 소유 증명 없이 허용된 계정의 opaque 변경을 저장할 수 있다. 탈취 계정/악성 공동 구성원이 잘못된 wrapping·암호문으로 접근을 망가뜨릴 가능성은 있다. 최근 인증·권한·감사·snapshot/버전·복원 절차가 완화한다. 계정 복구만으로 기존 HVK를 해제하는 기밀성 우회는 아니다 |
| TM-04 / 과거 사본의 잔여 위험 / 높음 | `vault-key-lifecycle.md` 마지막 절, `vault/service.py:rewrap_member`/`recover`, `ops/backup.py:backup` | 이전 암호/코드와 과거 wrapping을 가진 공격자는 같은 HVK를 계속 열 수 있다. 유출 대응은 새 HVK 전체 회전까지 수행한다. 명시적 카드 비밀 삭제는 온라인 모든 버전을 폐기하지만 과거 백업·오프라인 사본을 회수하지 않는다 |
| TM-05 / 기기 신뢰 가정 / 높음 | `NativeVaultStore.kt:prepareEncryption`/`finish`, `NativeVaultActivity.kt:input`/`close`, `data_extraction_rules.xml` | 실제 강한 생체·키 무효화·입력/화면 보호·백업 제외는 #17/#38/#39/#48에서 합성 데이터로 검증한다. CVC gate를 닫아 둔다. 루팅/감염 기기·외부 촬영·런타임 내부 사본의 완전 소거를 보장하지 않는다 |
| TM-06 / 복구 가용성 가정 / 높음 | `vault/service.py:get_recovery_wrapping`/`recover`, `NativeVaultActions.recover`, 웹 `unwrapRecovery` | 계정 접근이 있어도 보관함 암호·복구코드·사용 가능한 신뢰기기를 모두 잃으면 복호화 불가다. 오프라인 코드 확인·별도 보관·복구 훈련이 필요하다. 관리자 평문 우회나 기기 키 복사는 해결책으로 허용하지 않는다 |

TM-01은 출시 G5에서 평가할 방어 보강 항목이며 #18의 키/인증 분리 설계에 대한 확정 결함은 아니다.
TM-02~06은 현재 제품의 신뢰 경계·복구 제약을 숨기지 않기 위한 기록이다. 잠재 영향이 높다는 이유로
검증을 통과한 것으로 간주하지 않으며 아래 담당 Issue와 게이트를 계속 유지한다.

## 미검증 가정과 폐쇄 증거

| 가정 ID | 아직 증명하지 않은 것 | 필요한 증거 / 담당 |
|---|---|---|
| A-01 | 실제 두 Galaxy의 JCA/Keystore가 바이너리/UTF-8 벡터와 정책대로 작동 | 같은 공개 fixture의 실제 Android↔웹 roundtrip, 잘못된 암호·AAD·tag 거절, 600k~2M 비용/취소 측정 · #37/#41, G2/G3 |
| A-02 | strong auth-per-use, 등록 변경 무효화, 취소/늦은 콜백/잠금에서 키를 사용할 수 없음 | 모델·OS·APK hash별 CryptoObject 실제 연산과 실패 기록, 기기 인증 등록 변경·제거, 정상/무효 키 재등록 취소·오류 · #17/#38, G3 |
| A-03 | FLAG_SECURE·키보드/자동완성·최근 앱·백업/제조사 전송에 CVC/PAN이 남지 않음 | 합성 canary로 화면/로그/프록시/bridge/backup/재설치·이전 검사. 원문 캡처 대신 검사 결과만 기록 · #38/#39/#48, G4 |
| A-04 | 두 계정의 공유/철회·새 기기·중단 회전/복구가 실제 UI에서 일관됨 | 새/구/잘못된 복구코드, 프로세스 종료, 최근 인증 만료, 동일 요청 재시도, finalize 전후 장애의 양쪽 기기 결과 · #41, G2/G3/G6 |
| A-05 | 실제 배포 웹의 실행 코드·스크립트 경계와 정식 native origin/RP/DAL이 올바름 | 배포 header·script 의존성·XSS sink/주입 회귀, 정식 서명 origin·패스키 취소/재인증 검사 · #40/#48 및 #15, G1/G5/G6 |
| A-06 | 과거 백업을 복원해도 폐기된 세션/키 상태를 무심코 되살리지 않음 | [rollback 방지 절차](../operations-runbook.md#6-인증과-보관함의-rollback-방지), 별도 신뢰 receipt·현재 키 버전 대조·세션 폐기·필요한 HVK 회전, 두 사용자의 복호화 확인 · #41/#48 및 #45/#49, G6 |
| A-07 | 공개 fixture·debug 인수 경로가 정식 앱에 들어가지 않음 | 정식 APK의 manifest/모든 DEX/assets·의존성·서명 검사, 일반 CVC gate 거절 확인 · #39/#48 및 #47, G4/G6 |

기기별 지원/미지원 결과를 기록하고 실패 기능을 조용히 약화하지 않는다. 미지원 환경은
`BLOCKED_ENV` 또는 기능 불가로 남긴다. 에뮬레이터의 skip이나 빌드 성공을 실기기 성공으로 올리지 않는다.

## G1~G6와 Issue 완료 범위

| 게이트 | 기존 증거가 뒷받침하는 범위 | 남은 완료 조건 |
|---|---|---|
| G1 권한·세션·CSRF | [브라우저 인증](browser-authentication.md), [서버 보관함](vault-server.md), [통합 검증](final-integration.md)의 합성 API/DB·실제 HTTPS 결과 | 실제 배포/기기 origin·세션/철회/패스키 실패 인수. #18 설계 검토만으로 전체 완료 아님 |
| G2 암호·키 수명 | [네이티브 공통 벡터](native-vault-crypto.md), [웹 암호/흐름](vault-web.md), 서버 회전 제약 | 실제 Android provider와 웹 상호 운용, 두 기기 공유·복구·회전 장애. #37/#41 유지 |
| G3 실제 기기 | [디버그 합성 인수 절차](native-security-proof.md), [네이티브 수명 회귀](native-vault-lifecycle.md) | 두 Galaxy의 실제 인증·취소·등록 변경·잠금·강제종료·재설치. #17/#38/#41/#48 유지 |
| G4 무유출 | strict schema/serializer, 로컬 gate/백업 제외, [내보내기 검증](exports-server.md), [APK 검사/클라우드 기록](android-cloud-results.md) | 실제 기기의 프록시·로그·backup/이전·bridge·화면 canary 검사 및 사용자 CVC 선택. #39/#48 유지 |
| G5 웹·첨부·bridge | 웹 수명/저장소 회귀, [첨부 권한](documents-server.md), native 입력/출력 allowlist | TM-01의 배포 CSP 평가, 의존 코드/주입 경계, 실제 WebView·첨부 처리 환경 인수. #40/#48 유지 |
| G6 복원·배포·분실 | [실제 격리 복원 기록](operating-backup-restore.md)의 당시 서버 무결성, 정식 APK 관련 기존 운영 기록 | 독립 백업/키 보관·rollback 방지 후 실제 운영 전환·양 계정 보관함 복구·두 기기 데이터 보존 업데이트/분실 대응. #41/#48 및 #45/#47/#49 유지 |

[클라우드 기록](android-cloud-results.md)의 software AVD 부팅 제한과 실제 계측 미실행은
계측 성공이 아니다. 새 KVM workflow의 존재도 실제 성공 증거로 사용하지 않았다.
기존 운영 복원 기록은 서버 필드/문서의 격리 무결성 확인이며 두 구성원의 HVK 복구 성공 기록이 아니다.

| Issue | 이 문서로 판단하는 것 | 이 문서가 대신하지 않는 것 |
|---|---|---|
| #18 / SB-009 | 복구 분리, CVC 외부 경로 부재 설계, 키 흐름·인증 우회 검토, 위험/가정/게이트의 명시 | 발견되지 않은 결함의 부재 보증, 실기기 결과, 외부 전문 감사 |
| #17 / SB-008 | 합성 PoC 설계가 production 보관함과 구분됨 | 실제 CryptoObject·FLAG_SECURE·bridge/로그 확인 |
| #37 / SB-028 | 공통 포맷/KDF/AAD/nonce 경계와 fixture 확인 | 실제 Android↔웹 암호 상호 운용 인수 |
| #38 / SB-029 | 앱 잠금과 비밀 해제 분리, status-only bridge, 표시 수명 정책 | 실기기 화면/이탈/회전·인증 실패 인수 |
| #39 / SB-030 | 로컬 CVC 키/저장·백업 제외·release gate 확인 | 프록시/백업/기기 이전 실증과 활성화 선택 |
| #40 / SB-031 | 웹 메모리/DOM 수명과 CVC 비지원, XSS 신뢰 경계 확인 | 배포 G5와 최종 보안 인수 전체 완료 |
| #41 / SB-032 | 공유/새 기기/복구/회전 설계와 원자성 근거 확인 | 두 실제 기기의 복구·분실·회전 실패 시나리오 |
| #48 / SB-039 | 최종 게이트가 요구할 검증과 잔여 위험을 제공 | G1~G6의 실행·결함 해소·출시 승인 |

이 기준으로 #18의 설계 리뷰 완료를 판단하되 관련 구현/인수 Issue는 각각의 실제 완료 조건으로 관리한다.
기존 문서에서 #18을 실기기 게이트와 함께 묶어 언급한 문장은 출시 보안 경고로 해석하며,
이 문서가 실기기 게이트를 제거하거나 그 완료를 선언하는 것은 아니다.

## 공식 근거와 검토 방법

2026-10-18 공식 자료를 다시 확인했다. 외부 문서는 플랫폼 계약의 근거이며 실제 SallimBook
기기에서 그 계약이 구현됐다는 실행 증거는 아니다.

- [Android KeyGenParameterSpec.Builder](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder):
  인증 시간 0의 매 사용 인증, strong 인증 종류 및 Android 12~14 unlocked-device 정책 주의사항.
  현재 코드는 API 35 이상에만 `setUnlockedDeviceRequired(true)`를 추가하고 모든 지원 버전에서 strong auth-per-use를 요구한다.
- [Android 생체 인증 가이드](https://developer.android.com/identity/sign-in/biometric-auth):
  CryptoObject와 실제 암호 연산의 결합. 가이드의 예시 로그 코드를 비밀 로그 허용으로 해석하지 않는다.
- [Android Auto Backup](https://developer.android.com/identity/data/autobackup):
  no-backup 디렉터리 제외와 일부 제조사에서 allowBackup만으로 D2D를 막지 못하는 차이.
  최신 전송 모드도 출시 기기의 OS별 확인 대상이며 no-backup 보호만 보고 제조사 검증을 생략하지 않는다.
- [W3C Web Cryptography 보안 고려](https://www.w3.org/TR/webcrypto/#security-considerations):
  스크립트 주입과 브라우저/OS 신뢰, 키 메모리 소거의 보장 한계.
- [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html):
  PBKDF2-HMAC-SHA256 600,000회 참고값. 이 선택이 FIPS 인증이나 약한 암호의 안전성을 보증하지 않는다.

검토는 README/제품 요구사항/보안 정책/키 수명주기/ADR, #18 및 연관 Issue 본문,
서버의 schema→권한/잠금→복구/회전→DB 제약·시험, 웹/native의 KDF→unwrap→key check→표시/폐기,
bridge·백업·export의 입력/출력 경로를 순서대로 대조했다. `rg`로 비밀 필드·저장소·HTML 삽입·
CSP·복구 연결을 탐색했으며 검색 미발견을 런타임 부재 증명으로 쓰지 않았다.
문서 검증과 변경 파일 확인 외에 새로운 기능 시험을 실행하지 않았다.
