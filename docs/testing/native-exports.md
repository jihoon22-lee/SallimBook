# Android 사용자 내보내기 경계 · SB-037

요구사항 R-02/R-20, [SB-037 작업](../../planning/ISSUES.md), [사용자 export API](../api-contract.md#sb-037-사용자-내보내기감사-조회-구현-계약-r20)를 따른다.
이 문서는 사용자 ZIP 사본 저장을 다룬다. 운영 백업·새 서버 복원·정식 서명 및 두 Galaxy 인수는 별도 검증이다.

## 브리지와 소유권

`nativeExports.export({ input: ExportRequest })`는 생성 API 스키마를 사용하고 플러그인의
`exportArchiveUI`를 호출한다. 반환은 `{ status: "exported" | "cancelled" }`뿐이다.
API URL·가계 ID·header·토큰·재인증 증명·파일명·URI·path·bytes/blob를 입력하거나 반환하지 않는다.
`formats`는 중복 없는 json/csv 1~2개, `document_ids`는 중복 없는 UUID 0~10개이며 생략 시
서버와 같은 기본값 json+csv/빈 목록을 사용한다. 선택 배열은 호출 전에 복사한다. 알 수 없는 필드,
잘못된 선택 및 status 외 응답 필드를 거부하며 웹 HTTP·브라우저 저장소·다운로드 URL로 우회하지 않는다.

네이티브 Activity는 명시적인 컴포넌트로만 열리고 `exported=false`, 정확한 mode/selection extras,
`FLAG_SECURE`, 저장 상태·autofill·content capture·클립보드 메뉴·IME 학습 차단을 적용한다.
재생성된 Activity는 작업을 재개하지 않는다. 선택 메타데이터만 Intent에 들어가며 로그인 암호와
파일 원문·목적지 URI는 네이티브에서만 처리한다. APK manifest에서도 비공개 Activity임을 확인했다.

## 사용자 확인과 최근 인증

네이티브 화면은 형식과 선택 문서 수, 평문 ZIP 사본 보관, 진료 기록/메모/선택 원본 포함 가능성,
원격 회수·만료 불가와 부분 파일 가능성을 안내하고 별도 체크박스로 확인받는다. 전용 카드 비밀·
CVC·인증 자료·전체 계좌/증권번호 필드 제외와, 메모/원본 문서 안의 텍스트가 자동 제거되지 않는 점을 구분한다.

현재 계정 로그인 암호로 기존 native 재인증 API를 호출한다. 재인증 성공 뒤에만 저장 위치 선택기를
열고, 같은 요청·세션 세대·foreground·앱 잠금·기기 잠금을 확인한다. 앱 잠금 성공 bool이나 웹 플래그를
최근 서버 인증으로 간주하지 않는다. 재인증 60초, 선택기 60초 및 복귀 후 초점 1초 제한을 적용한다.
선택기 동안 네트워크/파일 본문 I/O를 진행하지 않는다. 일반 화면 이탈·잠금·Back·취소·파괴는 폐기한다.

## ZIP 전송과 무결성

`NativeAuthSession.exportArchive`는 계정 executor 안에서만 bearer를 얻고 고정
`POST /api/v1/exports`를 실행한다. 최소 185초의 bearer 여유를 확보하며, 부족하면 기존 refresh
회전 절차를 먼저 수행한다. refresh 자체로 최근 인증을 연장하지 않는다. 일반 JSON/finance bridge에
export 경로를 열지 않으며 native 전용 응답 소유자가 bytes를 받는다.

전용 OkHttp client는 HTTPS origin 고정, cookie/cache/redirect/자동 인증/connection retry 없음,
follow-up 차단, one-shot POST body, `Accept-Encoding: identity`를 사용한다. timeout은 전체/read
180초와 request write 30초다. POST를 재시도하지 않으며 각 새 사용자 동작은 서버의 새 export다.

200 응답은 아래를 모두 확인한 뒤 메모리에 보관한다.

- 정확한 `application/zip`, `Cache-Control: no-store`, `Pragma: no-cache`, `nosniff`.
- 단일 `Content-Length`, 64MiB 이하, 실제 body 길이 일치. 누락·중복·과다·짧음·후행 바이트 거절.
- 단일 UUID `X-Export-ID`와 이에 일치하는 고정 `Content-Disposition` 파일명.
- 단일 소문자 SHA-256 header와 전체 실제 bytes의 SHA-256 일치, ZIP local-header signature 확인.
- 압축 Content-Encoding, Transfer-Encoding, redirect, 잘못된 MIME·header·checksum 거절.

ZIP 원문은 하나의 제한된 mutable native buffer에만 둔다. 내부 캐시/임시 파일/웹 상태/로그/백업에
저장하지 않고 소유 종료·취소·실패 때 buffer를 지운다. 16KiB로 제한한 오류 JSON도 고정 코드로만
투영하며 서버 원문 message/details를 표시하거나 bridge에 반환하지 않는다.

## SAF 저장과 취소

`ACTION_CREATE_DOCUMENT` + `CATEGORY_OPENABLE`로 새 목적지를 직접 선택한다. 단일 content document
URI, write grant, 일치하는 단일 ClipData만 허용하고 영구 URI 권한을 요청하지 않는다. 제안 파일명은
고정 `sallimbook-export.zip`이며 웹이나 서버의 임의 경로를 저장 위치로 사용하지 않는다.

파일을 모두 받고 무결성을 확인하기 전에는 목적지에 본문을 쓰지 않는다. provider 쓰기에는 별도
180초 제한을 적용하며 각 chunk/flush/완료에서 동일 요청·단조 시각 제한을 확인한다. 마지막 UI 완료도
현재 foreground와 WRITE phase의 성공 소비를 요구한다. 늦은 네트워크/인증 결과는 버리고 성공을 보고하지 않는다.
대기 중인 native buffer는 Activity 종료 때 즉시 지우고 worker의 finally에서도 닫는다.

provider CancellationSignal, file descriptor 및 HTTP 취소는 owner별로 등록하며 서로 덮어쓰지 않는다.
중단 시 이번 선택기로 만든 목적지의 삭제를 시도한다. provider/프로세스 종료에 따라 빈 파일이나
부분 사본이 남을 수 있으므로 외부 사본을 완전히 회수했다고 보장하지 않는다. 서버 발급 감사는 사용자
저장 성공과 다르며 `exported`는 provider 쓰기·flush·close와 최종 요청 검사가 성공한 경우에만 반환한다.

## 실행한 검증

2026-10-18 WSL에서 frozen install, typecheck, Android sync를 실행했다.

```bash
pnpm install --frozen-lockfile
pnpm typecheck
pnpm android:sync
JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ANDROID_HOME=/home/jihoon/Android/Sdk \
  ./gradlew --no-daemon --max-workers=2 :app:testDebugUnitTest :app:assembleDebug :app:compileReleaseKotlin
```

Gradle 명령은 `apps/client/android`에서 실행했다. JVM **308개**(실패·오류·건너뜀 0), debug APK,
release Kotlin을 통과했다. 추가 17개는 선택/오류/단조 시각 정책 6개, bounded buffer/해시/취소 5개,
실제 OkHttp 요청·응답 경계 6개다. HTTP 테스트는 합성 interceptor를 사용하며 실제 서버 권한이나
Android provider를 실행한 결과가 아니다.

브라우저 **58개**(export bridge 34개 + 기존 document bridge 24개)를 desktop/android-size에서 통과했다.
전용 임시 설정에서 baseURL/webServer만 18754로 바꾸고 workers=1로 실행했다. 테스트 종료 후 Vite 종료와
포트 해제, 임시 설정 제거를 확인했다. 모의시험은 status-only 반환, 선택 복사, 잘못된 필드/범위/중복,
세션/잠금/취소/오류와 웹 우회·재전송·저장소 사용 없음을 확인한다.

`uv run --frozen --project services/api pytest services/api/tests/test_exports_encoding.py -q`의
export 형식·선택 schema·응답 제한·취소 수명 검사 **44개**도 통과했다. 이 명령은 DB를 쓰지 않으며
서버/마이그레이션/계약/lockfile을 수정하지 않았다. DB 권한·최근 인증의 서버 통합시험 결과와 구분한다.

실제 Android 재인증·SAF·파일 제공자·64MiB 메모리/저장·잠금·늦은 callback·부분 사본 삭제는 아직
두 Galaxy에서 실행하지 않았다. proxy/log/bridge/backup 검사, 잘못된 hash·권한 철회·저장 공간 부족·
provider 지연/강제 종료와 새 서버 복원도 인수 단계에서 별도로 수행해야 한다.
