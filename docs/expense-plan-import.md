# 월 지출 계획 최초 등록과 배포

R-08/R-18 · Issue #189. 공개 예제에는 합성 자료만 사용한다. 원본 자료와 대상 가계 ID는 운영자 전용 파일로 관리한다.

## 입력 및 실행

`ops.import_expense_plans`는 기존 서비스 검증과 감사 생성을 재사용한다. HTTP 요청을 행마다 보내 중간 저장하는 방식이 아니다. `create_plan_in_transaction`은 commit하지 않고 전체 batch가 한 번 commit된다. 기본 명령은 읽기 전용 preview이며 `--apply`를 명시한 경우에만 기록한다.

JSON 입력은 `ImportRequest`(household_id, actor_member_id, source_id, manifest_hash, rows, expected_rules_fingerprint)이며 각 행은 고유 source_key와 `PlanCreate` 본문이다. 최초 적용일은 서버의 서울 기준 실행일이고 실제 계약 시작일을 의미하지 않는다. 호출자가 임의 effective_from이나 scheduled를 공급하면 거부한다. preview receipt의 `rules_fingerprint`를 최초 apply 입력의 `expected_rules_fingerprint`로 고정한다. 이는 기존 모든 규칙 ID와 버전의 해시다. 가계 잠금 안에서 다시 비교하므로 preview 이후 일반 사용자가 생성·수정·삭제하면 전체 적용을 거부한다. 자동 병합하거나 새 fingerprint로 무조건 재시도하지 않는다. 기존 내용과 입력의 중복 여부를 다시 대조한 뒤에만 기준을 갱신한다. 이미 완료된 동일 출처 재실행은 이 기준 비교를 건너뛰고 원래 결과를 돌려준다. 회원은 현재 대상 가계의 활성 회원이어야 하고 결제수단/관련 구성원도 그 가계에 속해야 한다.

`manifest_digest(rows)`는 source_key 정렬과 스키마 기본값을 적용한 JSON의 SHA-256이다. actor와 실행일은 digest에서 제외하므로 다음날이나 배우자가 재실행해도 같은 최초 자료다. source_id는 등록 작업의 영구 식별자이며 재시도 때 바꾸지 않는다.

운영 API 환경의 같은 DB 설정을 사용한다. stdin 또는 운영자 소유의 0600 일반 파일만 읽는다. symlink와 과도한 입력 크기는 거부한다. 터미널에는 건수·상태·정해진 오류 코드만 출력하며 금액·이름·검증 실패 원문·SQL 인자를 출력하지 않는다. 선택적인 `--receipt`는 새 0600 파일로만 생성하고 기존 파일을 덮지 않는다. receipt에는 생성 ID·최초 적용일·삭제 여부가 있으므로 공개 보고에 첨부하지 않는다.

```sh
python -m ops.import_expense_plans --file /private/normalized-manifest.json
python -m ops.import_expense_plans --file /private/normalized-manifest.json --apply --receipt /private/new-receipt.json
```

컨테이너 stdin 사용 시 명령은 `python -m ops.import_expense_plans --file -`다. 연결된 운영 환경을 정확히 선택하고 비밀 환경변수나 입력 JSON을 셸 인자로 넣지 않는다. preview와 apply 사이의 상태 변경은 apply에서 다시 검증한다.

## 재실행·사용자 수정·삭제

0027의 `expense_import_batches`에 (가계, source_id), `expense_import_rows`에 (가계, source_id, source_key) 고유 제약을 둔다. 가계 잠금이 동시 실행을 직렬화한다. 동일 출처·동일 hash 재실행은 원래 ID와 적용일을 돌려주며 새로 생성하거나 사용자 수정 내용을 덮지 않는다. 같은 출처의 다른 hash는 409 충돌이다. 이 도구는 수정용 도구가 아니다.

일반 계획 삭제 경로는 현재 rule FK를 해제하고 `user_deleted`를 기록한다. 원래 생성 ID와 hash는 보존한다. 재실행이 삭제한 항목을 부활시키지 않는다. provenance는 새 본문/금액 복사본을 저장하지 않으며 DB 트리거가 이력 수정·삭제를 금지한다. 실제 납부나 확정 기록이 있으면 기존 계획 삭제 제한을 유지한다. 사용자용 내보내기는 계획 본문과 새 열을 포함하고 운영 provenance는 제외한다.

## 검증·배포 순서

1. 최종 소스의 전체 CI·Android 검사·실제 HTTPS 검사를 끝까지 확인한다. 중간 실패 뒤 건너뛴 단계는 통과가 아니다.
2. 운영 소스 revision, 이미지 ID, APK 버전/서명, schema, 타 서비스 ID/시작 시각을 기록한다. 대상 가계·회원·수단을 비공개 파일에서 유일하게 매칭하고 현재 데이터와 중복 후보를 읽기 확인한다.
3. 기존 운영 자동화로 배포 전 암호화 백업 및 격리 복원을 검증한다.
4. 새 additive migration과 호환 API를 적용하고 실제 schema/readiness 및 구 API 읽기를 확인한다.
5. readonly preview 후 정규화 파일의 고정 hash로 apply한다. 생성 건수·합계·미정/0·관련자·계좌/카드 연결을 독립 읽기로 검증한다. 기존 수입·보너스·잔액·월 확정은 변경되지 않아야 한다.
6. 동일 manifest replay의 생성 건수 0과 같은 최초 ID/적용일을 확인한다. 실제 납부·가짜 연체를 만들지 않는다.
7. 같은 최종 소스의 웹·서명 APK로 전환한다. 홈/계획/수단 연결을 실제 사용자 경로로 확인한다. 새 자료를 확인하려고 수정·삭제하는 시험은 하지 않는다.
8. 배포 후 백업·격리 복원에서 새 테이블/열·원문 메모·합계 보존을 확인한다. 예약 작업을 새 설정으로 연결하고 기존 WRG 시작 조건을 보존한다. source/이미지/schema/APK 증거와 실제 기기 미실행 범위를 분리 보고한다.

## 복구

commit 전 실패는 전체 rollback이다. commit 후 응답 유실은 같은 source_id/hash로 조회/재실행해 확인한다. import 이후 API 롤백 하한은 0026/0027의 nullable 계획과 provenance를 이해하는 호환 API다. 이전 0.1.13 API로 자동 복귀하지 않는다. 웹/APK를 되돌려야 해도 이 호환 API와 스키마를 유지한다. 새 데이터가 있는 스키마 downgrade는 거부한다.

금액/분류를 수정할 때는 일반 버전/감사 경로를 사용한다. 운영 DB를 초기화하거나 이전 백업으로 자동 덮어쓰지 않는다. 복원은 격리 DB에서 검증하고 기존 운영 DB와 타 프로젝트 컨테이너·볼륨·Tailscale 설정을 보존한다.
