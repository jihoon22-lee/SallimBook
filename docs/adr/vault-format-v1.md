# ADR · 보관함 v1 암호 포맷과 삭제 경계

> 2026-10-31: CVC 로컬 전용 제한은 [공유 보관함 v2 결정](web-cvc-vault-v2.md)으로 대체한다. 이 문서는 당시 결정과 v1 호환 포맷을 기록한다.
상태: SB-028/SB-032 구현 결정. 실기기 암호·인증·복구 인수는 별도 완료 조건이다.
관련: R-08/R-09/R-20, Issue #37~#41, [키 수명주기](../vault-key-lifecycle.md).

## 암호 포맷

표준 AES-256-GCM, PBKDF2-HMAC-SHA256, HKDF-SHA256을 사용한다. 자체 암호 알고리즘을 만들지 않는다.
HVK는 클라이언트 CSPRNG 32바이트, GCM nonce는 매 암호화마다 새 12바이트, tag는 16바이트다.
암호문과 tag를 연결해 canonical unpadded base64url로 전송한다. padding·다른 인코딩·미지의 필드는 거부한다.
키 버전·generation·revision은 1~2^53-1 정확 정수이며 AAD에서는 unsigned big-endian 64비트로 표현한다.

| payload 부분 | 고정 표현 |
|---|---|
| magic | ASCII `SBV1`, 4바이트 |
| PAN 길이 | unsigned 1바이트, 13~19 |
| PAN 공간 | ASCII 숫자 + 오른쪽 NUL padding, 합계 19바이트 |
| 만료 연도 | unsigned big-endian 16비트, 2000~2199 |
| 만료 월 | unsigned 1바이트, 1~12 |

카드 평문은 정확히 27바이트, 암호문+tag는 43바이트다. 클라이언트는 숫자·Luhn·padding·날짜를
검사한다. CVC·계좌번호·임의 필드를 이 payload에 추가하지 않는다. 서버는 암호문 길이와 권한을
검증하지만 복호화하거나 마지막 네 자리와 암호문의 수학적 일치를 확인할 수는 없다.

Member KEK는 별도 보관함 암호의 **원래 UTF-8 bytes**에서 PBKDF2-HMAC-SHA256으로 도출한다.
600,000~2,000,000회, 새 salt 16바이트, 출력 32바이트다. trim·Unicode 정규화·대소문자 변환을 하지 않는다.
잘못된 Unicode 입력은 대체문자로 바꾸지 않고 거부한다. 짧은 앱 PIN이나 로그인 비밀번호를 사용하지 않는다.
반복 횟수 상한은 서버 응답이 클라이언트 자원을 무제한 사용하지 못하게 하는 프로젝트 제한이다.

Recovery KEK는 CSPRNG 복구코드 32바이트에 HKDF-SHA256, 새 salt 16바이트,
info UTF-8 `SallimBook/vault/recovery-kek/v1`, 출력 32바이트를 적용한다.
복구코드의 사용자 표시는 canonical unpadded base64url이며 서버에 원문을 보내지 않는다.
두 wrapping은 HVK 32바이트를 GCM 암호화하므로 ciphertext+tag 길이는 48바이트다.

AAD는 JSON이 아닌 다음 순서의 bytes 연결이다. UUID는 하이픈 없는 문자열이 아니라 raw 16바이트다.
각 prefix 뒤에는 NUL 1바이트가 있다. `u64`와 `u32`는 unsigned big-endian이다.

| 용도 | AAD |
|---|---|
| 카드 | `SallimBook/vault/card/v1` + NUL + household UUID + card UUID + keyVersion u64 + schemaVersion(1) u32 |
| 구성원 | `SallimBook/vault/member/v1` + NUL + household UUID + member UUID + keyVersion u64 + generation u64 + iterations u32 + salt16 |
| 복구 | `SallimBook/vault/recovery/v1` + NUL + household UUID + keyVersion u64 + generation u64 + salt16 |
| 키 확인 | `SallimBook/vault/key-check/v1` + NUL + household UUID + keyVersion u64 |

