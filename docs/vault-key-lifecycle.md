# 카드 보관함 키 수명주기

상태: 서버 opaque 보관함과 DB 수명주기를 구현했다. Android/PC 보호 화면과 실기기 인수는 별도 진행한다.
확정 포맷은 [보관함 v1 결정](adr/vault-format-v1.md), 서버 증거는 [검증 기록](testing/vault-server.md)을 따른다.
API의 인증 성공과 암호키 접근은 별도라는 전제를 유지한다.

## 1. 키 구분

| 이름 | 소유·저장 | 역할 |
|---|---|---|
| HVK | 가계 보관함 키, 클라이언트에서 랜덤 생성 | PAN/유효기간 암호문 암·복호화 |
| Member KEK | 구성원의 별도 보관함 암호에서 KDF로 도출 | HVK를 구성원별로 wrapping |
| Device KEK | Android Keystore에서 생성, 원본 추출 금지 정책 | 해당 기기에서 HVK를 보호, 사용 시 시스템 인증 |
| Recovery KEK | 32바이트 랜덤 복구코드 기반 | HVK 복구용 wrapping; 코드 원문 서버 미저장 |
| Local CVC key | Android Keystore 로컬 키 | CVC 로컬 암호문 보호, 동기화 없음 |
| Server storage key | 서버 외부 비밀 설정 | 계좌번호·의료 문서 저장 암호화, HVK와 무관 |

보관함 암호와 로그인 암호는 분리한다. 짧은 4~6자리 앱 PIN을 보관함 KDF 비밀로 사용하지 않는다.
기기의 잠금 PIN은 Android의 하드웨어/OS 인증 정책을 통한 키 접근용이지 직접 AES 파생 재료가 아니다.

## 2. 암호 포맷

HVK는 CSPRNG로 생성한 256비트 랜덤키. 카드 payload는 AES-256-GCM, 96비트 랜덤 nonce, 128비트 tag.
AAD에 household_id, card_id, key_version, payload_schema_version을 고정된 직렬화 규칙으로 포함한다.
같은 키에서 nonce 재사용을 막고 서버는 저장된 nonce 충돌을 거부한다. 충돌 시 새 nonce로 다시 암호화한다.
인증 tag 오류는 복호화 실패이며 부분 평문을 보여주지 않는다.

구성원 wrapping KDF는 플랫폼 표준 호환성을 위한 PBKDF2-HMAC-SHA256, 600,000~2,000,000회,
128비트 이상 랜덤 salt, 출력 256비트다. 이 값은 OWASP의 PBKDF2 참고값을 바탕으로 한 설계 하한이며
Argon2id보다 우월하다는 의미나 FIPS 적합성 주장이 아니다([S07](references.md)).
구현 전 Android/웹 성능과 암호 호환 벡터를 시험하고, KDF 종류·파라미터·salt를 wrapping마다 저장한다.
서버에서 받은 KDF 종류·반복 횟수·메모리/암호문 크기는 클라이언트의 허용 목록과 상한으로 검증한다.
알 수 없는 포맷이나 자원 고갈을 유발하는 파라미터는 거부한다.
비밀번호 Unicode 인코딩은 UTF-8로 고정하고 임의 trim/대소문자 변경을 하지 않는다.
weak password의 offline 공격은 서버 rate limit으로 막을 수 없으므로 충분히 긴 보관함 암호를 요구한다.

```text
card envelope = {schema_version, key_version, nonce, ciphertext_with_tag}
member wrap   = {member_id, key_version, kdf, params, salt, nonce, wrapped_hvk}
```

CVC와 계좌번호는 이 카드 envelope 포맷에 끼워 넣지 않는다.
키는 문자열로 출력·로깅하지 않는다. JS/Kotlin의 메모리 소거에는 제약이 있음을 인정하고 참조 수명을 최소화한다.

## 3. 첫 설정

1. 사용자가 계정 로그인과 최근 재인증을 완료한다.
2. 신뢰하는 클라이언트가 HVK와 복구코드를 생성한다.
3. 사용자가 보관함 전용 암호를 입력한다. client가 Member KEK를 도출해 HVK를 wrapping한다.
4. 복구코드를 한 번 표시하고 안전한 오프라인 보관을 확인한다. clipboard에 자동 복사하지 않는다.
5. 서버에는 member/recovery wrapping과 메타데이터만 저장한다.
6. Android는 추가로 Device KEK를 만들고 로컬 HVK wrapping을 저장한다.

테스트/샘플에는 실제 키를 사용하지 않고 공개된 테스트 벡터 또는 실행 시 만든 폐기용 키를 사용한다.

## 4. 두 번째 구성원

일반 가계 초대가 비밀 자동 공유를 의미하지 않는다.
기존 구성원의 잠금 해제 가능한 신뢰 기기에서 새 구성원의 계정/공유 의도를 확인한다.
새 구성원이 그 신뢰 기기에서 자신의 보관함 암호를 입력하고 자신에게 연결된 Member wrapping을 생성한다.
서버는 가계 membership과 최근 재인증을 검증하고 새 wrapping을 저장한다.
새 구성원은 본인 기기에서 그 wrapping을 받아 본인 암호로 HVK를 해제한 후 Device KEK로 재보호한다.

v1은 이 명시적 초기 공유 절차로 시작한다. QR/푸시 승인형 키 전송 프로토콜은 별도 보안 설계 없이 추가하지 않는다.
기존 구성원이 새 구성원의 암호를 서버에서 알 수 있게 만들지 않는다. 신뢰 기기 공동 사용의 보안 전제를 안내한다.

