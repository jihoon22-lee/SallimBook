# 기여·개발 흐름

[AGENTS.md](AGENTS.md)를 먼저 읽습니다. 이 프로젝트는 사람과 여러 개발 에이전트가 같은 규칙으로 작업합니다.

## Issue와 브랜치

`SB-xxx`는 계획 식별자이며 GitHub Issue 번호와 다릅니다. 발행 후 번호는 게시 결과 및 Issue 링크로 확인합니다.
브랜치 예시는 `feat/SB-013-fixed-payments`, `fix/SB-022-payout-allocation`입니다.
기본 브랜치는 실제 저장소의 default branch를 조회해 사용합니다. `main`을 관례로 권장하지만 하드코딩하지 않습니다.
기초 문서 초기화 이외 기능 변경은 PR로 검토합니다. 담당 Issue가 없는 광범위한 재작성은 금지합니다.

## PR 크기와 리뷰

한 PR에 하나의 사용자 동작 또는 일관된 데이터 변경을 담습니다.
DB 스키마 변경은 Alembic migration, 변환/복구 절차, 기존 데이터 영향과 검증을 포함합니다.
암호화·권한·복구·첨부 다운로드 변경에는 보안 체크리스트를 붙입니다.
부부의 다른 계정과 Android/웹의 다른 화면에서 어떻게 보이는지 적습니다.

## 커밋

`docs:`, `feat:`, `fix:`, `test:`, `refactor:`, `chore:` 접두사를 권장합니다.
메시지는 한국어 또는 명확한 영어로 작성하고 자동 생성 파일과 수작업 파일을 구분합니다.
실제 금융·건강정보 및 서명키는 커밋에서 영구 배제합니다. 유출 시 단순 파일 삭제로 끝내지 않고 키/토큰 폐기와 이력 대응을 수행합니다.

## 서식

커밋 전에 `pnpm format`과 `uv run --project services/api ruff format services/api/src services/api/tests services/api/migrations`를 실행합니다.
CI는 `pnpm format:check`와 `ruff format --check`로 같은 범위를 검사합니다. 생성 파일 `packages/api-client/src/schema.d.ts`는 손으로 고치지 않고 `pnpm api:generate`로 다시 만듭니다.
일괄 서식 커밋 이전에 만든 브랜치는 충돌을 고치기 전에 같은 서식부터 적용합니다.

```bash
git fetch origin
git switch <branch>
git checkout origin/main -- package.json pnpm-lock.yaml .prettierrc.json .prettierignore
pnpm install --frozen-lockfile
pnpm format
git commit -am "chore(format): apply Prettier before rebase"
git rebase origin/main
```

rebase 중 충돌이 남으면 양쪽이 모두 Prettier 서식이므로 내용 차이만 해결하고 `pnpm format`을 다시 실행합니다.
로컬 `git blame`이 서식 커밋을 건너뛰게 하려면 `git config blame.ignoreRevsFile .git-blame-ignore-revs`를 설정합니다.

## 린트

커밋 전에 `pnpm lint`를 실행합니다. ESLint(TypeScript·React Hooks·jsx-a11y 규칙)가 경고 0개로 끝나야 하며 CI도 같은 명령을 실행합니다.
규칙을 끄는 주석은 꼭 필요한 줄에만 `// eslint-disable-next-line <규칙 이름> -- <이유>` 형식으로 답니다.
규칙 이름과 이유를 반드시 적고, 파일 전체를 끄는 `/* eslint-disable */`는 쓰지 않습니다. 쓰이지 않는 disable 주석은 린트 오류입니다.

## 출시

v1의 모든 마일스톤과 인수 기준을 통과해야 v1.0.0을 부여합니다.
문서 작성 완료를 기능 완료로 체크하지 않습니다.
구현 중 내부 빌드는 `0.x` 또는 사전 릴리스로 구분합니다.
릴리스 노트에는 지원 기기·API/DB 버전, 알려진 제한, 백업 필요 여부를 기재합니다.
