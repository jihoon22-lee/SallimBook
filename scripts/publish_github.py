#!/usr/bin/env python3
"""Publish the reviewed SallimBook design bundle through an authenticated gh CLI.

Dry-run is the default and makes no network calls. --apply creates a private
repository by default, publishes allowlisted files in one commit, then creates
missing labels, milestones and issues. It never force-pushes or resets issues.
No third-party Python dependencies are required (Python 3.10+).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = '.sallimbook-docs-manifest.json'
PACKAGE_ID = 'sallimbook-design-20261017'
REPO_NAME = 'SallimBook'
DESCRIPTION = '부부 공동 자산·보험·생활 관리 — Android 앱과 PC 웹'


class PublishError(RuntimeError):
    """An explicit, non-destructive publishing failure."""


class ApiError(PublishError):
    def __init__(self, status: int | None, message: str):
        super().__init__(f'GitHub HTTP {status or "unknown"}: {message}')
        self.status = status


def git_sha(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_path(name: str) -> bool:
    p = PurePosixPath(name)
    return name not in ('', '.') and not p.is_absolute() and '..' not in p.parts and '\\' not in name and str(p) == name


def load_bundle(root: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Read only hash-verified allowlisted files; never sweep a working directory."""
    try:
        if (root / MANIFEST).is_symlink():
            raise PublishError('manifest 심볼릭 링크는 허용하지 않습니다.')
        manifest_bytes = (root / MANIFEST).read_bytes()
        meta = json.loads(manifest_bytes)
    except (OSError, ValueError) as exc:
        raise PublishError(f'문서 manifest를 읽지 못했습니다: {exc}') from exc
    if meta.get('package_id') != PACKAGE_ID or meta.get('schema_version') != 1:
        raise PublishError('알 수 없는 문서 패키지 manifest입니다.')
    files: dict[str, bytes] = {}
    for name, expected in meta.get('files', {}).items():
        if not valid_path(name) or name == MANIFEST:
            raise PublishError(f'허용되지 않은 패키지 경로: {name}')
        path = root / name
        if any((root / Path(*PurePosixPath(name).parts[:n])).is_symlink()
               for n in range(1, len(PurePosixPath(name).parts) + 1)) or not path.resolve().is_relative_to(root.resolve()):
            raise PublishError(f'심볼릭 링크 또는 패키지 밖의 경로: {name}')
        try:
            data = path.read_bytes()
            data.decode('utf-8')
        except (OSError, UnicodeError) as exc:
            raise PublishError(f'UTF-8 문서 파일을 읽지 못했습니다: {name}') from exc
        if sha256(data) != expected['sha256'] or git_sha(data) != expected['git_sha1']:
            raise PublishError(f'패키지 파일이 원본과 다릅니다: {name}. 변경 내용을 검토하고 manifest를 명시적으로 갱신하세요.')
        if len(data) > 1_000_000:
            raise PublishError(f'문서 게시 허용 크기 초과: {name}')
        files[name] = data
    if not files or 'README.md' not in files or 'planning/backlog.json' not in files:
        raise PublishError('필수 패키지 파일이 없습니다.')
    files[MANIFEST] = manifest_bytes
    return files, meta


def validate_plan(plan: dict[str, Any], files: dict[str, bytes]) -> None:
    if plan.get('project') != REPO_NAME or plan.get('schema_version') != 1:
        raise PublishError('알 수 없는 계획 형식입니다.')
    milestones = [m['id'] for m in plan['milestones']]
    issue_ids = [i['id'] for i in plan['issues']]
    if len(set(milestones)) != len(milestones) or len(set(issue_ids)) != len(issue_ids):
        raise PublishError('마일스톤 또는 Issue 계획 ID가 중복입니다.')
    if len({m['title'] for m in plan['milestones']}) != len(milestones):
        raise PublishError('마일스톤 제목이 중복입니다.')
    known = set(issue_ids)
    labels = {x['name'] for x in plan['labels']}
    graph: dict[str, list[str]] = {}
    for item in plan['issues']:
        ident = item['id']
        if not re.fullmatch(r'SB-\d{3}', ident) or item['milestone'] not in milestones:
            raise PublishError(f'계획 ID/마일스톤 오류: {ident}')
        if not item['acceptance'] or not item['tests']:
            raise PublishError(f'완료 조건 또는 검증이 없습니다: {ident}')
        if not {'type:feature', 'priority:' + item['priority'], 'area:' + item['area']} <= labels:
            raise PublishError(f'계획 label 정의가 없습니다: {ident}')
        if any(d not in known for d in item['depends_on']):
            raise PublishError(f'존재하지 않는 선행 Issue: {ident}')
        if any(d not in files for d in item['docs']):
            raise PublishError(f'존재하지 않는 문서 참조: {ident}')
        graph[ident] = item['depends_on']
    active, visited = set(), set()
    def visit(ident: str) -> None:
        if ident in active:
            raise PublishError('선행 작업 그래프에 순환이 있습니다.')
        if ident in visited:
            return
        active.add(ident)
        for dep in graph[ident]:
            visit(dep)
        active.remove(ident)
        visited.add(ident)
    for ident in issue_ids:
        visit(ident)


