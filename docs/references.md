# 공식 참고 자료

확인 기준일: **2026-10-17**. 아래는 외부 기술·정책 사실의 근거다.
프로젝트의 잠금 시간·DB 구조·화면·마일스톤은 자체 설계 결정이며 출처가 해당 설계를 인증하는 것은 아니다.
라이브러리의 실제 패치 버전과 배포 정책은 구현/출시 시 다시 확인한다.

| ID | 공식 자료 | 사용하는 부분 |
|---|---|---|
| S01 | [Capacitor 환경 설정](https://capacitorjs.com/docs/getting-started/environment-setup) | Node/Android 환경과 웹·네이티브 대상 |
| S02 | [Capacitor 8 이행 문서](https://capacitorjs.com/docs/updating/8-0) | SDK·Gradle·Kotlin 호환 기준 확인 |
| S03 | [Android 생체인증](https://developer.android.com/identity/sign-in/biometric-auth) | BiometricPrompt, CryptoObject, 인증수단·키무효화 |
| S04 | [Android Keystore](https://developer.android.com/privacy-and-security/keystore) | 기기 키와 사용자 인증에 의한 키 사용 |
| S05 | [Android Credential Manager](https://developer.android.com/identity/credential-manager) | 계정 로그인·패스키 경로 |
| S06 | [MDN Web Authentication API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Authentication_API) | 웹 인증과 브라우저·인증장치 관계 |
| S07 | [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) | 로그인 해시·KDF 비용 참고 |
| S08 | [PCI SSC FAQ 1574](https://www.pcisecuritystandards.org/faqs/1574/) | 서비스제공자 저장과 소비자 기기 입력 사례 구분 |
| S09 | [PCI SSC FAQ 1280](https://www.pcisecuritystandards.org/faqs/1280/) | 승인 후 보안코드 저장 금지 설명 |
| S10 | [PostgreSQL numeric](https://www.postgresql.org/docs/current/datatype-numeric.html) | 정확한 금액 자료형 |
| S11 | [FastAPI 기능](https://fastapi.tiangolo.com/features/) | OpenAPI와 타입 기반 API |
| S12 | [Android Auto Backup](https://developer.android.com/identity/data/autobackup) | 백업·기기이전 제외, noBackupFilesDir |
| S13 | [Android FLAG_SECURE](https://developer.android.com/reference/android/view/WindowManager.LayoutParams#FLAG_SECURE) | 민감 화면 캡처/비보안 표시 제한 |
| S14 | [GitHub CLI gh api](https://cli.github.com/manual/gh_api) | 인증된 REST 호출과 JSON body |
| S15 | [GitHub Git Trees API](https://docs.github.com/en/rest/git/trees) | 문서 파일을 하나의 tree/commit으로 게시 |
| S16 | [GitHub Milestones API](https://docs.github.com/en/rest/issues/milestones) | 마일스톤 생성/조회 |
| S17 | [GitHub CLI repository create](https://cli.github.com/manual/gh_repo_create) | 저장소 생성 개념 및 공개 범위 |
| S18 | [Android CLI build](https://developer.android.com/build/building-cmdline) | CLI 빌드와 APK |
| S19 | [Android app signing](https://developer.android.com/studio/publish/app-signing) | 정식 서명과 키 관리 |
| S20 | [Android developer verification](https://developer.android.com/developer-verification) | 출시 시 직접 배포 경로·정책 재확인 |

외부 문서를 그대로 복사하지 않고 필요한 개념만 요약했다.
개인 금융/보험 계약에 관한 외부 사실은 이 설계 문서에서 단정하지 않는다.