키 확인 평문은 ASCII `SallimBook vault key check v1` 29바이트, 암호문+tag는 45바이트다.
카드가 없는 가계도 공유받은 HVK가 현재 키인지 클라이언트에서 확인할 수 있다.
서버는 이 값도 복호화하지 않으며, 사용자가 잘못된 키로 wrapping을 만든 경우까지 알아낼 수 없다.

서버는 가계·키 버전·nonce의 append-only 유일 원장을 유지한다. 카드/구성원/복구/키 확인에서
같은 nonce를 다시 참조할 수 없다. 구성원/복구 salt도 각각의 테이블에서 가계별 재사용을 거부한다.
취소된 회전·바꾼 wrapping·폐기한 카드의 nonce 기록도 삭제하지 않는다.

## 공유·회전·폐기

일반 가계 초대와 보관함 공유를 분리한다. 기존 구성원이 신뢰 기기에서 새 구성원의 암호로 wrapping을
준비한 뒤 상대가 본인 최근 인증과 암호로 열고 키 확인 값을 검증해 수락한다. 서버는 대상 ID·가계·
현재 권한·최근 계정 인증을 검증하며 클라이언트의 생체인증 성공 플래그를 증거로 쓰지 않는다.

키 회전은 서버가 새 버전을 예약하고 현재 모든 카드 비밀과 유지할 구성원을 고정한다.
모든 새 카드 암호문·구성원 wrapping·복구 wrapping·키 확인이 준비돼야 current를 원자 전환한다.
준비 중에는 기존 키로 읽을 수 있고 비밀 변경·가입·복구/rewrap은 동결한다. 중단한 키 버전은 재사용하지 않는다.
과거 버전은 일반 조회 API에서 숨긴다. 구성원 철회 직후에는 접근을 막고 키 회전 필요 상태를 표시한다.

**카드 비밀 삭제는 종료/보관과 다르다.** 해당 카드의 모든 현재·과거·중단 버전 암호문을 DB에서
NULL로 폐기하고 다시 채울 수 없게 한다. 참조 ID·nonce·revision·폐기 시각·감사와 일반 카드 metadata는
유지한다. 이렇게 하면 회전 근거와 감사는 보존하면서 서버의 과거 암호문이 계속 남는 문제를 피한다.
이미 만들어진 백업과 오프라인 기기의 사본을 즉시 회수할 수는 없다. Android CVC는 서버에 없으며
별도 로컬 삭제·다음 연결 시 폐기 처리와 기기 초기화 안내가 필요하다.

복구코드만 바꾸고 HVK를 그대로 두면 예전 코드와 wrapping의 오프라인 사본으로 같은 HVK를 열 수 있다.
코드 유출 대응은 새 HVK 회전까지 수행해야 한다. 로그인 비밀번호 재설정은 HVK 복구를 대신하지 않는다.

## 호환 벡터와 근거

[공개 합성 벡터](../../packages/test-fixtures/vault-v1.json)는 고정된 시험 키·nonce와 공개 결제 sandbox
번호만 사용한다. 운영 비밀이 아니며 앱에 이 값들을 기본값으로 넣지 않는다.
`uv run --project services/api python scripts/generate_vault_vectors.py`로 재현한다.
한국어·결합 문자·emoji·앞뒤 공백을 포함한 암호와 두 독립 구성원 wrapping을 Android/웹 구현이 함께 검사한다.
벡터 통과는 실기기의 Keystore·생체인증·백업 경계 검증을 대신하지 않는다.

근거: [W3C Web Cryptography](https://www.w3.org/TR/2017/REC-WebCryptoAPI-20170126/),
[cryptography KDF 문서](https://cryptography.io/en/50.0.0/hazmat/primitives/key-derivation-functions/),
[공개 sandbox 테스트 번호](https://docs.stripe.com/testing).
