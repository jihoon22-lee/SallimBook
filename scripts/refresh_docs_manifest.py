"""Explicitly refresh the reviewed documentation allowlist, never sweep the repo."""
import argparse
import json
from pathlib import Path

from publish_github import MANIFEST, git_sha, sha256, valid_path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--add', action='append', default=[], help='Reviewed documentation path to add')
    args = parser.parse_args()
    path = ROOT / MANIFEST
    manifest = json.loads(path.read_text(encoding='utf-8'))
    names = set(manifest['files']) | set(args.add)
    for name in sorted(names):
        candidate = ROOT / name
        if (not valid_path(name) or name == MANIFEST
                or any((ROOT / Path(*Path(name).parts[:n])).is_symlink()
                       for n in range(1, len(Path(name).parts) + 1))
                or not candidate.resolve().is_relative_to(ROOT)
                or any(part.startswith('.') for part in Path(name).parts) and name in args.add):
            raise SystemExit(f'Unsafe path: {name}')
        if name in args.add and not (name.endswith('.md') or name.startswith(('scripts/', 'tests/'))):
            raise SystemExit(f'Only reviewed documentation/tool paths may be added: {name}')
        data = candidate.read_bytes()
        data.decode('utf-8')
        if len(data) > 1_000_000:
            raise SystemExit(f'File exceeds documentation size limit: {name}')
        manifest['files'][name] = {'sha256': sha256(data), 'git_sha1': git_sha(data)}
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Refreshed {len(names)} explicitly listed documentation/tool files.')


if __name__ == '__main__':
    main()