def ordered_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {i['id']: i for i in items}
    result, seen = [], set()
    def add(ident: str) -> None:
        if ident in seen:
            return
        for dep in by_id[ident]['depends_on']:
            add(dep)
        seen.add(ident)
        result.append(by_id[ident])
    for item in items:
        add(item['id'])
    return result


class GhApi:
    """Use gh's own credential store; never read or print tokens."""
    def __init__(self) -> None:
        if shutil.which('gh') is None:
            raise PublishError('GitHub CLI(gh)가 없습니다. 공식 CLI를 설치하고 gh auth login을 먼저 실행하세요.')

    def request(self, method: str, endpoint: str, payload: Any = None) -> Any:
        cmd = ['gh', 'api', '--hostname', 'github.com', '--method', method,
               '--include', '-H', 'Accept: application/vnd.github+json',
               '-H', 'X-GitHub-Api-Version: 2022-11-28', endpoint]
        if payload is not None:
            cmd += ['--input', '-']
        try:
            proc = subprocess.run(cmd, input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                                  capture_output=True, text=True, encoding='utf-8', timeout=90,
                                  env={**os.environ, 'GH_PAGER': 'cat', 'NO_COLOR': '1'})
        except subprocess.TimeoutExpired as exc:
            raise PublishError('GitHub 요청이 시간 초과되었습니다. 쓰기 완료 여부가 불확실하므로 결과를 확인한 뒤 재실행하세요.') from exc
        output = proc.stdout.replace('\r\n', '\n')
        status = None
        body = output
        if output.startswith('HTTP/'):
            header, sep, body = output.partition('\n\n')
            match = re.match(r'HTTP/\S+\s+(\d+)', header)
            status = int(match.group(1)) if match else None
            if not sep:
                body = ''
        data = None
        if body.strip():
            try:
                data = json.loads(body)
            except ValueError as exc:
                if proc.returncode == 0:
                    raise PublishError('GitHub에서 JSON이 아닌 응답을 받았습니다.') from exc
        if proc.returncode or (status is not None and status >= 400):
            if status is None:
                match = re.search(r'HTTP (\d+)', proc.stderr)
                status = int(match.group(1)) if match else None
            msg = data.get('message', '') if isinstance(data, dict) else ''
            if not msg:
                msg = '인증/권한 또는 연결 상태를 확인하세요. gh auth status를 사용하세요.'
            raise ApiError(status, msg)
        return data


def list_all(api: Any, endpoint: str) -> list[dict[str, Any]]:
    result = []
    sep = '&' if '?' in endpoint else '?'
    for page in range(1, 101):
        data = api.request('GET', f'{endpoint}{sep}per_page=100&page={page}')
        if not isinstance(data, list):
            raise PublishError('목록 API가 예상하지 않은 형식을 반환했습니다.')
        result.extend(data)
        if len(data) < 100:
            return result
    raise PublishError('안전 페이지 한도를 초과했습니다. 저장소 상태를 직접 확인하세요.')


def plan_changes(local: dict[str, bytes], remote: dict[str, str], previous: dict[str, Any] | None,
                 allow_initial_readme: bool = False) -> dict[str, bytes]:
    """Never overwrite user-edited managed files or unknown existing files."""
    changed = {}
    prior_files = previous.get('files', {}) if previous else {}
    for path, data in local.items():
        current = remote.get(path)
        if current == git_sha(data):
            continue
        if current is None:
            changed[path] = data
            continue
        if path == MANIFEST and previous and previous.get('package_id') == PACKAGE_ID:
            changed[path] = data
            continue
        old = prior_files.get(path, {}).get('git_sha1')
        if old and current == old:
            changed[path] = data
            continue
        if allow_initial_readme and path == 'README.md':
            changed[path] = data
            continue
        raise PublishError(f'기존 파일을 안전하게 덮어쓸 수 없습니다: {path}. 원격 변경을 먼저 검토하세요.')
    return changed


