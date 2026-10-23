"""The installed-tree scan behind `pnpm install --ignore-scripts`; synthetic trees only."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ops import build_context
from scripts import check_install_scripts as scan


def package(store, name, version, manifest=None, files=()):
    """A dependency the way pnpm lays it out: the real directory sits in its own store entry."""
    entry = store / f"{name.replace('/', '+')}@{version}" / "node_modules" / name
    entry.mkdir(parents=True)
    (entry / "package.json").write_text(
        json.dumps({"name": name, "version": version, **(manifest or {})})
    )
    for file in files:
        (entry / file).write_text("")
    return entry


class InstallScriptScan(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = self.root / "node_modules/.pnpm"
        self.store.mkdir(parents=True)

    def test_lifecycle_scripts_and_native_build_files_are_found(self):
        package(self.store, "plain", "1.0.0", {"scripts": {"build": "tsc", "test": "x"}})
        package(self.store, "esbuild", "0.25.0", {"scripts": {"postinstall": "node install.js"}})
        package(self.store, "@scope/native", "2.1.0", files=["binding.gyp"])
        package(self.store, "legacy", "0.1.0", {"scripts": {"preinstall": "x"}})
        package(self.store, "builder", "3.0.0", {"scripts": {"install": "node-gyp rebuild"}})
        self.assertEqual(
            scan.dependencies_needing_scripts(self.root / "node_modules"),
            {"esbuild@0.25.0", "@scope/native@2.1.0", "legacy@0.1.0", "builder@3.0.0"},
        )

    def test_linked_dependencies_are_not_mistaken_for_the_package_itself(self):
        owner = package(self.store, "owner", "1.0.0")
        needy = package(self.store, "needy", "1.0.0", {"scripts": {"postinstall": "x"}})
        # pnpm links a package's dependencies next to it; the link is not a second copy.
        (owner.parent / "needy").symlink_to(needy)
        self.assertEqual(
            scan.dependencies_needing_scripts(self.root / "node_modules"), {"needy@1.0.0"}
        )

    def test_workspace_projects_with_lifecycle_scripts_are_found(self):
        (self.root / "pnpm-workspace.yaml").write_text("packages:\n  - apps/*\n  - packages/*\n")
        (self.root / "package.json").write_text(json.dumps({"name": "root", "scripts": {}}))
        for name, scripts in (("apps/web", {"build": "x"}), ("packages/lib", {"prepare": "x"})):
            directory = self.root / name
            directory.mkdir(parents=True)
            (directory / "package.json").write_text(
                json.dumps({"name": name.split("/")[1], "scripts": scripts})
            )
        self.assertEqual(scan.workspace_projects_with_scripts(self.root), {"lib"})

    def run_main(self, *arguments):
        output = io.StringIO()
        with redirect_stdout(output), patch("sys.stderr", io.StringIO()):
            code = scan.main(["--root", str(self.root), *arguments])
        return code, output.getvalue()

    def test_command_fails_unless_the_found_packages_are_exactly_the_listed_ones(self):
        (self.root / "pnpm-workspace.yaml").write_text("packages:\n  - apps/*\n")
        (self.root / "package.json").write_text(json.dumps({"name": "root"}))
        package(self.store, "plain", "1.0.0")
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["dependencies"], [])
        package(self.store, "esbuild", "0.25.0", {"scripts": {"postinstall": "x"}})
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["dependencies"], ["esbuild@0.25.0"])
        # Listing it is a deliberate decision: the build then has to run its script itself.
        with patch.object(build_context, "INSTALL_SCRIPT_PACKAGES", ("esbuild@0.25.0",)):
            code, _ = self.run_main()
        self.assertEqual(code, 0)
        # A listed package that is gone no longer justifies an explicit step.
        with patch.object(build_context, "INSTALL_SCRIPT_PACKAGES", ("esbuild@0.25.0", "gone@1")):
            code, _ = self.run_main()
        self.assertEqual(code, 1)

    def test_a_missing_install_is_an_error_not_a_pass(self):
        (self.root / "node_modules/.pnpm").rmdir()
        code, output = self.run_main()
        self.assertEqual(code, 2)
        self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
