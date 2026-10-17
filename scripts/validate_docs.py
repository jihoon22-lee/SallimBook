#!/usr/bin/env python3
"""Validate local documentation and planning. Does not test an implemented app."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from publish_github import MANIFEST, PublishError, load_bundle, validate_plan

ROOT = Path(__file__).resolve().parents[1]

IGNORED_DIRECTORIES = {
    '.git', '.venv', 'node_modules', 'dist', 'build', '.gradle', '.kotlin',
    '__pycache__', '.pytest_cache', '.ruff_cache', '.cache', '.pnpm-store',
    'coverage', 'playwright-report', 'test-results', 'private', 'private-data',
    'secrets', 'attachments', 'uploads', 'backups',
}


def project_files(root: Path) -> list[Path]:
    """Include new project documents, but never walk dependency/output trees."""
    try:
        top = subprocess.run(
            ['git', '-C', str(root), 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if Path(top).resolve() == root.resolve():
            result = subprocess.run(
                ['git', '-C', str(root), 'ls-files', '--cached', '--others',
                 '--exclude-standard', '-z'], capture_output=True, check=True,
            )
            candidates = {root / os.fsdecode(name) for name in result.stdout.split(b'\0') if name}
            return sorted(p for p in candidates if p.is_file() and not p.is_symlink()
                          and not (set(p.relative_to(root).parts) & IGNORED_DIRECTORIES))
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass  # A downloaded documentation bundle need not be a Git checkout.
    result = []
    for parent, directories, names in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories
                          if name not in IGNORED_DIRECTORIES
                          and not (Path(parent) / name).is_symlink()]
        result.extend(Path(parent) / name for name in names
                      if not (Path(parent) / name).is_symlink())
    return sorted(result)


def strip_fences(text: str) -> str:
    result = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if match:
            char = match.group(1)[0]
            if fence is None:
                fence = char
            elif fence == char:
                fence = None
            continue
        if fence is None:
            result.append(line)
    return '\n'.join(result)


def local_link_errors(root: Path, paths: list[Path]) -> tuple[list[str], int]:
    errors = []
    count = 0
    for path in paths:
        text = path.read_text(encoding='utf-8')
        if '\ue200' in text or '\ue201' in text or re.search(r'turn\d+(?:search|view|file)\d+', text):
            errors.append(f'{path.relative_to(root)}: unresolved tool citation')
        content = strip_fences(text)
        for target in re.findall(r'!?\[[^\]\n]*\]\(([^)\n]+)\)', content):
            target = target.strip().split(' "', 1)[0].strip('<>')
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            count += 1
            destination = (path.parent / unquote(parsed.path)).resolve()
            if not destination.is_relative_to(root.resolve()) or not destination.is_file():
                errors.append(f'{path.relative_to(root)}: broken/unsafe local link: {target}')
    return errors, count


def check(root: Path) -> dict:
    maintained = project_files(root)
    paths = [p for p in maintained if p.suffix == '.md']
    errors, links = local_link_errors(root, paths)
    if (root / MANIFEST).exists():
        files, _ = load_bundle(root)
        manifest_checked = True
    else:
        files = {str(p.relative_to(root)): b'' for p in maintained}
        manifest_checked = False
    plan = json.loads((root / 'planning/backlog.json').read_text(encoding='utf-8'))
    validate_plan(plan, files)
    req_text = (root / 'docs/product-requirements.md').read_text(encoding='utf-8')
    reqs = set(re.findall(r'^\| (R-\d{2}) \|', req_text, re.M))
    referenced = {r for issue in plan['issues'] for r in issue['requirements']}
    if referenced != reqs:
        errors.append(f'requirements coverage mismatch: missing={reqs - referenced}, unknown={referenced - reqs}')
    if len(plan['milestones']) != 9 or len(plan['issues']) != 40 or len(reqs) != 22:
        errors.append('initial design baseline differs from 9 milestones / 40 issues / 22 requirements')
    if errors:
        raise PublishError('\n'.join(errors))
    return {'markdown_files': len(paths), 'local_links_checked': links, 'requirements': len(reqs),
            'milestones': len(plan['milestones']), 'issues': len(plan['issues']),
            'manifest_hashes_checked': manifest_checked,
            'scope': 'local documentation and publishing plan only; not app/security/GitHub live validation'}


def main() -> int:
    try:
        print(json.dumps(check(ROOT), ensure_ascii=False, indent=2))
        return 0
    except (PublishError, OSError, ValueError, KeyError) as exc:
        print('문서 검증 실패: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