def issue_body(item: dict[str, Any], repo: str, branch: str, created: dict[str, dict[str, Any]]) -> str:
    marker = f'<!-- sallimbook:issue:{item["id"]} -->'
    base = f'https://github.com/{repo}/blob/{quote(branch, safe="")}/'
    lines = [marker, '## 목적', '', item['description'], '',
             '**목표:** v1.0.0 · **계획 ID:** ' + item['id'],
             '**요구사항:** ' + ', '.join(item['requirements']), '', '## 선행 작업', '']
    if item['depends_on']:
        for dep in item['depends_on']:
            if dep not in created:
                raise PublishError(f'{item["id"]}의 선행 Issue가 아직 게시되지 않았습니다: {dep}')
            lines.append(f'- [{dep}]({created[dep]["html_url"]})')
    else:
        lines.append('없음.')
    lines += ['', '## 완료 조건', ''] + ['- [ ] ' + a for a in item['acceptance']]
    lines += ['', '## 검증', ''] + ['- ' + t for t in item['tests']]
    lines += ['', '## 설계 문서', ''] + [f'- [{p}]({base}{quote(p, safe="/")})' for p in item['docs']]
    lines += ['', '## 공통 지침', '',
              f'[AGENTS.md]({base}AGENTS.md)를 따른다. 특정 AI 도구 전용 작업이 아니다.',
              '실제 개인정보·비밀은 이슈/로그/fixture에 첨부하지 않는다. 문서 작성만으로 기능 완료 처리하지 않는다.']
    return '\n'.join(lines) + '\n'


@dataclass
class Options:
    owner: str = 'jihoon22-lee'
    visibility: str = 'private'
    adopt_empty: bool = False
    docs_only: bool = False