## 5. 평상시 열람

Android: 계정 세션 유효 확인 → 허용된 card ID의 암호문 가져오기 → 네이티브 화면의 대상 카드 확인 →
BiometricPrompt/CryptoObject로 Device KEK 사용 허가 → HVK 해제 → 카드 복호화 → 최대 30초 표시 → 잠금.
네이티브 화면은 허용된 origin/API만 사용하고, 임의 JS 문자열을 복호화하는 범용 함수를 노출하지 않는다.
서버는 가계 권한을 확인할 뿐 '생체인증 결과 bool'을 인증 증거로 받아들이지 않는다.

PC: 계정 세션 확인 → vault 전용 화면에서 구성원 암호 입력 → Member wrapping 해제 → 해당 카드만 복호화 → 제한 시간 표시.
HVK/평문은 localStorage/IndexedDB/Service Worker/일반 Query cache에 저장하지 않는다.
화면 잠금 후 매번 새 암호 입력을 요구하는 것을 기본값으로 한다.

## 6. 암호·기기 변경

보관함 암호 변경: 기존 암호나 이미 해제된 신뢰 기기로 HVK 확인 → 새 KDF salt/params → 새 Member wrapping 저장.
카드 암호문 전체를 바꿀 필요는 없다. 로그인 암호 변경은 이 wrapping을 자동 변경하지 않는다.

새 Android 기기: 서버 로그인/기기등록 → 보관함 암호로 본인 wrapping 해제 → 새 Device KEK 생성 → 로컬 wrapping.
기존 기기의 non-exportable key를 복사하지 않는다. CVC는 새 기기에서 수동 재입력한다.

지문 등록 변경/키 무효화: 자동 우회하지 않고 로컬 wrapping을 무효 상태로 표시 → 보관함 암호/복구 절차로 재등록.
기기 잠금 해제 방식 제거, 앱 데이터 초기화, 공장 초기화도 동일하게 처리한다([S03, S04](references.md)).

## 7. 복구

계정 접근권한 복구 후, 오프라인 복구코드로 Recovery wrapping을 해제한다.
새 구성원 wrapping과 새 기기 wrapping을 만들고 기존 복구코드는 회전시킨다.
복구코드도 보관함 암호도 신뢰 기기도 없으면 기존 암호문을 복원할 수 없다.
그 사실을 숨기지 않고 카드번호를 다시 등록해야 함을 안내한다.
서버 관리자의 '비밀번호 재설정' 버튼으로 HVK를 평문 반환하는 우회는 금지한다.

## 8. 가계 구성원/기기 철회·키 회전

기기 철회는 서버의 해당 세션·등록 상태를 폐기한다. 다음 연결에서 로컬 wrapping/CVC 삭제를 지시한다.
오프라인 사본이나 이미 본 번호를 되돌릴 수는 없다.
구성원 접근 철회나 키 유출 시 새 HVK로 모든 카드 payload를 재암호화하고 새 wrapping을 배포한다.
초기 v1은 가계의 카드 수가 적다는 전제로 이 작업을 단계화하되, 새 버전 전체 준비가 끝난 후 원자적으로 current를 전환한다.
중간 실패로 카드 일부만 접근 불능이 되지 않게 이전 버전 복구 지점을 유지한다.
기존 백업에는 과거 암호문/키 wrapping이 남을 수 있으므로 보존 기간과 폐기 일정을 고려한다.

## 9. PIN fallback와 최소 Android

minSdk는 사용자 승인으로 API 30(Android 11)에 고정한다. Galaxy S25·S24 Ultra에서 실제 키·인증 동작을 검증한다.
BiometricPrompt의 허용 인증 조합과 auth-per-use/time-based key 구성이 정확히 맞는지 검증한다.
PIN fallback을 추가하려고 인증 후에도 언제든 사용 가능한 무보호 키를 만들지 않는다.
기기에서 요구 정책을 충족하지 못하면 보관함 암호 재입력 경로 또는 기능 불가 안내를 사용하고 조용히 약화하지 않는다.

## 10. 검증 완료 조건

같은 테스트 payload의 Android↔웹 암호 호환, 잘못된 암호/AAD/tag 실패, nonce 중복 거부,
두 구성원 독립 암호, 새 기기 복구, 지문 변경 무효화, 키 회전 중 실패 복구,
클립보드/백업/네트워크/bridge 무유출을 모두 확인한다.
암호 라이브러리·구현 리뷰 완료 전 실제 카드정보를 입력하지 않는다.


서버는 교체된 구성원/복구 wrapping 이력도 보존한다. 따라서 예전 암호·복구코드와 과거 wrapping
사본을 가진 경우 같은 HVK를 열 수 있다. 암호 또는 코드 변경만으로 이미 유출된 HVK를 무효화하지 않는다.
유출 대응은 새 HVK로 전체 회전해야 하며 이전 백업/오프라인 사본까지 회수할 수는 없다.
카드 비밀의 명시 삭제는 현재·retired·aborted 모든 온라인 카드 암호문을 NULL로 폐기한다.

카드 비밀을 새 값으로 교체하면 이전 envelope는 current에서 빠지지만 암호문 이력은 유지한다.
이력까지 온라인에서 제거하려면 명시적 비밀 삭제를 사용한다. 일반 API는 현재 envelope만 조회한다.
