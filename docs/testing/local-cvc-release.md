# Android 로컬 CVC 활성화와 별도 보안 검토

> 2026-10-31: 아래는 로컬 CVC 활성화 당시 기록이다. 선택적 공유 CVC는 [v2 결정](../adr/web-cvc-vault-v2.md)과 [최초 입력 검증](financial-first-import.md)을 따른다.

2026-10-25 · R-10/R-11/R-12 · SB-030 · [#39](https://github.com/jihoon22-lee/SallimBook/issues/39).
[사용자 결정과 범위](../adr/local-cvc-release-option.md)를 따른다.

## 동작

Android 카드 상세와 보관함 목록에서 CVC/CVV 입력·수정, 열람, 삭제를 선택할 수 있다.
직접 입력하는 네이티브 화면에서 기기 한정 저장·재입력·등록된 생체인증 수단의 접근을 설명하고
처음에는 미선택인 동의란을 제공한다. 동의 없는 저장과 ASCII 숫자 3~4자리 이외 입력을 거부한다.
입력 배열은 성공·실패 모두 지우고 저장·열람에는 매번 실제 키와 연결한 강한 생체인증을 요구한다.
미입력 상태는 네이티브 화면에서만 안내하며 React 상태나 서버에 CVC 존재 여부를 보내지 않는다.
열람에서 직접 입력·삭제 화면으로 이동할 수 있다. 키 무효화 후 삭제·재입력을 안내한다.

## 별도 보안 검토

구현 후 CVC 경로를 입력부터 저장·표시·외부 출력까지 별도로 추적했다. 구현자의 소스 검토이며
독립된 외부 감사 또는 실제 기기 인수로 표현하지 않는다. 실제 개인정보·운영 키·CVC는 사용하지 않았다.

| 경계 | 검토한 구현과 판정 |
|---|---|
| 활성화·동의 | `NativeVaultCvcPolicy`는 일반 namespace만 허용한다. 동의를 입력 시점에 검증하며 CharArray를 finally에서 지운다. JS·Intent·서버 플래그가 동의나 키 인증을 대신하지 않는다 |
| 입력·표시 | `NativeVaultActivity`는 비공개 Activity, FLAG_SECURE, 비저장 입력/출력, 자동완성·내용수집·학습·문맥 복사 제한을 유지한다. 평문은 네이티브 화면에서 최대 30초 표시하고 이탈/잠금에 지운다 |
| 실제 키 사용 | `NativeVaultStore.prepareEncryption`은 AES-256-GCM, 매 사용 강한 생체인증과 등록 변경 무효화를 요구한다. `beginPrompt`는 실제 Cipher의 CryptoObject를 전달하고 동일 객체·foreground·세션 generation을 확인한다. `finish`는 한 번 소비 후 doFinal하며 boolean 인증 우회가 없다 |
| identity·변경 | 서버에서 확인한 scope와 카드 envelope ID/revision을 AAD와 키 별칭에 묶는다. 조회 전후 서버 상태를 대조하며 권한 철회·카드 비밀 변경·키 회전 뒤 기존 로컬 자료를 reconcile한다 |
| 저장·삭제 | 별도 Keystore 키와 noBackupFilesDir의 AtomicFile을 사용한다. 새 파일 쓰기 실패는 이전 암호문을 보존한다. 기존 키 오류나 orphan 파일을 새 키로 조용히 대체하지 않는다. 명시적 삭제는 해당 카드 범위의 키와 암호문을 제거한다 |
| 합성 경로 | 배포 namespace 허용은 debug 합성 namespace를 열지 않는다. 합성 검사는 Activity 소유자·binding 범위를 유지하고 운영 namespace에 키를 생성하거나 지우지 않는다. release acceptance gate는 항상 거부하고 실패 주입은 없다 |
| JS·웹 | `VaultActionLauncher`는 Android에 동작/카드 ID만 보내며 PC 웹의 CVC 동작을 거부한다. native adapter의 기존 exact-field 검사와 status-only 응답 검증을 유지한다. 웹 CVC 입력·저장·HTTP 우회가 없다 |
| 서버·백업 | 카드 일반 schema의 extra-field 거부, 보관함의 고정 envelope 계약, export 허용 목록을 유지한다. 서버·migration·API 계약 변경이 없다. manifest의 allowBackup/fullBackupContent false와 cloud/device-transfer 제외 규칙을 유지한다. 운영 백업은 서버 DB/문서만 수집한다 |

소스 검토에서 활성화와 함께 새로 생긴 외부 평문 경로나 인증 우회는 발견하지 않았다.
JVM에서 Android Keystore의 실물 보안 수준·제조사 이전·캡처 차단을 입증할 수는 없다.
앱 내부 문자열·UI/OS의 모든 메모리 사본 소거, 루팅·감염 기기·외부 촬영 차단도 보장하지 않는다.

## 검증

합성 데이터만 사용하며 화면/trace/video에 비밀을 기록하지 않는다.

| 명령·범위 | 결과 |
|---|---|
| `pnpm test:web vault-overview vault-native-bridge vault-private vault-workflow vault-crypto` | 116 통과. Android 버튼은 동작/카드 ID만 전달하고 HTTP·브라우저 저장을 하지 않는다. 웹 CVC 미지원과 기존 보관함 수명/암호화도 검증 |
| `uv run --project services/api pytest services/api/tests/test_cards.py services/api/tests/test_vault.py services/api/tests/test_vault_schemas.py -m 'not database' -q` | 101 통과, DB 미설정 11 skip / DB marker 25 제외. DB 통과로 세지 않음 |
| `pnpm test:database services/api/tests/test_cards.py services/api/tests/test_vault.py services/api/tests/test_vault_schemas.py services/api/tests/test_vault_database.py -q` | 144 통과. 실제 DB 가계 격리·CVC extra-field 거부·보관함 권한/회전/삭제, 모델/migration 일치·왕복 확인 |
| `uv run --project services/api python scripts/test_web_auth.py --vault` | 실제 HTTPS/API/PostgreSQL 보관함 회귀 통과. CVC 평문 네이티브 입력이나 실기기 생체 성공 시험은 아님 |
| `JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 pnpm android:build` | debug APK 빌드·JVM 477 통과(동의 거부, 입력 소거, ASCII/길이, namespace 정책 포함) |
| Android `./gradlew --no-daemon :app:assembleDebugAndroidTest` | 계측 APK 컴파일 통과. 실행 결과와 구분 |
| `pnpm typecheck`, `pnpm lint`, `pnpm format:check`, `git diff --check` | 통과. 웹 빌드는 Android/HTTPS 준비에서 통과 |
| `python3 scripts/validate_docs.py`, `python3 -m unittest discover -s tests -v` | 문서·링크 검사와 도구 258 통과 |

초기 빌드에서 CVC action union의 TypeScript narrowing 오류가 발견되어 각 action을 분리한 뒤
타입 검사와 Android 빌드를 다시 실행해 통과했다. API 시험의 잘못된 파일 이름은 실제
`test_vault_schemas.py`로 수정해 다시 실행했다. 기존 Vite 큰 청크·Gradle deprecation·Starlette 경고는 남는다.
최종 `pnpm test:web vault-overview`는 PC CVC 버튼 부재 확인을 추가해 40개 통과했다.
두 Galaxy의 생체 성공·등록 변경·재설치·제조사 전송·실제 정식 업데이트는 사용자 후속 시험이다.

## 사용 안내

서명 APK 업데이트 후 카드 보관함을 설정하고 해당 카드의 전체 번호·유효기간을 먼저 등록한다.
카드 상세 또는 보관함에서 **이 기기의 CVC/CVV 입력·수정**을 선택하고 네이티브 안내·동의 후 직접 입력한다.
매 저장·열람에 강한 생체인증이 필요하다. 보관을 원하지 않으면 입력하지 않거나 **삭제 검토**에서 확인한다.
기기 교체·재설치 뒤 복원되지 않는다. 키가 무효화되면 이 기기의 보안코드를 삭제하고 직접 재입력한다.
새 서명 APK와 실제 운영 배포의 버전·hash·검증은 별도 운영 기록에 연결한다.
