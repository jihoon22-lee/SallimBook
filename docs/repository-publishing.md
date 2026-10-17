# GitHub 저장소 게시

## 1. 이 패키지와 원격 저장소를 구분하기

이 문서 패키지는 GitHub CLI로 `jihoon22-lee/SallimBook`을 생성하고 파일·마일스톤·이슈를 게시할 수 있다.
패키지를 다운로드하거나 dry-run을 실행한 것만으로 원격 저장소가 생기지 않는다.
**실제 게시 성공 여부는 실행 결과와 `publish-report.json`, GitHub 조회로 확인한다.**
앱·API·운영 DB를 설치하거나 배포하는 스크립트가 아니다.

## 2. 준비

Python 3.10 이상과 인증된 GitHub CLI(`gh`)가 필요하다. Python 외부 패키지는 필요하지 않다.
GitHub CLI 설치는 공식 안내를 따른다: https://cli.github.com/manual/installation

```bash
# ZIP을 풀고 README.md가 있는 SallimBook 디렉터리로 이동한다.
cd SallimBook
python3 --version
gh --version
gh auth login --hostname github.com
gh auth status --hostname github.com
```

계정 소유자는 `jihoon22-lee`여야 한다. 스크립트는 인증된 로그인과 `--owner`를 대조하고 다르면 생성 전에 중지한다.
GitHub 앱의 읽기 전용 연결 권한과 로컬 gh 인증은 별개다. 브라우저 로그인 방식으로 gh를 인증하고 토큰을 채팅·문서에 붙여 넣지 않는다.
개인 저장소 생성, Contents 쓰기, Issues·Milestones 쓰기가 가능한 인증이 필요하다.
특정 저장소만 선택한 fine-grained 토큰은 아직 없는 저장소를 만들고 접근하는 데 충분하지 않을 수 있다.
조직에 저장소를 생성하는 기능은 이 게시기에 없다.

## 3. 검증 후 게시

```bash
python3 scripts/validate_docs.py
python3 -m unittest discover -s tests -v
python3 scripts/publish_github.py --owner jihoon22-lee --dry-run

# 이 명령부터 실제 GitHub 쓰기가 발생한다.
python3 scripts/publish_github.py --owner jihoon22-lee --apply
```

명령을 생략하면 기본은 dry-run이며 네트워크 요청을 하지 않는다.
`--apply`는 새 **비공개** 저장소를 생성하고 문서 파일들을 하나의 문서 커밋으로 올린 뒤
계획용 labels, **9개 마일스톤**, **40개 구현 이슈**를 만든다. GitHub의 최초 README 초기화 커밋은 별도로 생길 수 있다.
기존 저장소의 기본 브랜치 이름을 사용하며 새 저장소에서도 `main`이라고 가정하지 않는다.
문서의 기본 브랜치와 실제 이슈 URL을 사용해 선행 작업·설계 참조를 연결한다.

코드·문서 공개를 결정한 경우에만 `--visibility public`을 명시한다. 기존 저장소의 공개 범위는 자동 변경하지 않는다.
소스 공개 여부와 실제 금융·건강 데이터 보관은 별개이며, 실제 데이터·키·서명 파일은 절대 Git에 넣지 않는다.

## 4. 이미 저장소가 있을 때

동일 패키지의 관리 manifest가 있는 저장소는 누락된 파일·마일스톤·이슈를 보완할 수 있다.
기존 Issue의 체크리스트·본문·닫힘 상태와 마일스톤 상태를 자동으로 초기화하지 않는다.
원격 파일이 사용자가 수정한 상태라면 덮어쓰지 않고 중지한다. 관련 변경을 먼저 검토한다.

직접 만들어 둔 **빈 저장소 또는 README만 있는 저장소**에 처음 게시하려면:

```bash
python3 scripts/publish_github.py --owner jihoon22-lee --apply --adopt-empty
```

이 옵션은 README 교체에 대한 명시적 동의다. 다른 코드가 들어 있는 저장소에는 적용되지 않는다.
새 저장소 생성 직후 중단되어 관리 manifest가 아직 없을 때도 원격이 README-only인지 확인한 후 이 옵션으로 재개한다.
동일 이름의 기존 저장소가 비공개/공개 설정과 다르면 자동 전환하지 않고 중지한다.

문서만 먼저 게시할 때는 `--docs-only`를 사용한다. 나중에 옵션 없이 재실행하면 계획을 추가한다.
동일 제목이지만 관리 ID가 없는 이슈가 있으면 자동 연결하거나 중복 생성하지 않는다.

## 5. 업로드 안전장치

- `.sallimbook-docs-manifest.json`의 허용 목록과 SHA-256/Git blob hash가 일치하는 UTF-8 파일만 읽는다.
- 작업 디렉터리를 통째로 `git add`하지 않는다. `.env`, DB, APK, 서명키, 로그, 실행 보고서는 게시하지 않는다.
- 경로 이탈·심볼릭 링크·크기 초과를 거부한다. 원격 문서 파일도 일반 파일 형식인지 검사한다.
- Git tree/commit API와 `force: false` ref 갱신으로 기존 코드를 삭제하거나 강제 push하지 않는다.
- 동시에 브랜치가 이동해 갱신이 충돌하면 중지하고 재조회한다. 쓰기 시간초과를 자동 반복하지 않는다.
- 정상 게시 뒤 원격 파일 hash와 계획 Issue ID의 존재를 다시 조회한다.

manifest는 **실수로 변경된 패키지를 탐지**하기 위한 것이다. 공격자가 파일과 manifest를 함께 교체하는 경우를 막는 전자서명이 아니다.
배포 ZIP의 출처와 별도 checksum을 확인한다.

## 6. 중간 실패와 재실행

스크립트는 진행 단계를 로컬 `publish-report.json`에 남긴다. 인증 토큰이나 금융 데이터는 기록하지 않는다.
일부 작업 뒤 실패하면 이미 생성된 저장소·커밋·이슈를 삭제하지 않는다.
먼저 보고서와 GitHub 상태를 확인하고 권한·네트워크·충돌 원인을 해결한 뒤 재실행한다.
GitHub Issue 쓰기에는 이 게시기의 원자적 일괄 트랜잭션이 없으므로 동시에 두 게시기를 실행하지 않는다.

원격 404는 저장소가 없다는 뜻일 수도 있고 인증 범위 때문에 볼 수 없다는 뜻일 수도 있다.
이 경우 생성 시도가 실패할 수 있으며 이름을 임의로 바꾸거나 권한을 우회하지 않는다.
로그인 실패 시 `gh auth status`를 확인하고, 사용자 계정의 인증을 완료한다.

## 7. 게시 후 개발 checkout

게시기는 git 작업 디렉터리를 초기화하지 않는다. 성공 후 원하는 WSL 개발 경로에서:

```bash
gh repo clone jihoon22-lee/SallimBook
cd SallimBook
```

`AGENTS.md`와 `planning/ISSUES.md`를 읽고 SB-001부터 시작한다.
패키지 파일을 수정한 후 다시 게시하려면 manifest의 허용 목록·hash도 명시적으로 갱신해야 한다.
일반 개발 변경은 이 최초 게시기보다 정상 Git 브랜치·PR 리뷰 흐름을 사용한다.

## 8. 검사 범위

로컬 자동 테스트는 게시기의 입력 검증·충돌 처리·가상 GitHub 응답·재실행을 검사한다.
실제 GitHub 권한·네트워크·API 호환성을 대신 보장하지 않으며, 실제 적용 결과를 별도로 확인해야 한다.
기술 근거: [GitHub CLI 및 Git API 공식 자료 S14~S17](references.md).
