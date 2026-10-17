# Android 감사 메타데이터 조회 — SB-034/040

관련 R-01/R-02/R-19/R-20, Issue #43/#49, 화면 UI-26.
서버 조회 계약은 [감사 API](../api-contract.md#sb-037-사용자-내보내기감사-조회-구현-계약-r20)를 따른다.

## 입력과 권한 경계

`nativeAudit.list({query})`는 생성 `listAuditEvents` query 및 `AuditListResponse` 타입을 사용한다.
전용 `listAuditEvents` plugin은 limit/cursor/entity_type/entity_id/actor_member_id/action/since/until만
받는다. 임의 URL·method·headers·body·가계 ID·인증 성공 bool을 받지 않고 일반 `request`의
허용 경로도 확장하지 않는다. 이 조회는 서버의 최근 계정 재인증을 추가로 요구하지 않는다.

Android의 계정 executor와 현재 세션 bearer로 고정 `GET /api/v1/audit-events`를 호출한다.
전후 `/me`의 household/member/user ID가 같아야 결과를 전달하며 앱 잠금·취소·세션 세대를 확인한다.
가계 범위와 활성 계정·기기 권한의 최종 검사는 서버에 있다. 응답에는 household ID가 없으므로
네이티브가 각 감사 행의 가계 소유권을 독립적으로 증명한다고 주장하지 않는다.
과거 비활성 구성원의 감사 기록도 유지한다. 현재 활성 구성원만 반환하는 `/household/members`의
목록에 없다는 이유로 과거 변경자 ID를 거절하지 않는다.

## 안전한 응답과 전송

네이티브는 감사 ID·변경자 member ID·entity type/ID·action·request ID·전후 version·UTC 시각·
changed_fields의 정확한 10개 필드만 새 객체로 투영한다. 원본 `safe_diff`, 전후 값, 임의 메모나
추가 필드는 거절한다. `changed_fields`는 서버의 알려진 **필드 이름** 목록이다. `password_hash`,
`wrapped_hvk` 같은 이름이 들어갈 수 있지만 그 값이나 암호문은 반환하지 않는다.

`NativeAuditWire`는 현재 서버의 35개 entity type·19개 action·307개 필드 이름을 대조한 명시적
목록을 사용한다. 서버의 감사 메타데이터 목록이 바뀌면 이 보안 투영도 같은 변경에서 검토한다.
생성 API DTO를 대체하는 별도 업무 모델을 만들지 않는다.
UUID·상관 ID 형식, 안전한 정수 범위의 양수 version 또는 null, UTC timestamp, 정렬된 중복 없는
변경 필드 64개 이하, 요청 limit 1..200을 검사한다. since/until은 timezone 필수이며 `[since, until)`이다.
페이지는 시각·UUID 내림차순과 ID 중복을 검사하고 선택 필터·요청 cursor보다 뒤의 행만 허용한다.
cursor는 최대 1,024자의 canonical base64url이며 UTC 시각·UUID·필터 지문 3개만 허용한다.
다음 cursor는 마지막 행과 같아야 한다. 서버의 가계/필터 바인딩 검사는 이 형식 검사를 대신하지 않는다.

`NativeAuditHttp`는 고정 HTTPS, 플랫폼 TLS, 15초 요청 한도, 기존 no-follow-up native client 정책을
사용한다. 쿠키·redirect·cache·자동 재전송·HTTP 로그가 없으며 bearer는 native 안에만 둔다.
1MiB 이하의 strict UTF-8 JSON으로 중복 키·실수·과도한 중첩을 거절하고 임시 byte buffer를 지운다.
SDK API 목록을 확인하여 URL 인코딩은 minSDK 30에서 사용할 수 있는 charset-name overload를 쓴다.
`INVALID_CURSOR` 400, `INVALID_AUDIT_FILTER` 422, `AUDIT_METADATA_INVALID` 503은 고정 로컬 오류로
보존하며 서버 원문 메시지·입력·알 수 없는 코드는 bridge/UI에 반사하지 않는다.
TS adapter에는 HTTP·저장소 fallback이나 자동 retry가 없다.

## 검증

```bash
pnpm install --frozen-lockfile
pnpm typecheck
pnpm android:sync
JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ANDROID_HOME=/home/jihoon/Android/Sdk apps/client/android/gradlew -p apps/client/android --no-daemon --max-workers=2 :app:testDebugUnitTest :app:assembleDebug :app:compileReleaseKotlin
TMPDIR=/home/jihoon/.cache/sallimbook pnpm --filter @sallimbook/client exec playwright test audit-native-bridge.spec.ts --config playwright.audit-native.local.config.ts --workers=2
pnpm test:docs
```

2026-10-18 WSL: typecheck·Android sync·전체 JVM **322개**(실패·오류·건너뜀 0), debug APK와
release Kotlin 검증을 통과했다. 신규 wire 10개는 8개 필터·cursor·정렬·범위·현재 identity·과거 actor,
명시적 필드 투영·원문 거부·오류 코드를 검사한다. 실제 OkHttp interceptor 4개는 고정 method/URL,
private bearer·무본문·오류 상관 ID·strict JSON/MIME/크기·취소/잠금/늦은 결과를 검사한다.
서버의 35/19/307개 이름 목록도 실제 소스에서 읽어 네이티브 목록과 집합이 같은지 확인했다.

브라우저 **38개**는 PC/Android 크기의 모의 plugin으로 필터 전달·39개 잘못된 입력·안전한 오류,
응답 한도·추가 필드 거부와 HTTP/저장소/재시도 부재를 검사한다. 기존 설정의 baseURL/webServer만
18754로 바꾼 임시 config를 썼고 종료 후 포트 반환·config 삭제를 확인했다.
서버 `test_exports_encoding.py` **44개**도 통과했다. DB 권한/가계 교차 검증은 서버의 별도 통합시험이며,
이 변경에서는 DB·마이그레이션·API 계약을 변경하거나 격리 DB를 새로 실행하지 않았다.

이 검사는 실제 Galaxy WebView/앱 잠금·백그라운드·세션 폐기나 네트워크 인증을 실행한 실기기
인수가 아니다. 실제 설정 화면의 감사 조회와 취소·잠금 실패 인수는 전체 실기기 검증에 남아 있다.
