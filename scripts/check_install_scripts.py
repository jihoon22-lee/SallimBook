"""Compare what `pnpm install --ignore-scripts` skips with what the build runs explicitly.

The release and image builds install without lifecycle scripts. pnpm 9 lockfiles do not
record which dependencies have such scripts, so this reads the installed tree: a
dependency with a preinstall/install/postinstall script, or a binding.gyp (which makes
pnpm build it implicitly), must be listed in ops.build_context.INSTALL_SCRIPT_PACKAGES and
run by an explicit build step. Workspace projects' own lifecycle scripts are reported too.
Run it after `pnpm install`.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_SCRIPTS = ("preinstall", "install", "postinstall")
WORKSPACE_SCRIPTS = (*DEPENDENCY_SCRIPTS, "prepare", "prepublish")


def manifest(directory):
    try:
        value = json.loads((directory / "package.json").read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def dependencies_needing_scripts(node_modules):
    store = Path(node_modules) / ".pnpm"
    found = set()
    for entry in sorted(store.iterdir()):
        modules = entry / "node_modules"
        if not modules.is_dir():
            continue
        for child in sorted(modules.iterdir()):
            # A store entry holds the package itself as a real directory and its
            # dependencies as links; scoped names add one directory level.
            candidates = sorted(child.iterdir()) if child.name.startswith("@") else [child]
            for package in candidates:
                if package.is_symlink() or not package.is_dir():
                    continue
                value = manifest(package)
                if value is None:
                    continue
                scripts = value.get("scripts") if isinstance(value.get("scripts"), dict) else {}
                if any(name in scripts for name in DEPENDENCY_SCRIPTS) or (
                    package / "binding.gyp"
                ).is_file():
                    found.add(f"{value.get('name', package.name)}@{value.get('version', '?')}")
    return found


def workspace_projects_with_scripts(root):
    root = Path(root)
    patterns = []
    workspace = root / "pnpm-workspace.yaml"
    if workspace.is_file():
        patterns = [
            line.split("-", 1)[1].strip().strip("'\"")
            for line in workspace.read_text().splitlines()
            if line.strip().startswith("- ")
        ]
    directories = [root]
    for pattern in patterns:
        directories += [path for path in sorted(root.glob(pattern)) if path.is_dir()]
    found = set()
    for directory in directories:
        value = manifest(directory)
        scripts = (value or {}).get("scripts")
        if isinstance(scripts, dict) and any(name in scripts for name in WORKSPACE_SCRIPTS):
            found.add(value.get("name", directory.name))
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if not (args.root / "node_modules/.pnpm").is_dir():
        print("No installed dependency tree; run pnpm install first.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(ROOT))
    from ops import build_context

    dependencies = dependencies_needing_scripts(args.root / "node_modules")
    workspace = workspace_projects_with_scripts(args.root)
    allowed = set(build_context.INSTALL_SCRIPT_PACKAGES)
    print(
        json.dumps(
            {
                "dependencies": sorted(dependencies),
                "workspace": sorted(workspace),
                "allowed": sorted(allowed),
            },
            sort_keys=True,
        )
    )
    return 0 if dependencies == allowed and not workspace else 1


if __name__ == "__main__":
    sys.exit(main())