class Publisher:
    def __init__(self, api: Any, root: Path, files: dict[str, bytes], manifest: dict[str, Any],
                 plan: dict[str, Any], options: Options):
        self.api, self.root, self.files, self.manifest, self.plan, self.options = api, root, files, manifest, plan, options
        self.repo = f'{options.owner}/{REPO_NAME}'
        self.base = f'repos/{self.repo}'
        self.report: dict[str, Any] = {'repository': self.repo, 'status': 'started', 'stages': [],
                                       'milestones': {}, 'issues': {}, 'repository_created': False}

    def checkpoint(self, stage: str) -> None:
        self.report['stages'].append(stage)
        self.save_report()
        print(stage, flush=True)

    def save_report(self) -> None:
        temp = self.root / 'publish-report.json.tmp'
        temp.write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temp.replace(self.root / 'publish-report.json')

    def snapshot(self, branch: str) -> tuple[str, str, dict[str, str]]:
        ref = self.api.request('GET', f'{self.base}/git/ref/heads/{quote(branch, safe="/")}')
        head = ref['object']['sha']
        commit = self.api.request('GET', f'{self.base}/git/commits/{head}')
        tree_sha = commit['tree']['sha']
        tree = self.api.request('GET', f'{self.base}/git/trees/{tree_sha}?recursive=1')
        if tree.get('truncated'):
            raise PublishError('원격 tree가 잘려서 안전하게 확인할 수 없습니다.')
        for entry in tree['tree']:
            if entry['path'] in self.files and (entry['type'] != 'blob' or entry.get('mode') != '100644'):
                raise PublishError('관리 경로가 일반 문서 파일이 아닙니다: ' + entry['path'])
        return head, tree_sha, {x['path']: x['sha'] for x in tree['tree'] if x['type'] == 'blob'}

    def publish(self) -> dict[str, Any]:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', self.options.owner):
            raise PublishError('올바르지 않은 GitHub 사용자 이름입니다.')
        user = self.api.request('GET', 'user')
        if user['login'].casefold() != self.options.owner.casefold():
            raise PublishError(f'로그인 계정({user["login"]})과 대상 소유자가 다릅니다. 다른 계정에 생성하지 않습니다.')
        self.checkpoint('GitHub 인증 계정 확인 완료')
        try:
            repo = self.api.request('GET', self.base)
        except ApiError as exc:
            if exc.status != 404:
                raise
            repo = self.api.request('POST', 'user/repos', {
                'name': REPO_NAME, 'description': DESCRIPTION,
                'private': self.options.visibility == 'private', 'auto_init': True,
                'has_issues': True, 'has_wiki': False})
            self.report['repository_created'] = True
            self.checkpoint('새 저장소 생성 완료')
        if bool(repo['private']) != (self.options.visibility == 'private'):
            raise PublishError('기존 저장소 공개 범위가 선택한 값과 다릅니다. 공개 범위는 자동 변경하지 않습니다.')
        if repo.get('archived'):
            raise PublishError('보관된 저장소에는 게시하지 않습니다.')
        branch = repo.get('default_branch') or 'main'
        self.report.update({'repository_url': repo.get('html_url', f'https://github.com/{self.repo}'), 'default_branch': branch})
        # Auto-init may be eventually consistent. Only retry safe GETs.
        for attempt in range(5):
            try:
                head, tree_sha, remote = self.snapshot(branch)
                break
            except ApiError as exc:
                if self.report['repository_created'] and exc.status in (404, 409) and attempt < 4:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                if exc.status in (404, 409) and self.options.adopt_empty:
                    # Initialize an explicitly adopted empty repository with our README.
                    self.api.request('PUT', f'{self.base}/contents/README.md', {
                        'message': 'docs: initialize SallimBook design repository',
                        'content': base64.b64encode(self.files['README.md']).decode('ascii'), 'branch': branch})
                    head, tree_sha, remote = self.snapshot(branch)
                    break
                raise
        previous = None
        if MANIFEST in remote:
            blob = self.api.request('GET', f'{self.base}/git/blobs/{remote[MANIFEST]}')
            try:
                previous = json.loads(base64.b64decode(blob['content']))
            except (ValueError, KeyError) as exc:
                raise PublishError('기존 관리 manifest를 읽을 수 없습니다.') from exc
            if previous.get('package_id') != PACKAGE_ID or previous.get('schema_version') != 1:
                raise PublishError('다른 패키지/프로젝트의 manifest가 있습니다.')
        initial = self.report['repository_created']
        if not previous and not initial:
            if not self.options.adopt_empty or set(remote) - {'README.md'}:
                raise PublishError('관리되지 않은 기존 저장소입니다. 빈 저장소/README만 있는 경우에만 --adopt-empty로 명시적으로 채택할 수 있습니다.')
        allow_readme = initial or (self.options.adopt_empty and set(remote) <= {'README.md'})
        changes = plan_changes(self.files, remote, previous, allow_readme)
        if changes:
            tree = self.api.request('POST', f'{self.base}/git/trees', {
                'base_tree': tree_sha,
                'tree': [{'path': p, 'mode': '100644', 'type': 'blob', 'content': data.decode('utf-8')}
                         for p, data in sorted(changes.items())]})
            commit = self.api.request('POST', f'{self.base}/git/commits', {
                'message': 'docs: add SallimBook product, architecture, security and v1 delivery plan',
                'tree': tree['sha'], 'parents': [head]})
            self.api.request('PATCH', f'{self.base}/git/refs/heads/{quote(branch, safe="/")}',
                             {'sha': commit['sha'], 'force': False})
            self.report['commit_sha'] = commit['sha']
        else:
            self.report['commit_sha'] = head
        self.report['commit_url'] = f'https://github.com/{self.repo}/commit/{self.report["commit_sha"]}'
        _, _, verify = self.snapshot(branch)
        wrong = [p for p, data in self.files.items() if verify.get(p) != git_sha(data)]
        if wrong:
            raise PublishError('원격 문서 검증 실패: ' + ', '.join(wrong[:5]))
        self.report['files_verified'] = len(self.files)
        self.checkpoint(f'문서 {len(self.files)}개 원격 hash 검증 완료')
        if not self.options.docs_only:
            if repo.get('has_issues') is False:
                raise PublishError('기존 저장소의 Issues 기능이 비활성화되어 있습니다. 문서는 게시했으나 이슈/마일스톤을 만들 수 없습니다.')
            self.publish_planning(branch)
        self.report['status'] = 'completed'
        self.checkpoint('게시 및 조회 검증 완료')
        return self.report

    def publish_planning(self, branch: str) -> None:
        labels = {x['name']: x for x in list_all(self.api, f'{self.base}/labels')}
        for item in self.plan['labels']:
            if item['name'] not in labels:
                self.api.request('POST', f'{self.base}/labels', item)
        self.checkpoint('계획 label 확인 완료')
        known_ms = list_all(self.api, f'{self.base}/milestones?state=all')
        milestone_map = {}
        for item in self.plan['milestones']:
            match = [m for m in known_ms if m['title'] == item['title']]
            if len(match) > 1:
                raise PublishError('중복 제목의 마일스톤이 있습니다: ' + item['title'])
            if match:
                found = match[0]
            else:
                found = self.api.request('POST', f'{self.base}/milestones', {
                    'title': item['title'], 'description': f'<!-- sallimbook:milestone:{item["id"]} -->\n' + item['description'],
                    'state': 'open'})
            milestone_map[item['id']] = found['number']
            self.report['milestones'][item['id']] = {'number': found['number'], 'url': found['html_url']}
            self.save_report()
        self.checkpoint(f'마일스톤 {len(milestone_map)}개 확인 완료')
        existing = list_all(self.api, f'{self.base}/issues?state=all')
        issue_map = {}
        for item in existing:
            if 'pull_request' in item:
                continue
            matches = re.findall(r'<!-- sallimbook:issue:(SB-\d{3}) -->', item.get('body') or '')
            for ident in matches:
                if ident in issue_map:
                    raise PublishError(f'동일 계획 ID의 원격 Issue가 여러 개입니다: {ident}')
                issue_map[ident] = item
        for item in ordered_issues(self.plan['issues']):
            ident = item['id']
            title = f'[{ident}] {item["title"]}'
            if ident in issue_map:
                found = issue_map[ident]
                action = 'existing'
            else:
                if any(x['title'] == title for x in existing):
                    raise PublishError(f'같은 제목의 관리되지 않은 Issue가 있습니다: {title}. 중복 생성하지 않습니다.')
                found = self.api.request('POST', f'{self.base}/issues', {
                    'title': title, 'body': issue_body(item, self.repo, branch, issue_map),
                    'milestone': milestone_map[item['milestone']],
                    'labels': ['type:feature', 'priority:' + item['priority'], 'area:' + item['area']]})
                issue_map[ident] = found
                action = 'created'
            self.report['issues'][ident] = {'number': found['number'], 'url': found['html_url'], 'action': action}
            self.save_report()
        # Verify existence by fresh reads. Do not overwrite user-edited states/bodies.
        actual = list_all(self.api, f'{self.base}/issues?state=all')
        verified = {m for x in actual if 'pull_request' not in x
                    for m in re.findall(r'<!-- sallimbook:issue:(SB-\d{3}) -->', x.get('body') or '')}
        wanted = {i['id'] for i in self.plan['issues']}
        if not wanted <= verified:
            raise PublishError('일부 Issue의 게시 후 조회 검증에 실패했습니다.')
        self.checkpoint(f'구현 Issue {len(wanted)}개 조회 검증 완료')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner', default='jihoon22-lee')
    parser.add_argument('--visibility', choices=['private', 'public'], default='private',
                        help='새 저장소 공개 범위. 기존 저장소 공개 범위는 변경하지 않음.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='GitHub에 실제 생성/게시')
    mode.add_argument('--dry-run', action='store_true', help='로컬 검증과 계획 출력만 수행(기본값)')
    parser.add_argument('--adopt-empty', action='store_true', help='기존 빈 저장소 또는 README-only 저장소를 명시적으로 채택')
    parser.add_argument('--docs-only', action='store_true', help='문서만 게시하고 이슈/마일스톤은 건너뜀')
    args = parser.parse_args(argv)
    publisher = None
    try:
        files, manifest = load_bundle(ROOT)
        plan = json.loads(files['planning/backlog.json'])
        validate_plan(plan, files)
        if not args.apply:
            print(json.dumps({'mode': 'dry-run', 'network_calls': 0, 'target': f'{args.owner}/{REPO_NAME}',
                              'visibility': args.visibility, 'files': len(files),
                              'milestones': 0 if args.docs_only else len(plan['milestones']),
                              'issues': 0 if args.docs_only else len(plan['issues']),
                              'note': '생성/업로드되지 않았습니다. 실제 게시에는 인증된 gh와 --apply가 필요합니다.'},
                             ensure_ascii=False, indent=2))
            return 0
        publisher = Publisher(GhApi(), ROOT, files, manifest, plan,
                              Options(args.owner, args.visibility, args.adopt_empty, args.docs_only))
        report = publisher.publish()
        print(report['repository_url'])
        print('상세 결과: ' + str(ROOT / 'publish-report.json'))
        return 0
    except (PublishError, OSError, ValueError, KeyError) as exc:
        if publisher is not None:
            publisher.report['status'] = 'incomplete'
            publisher.report['error'] = str(exc)
            try:
                publisher.save_report()
            except OSError:
                pass
        print('게시 중단: ' + str(exc), file=sys.stderr)
        print('이미 완료된 원격 작업은 자동 삭제/롤백하지 않습니다. publish-report.json과 GitHub 상태를 확인하세요.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
