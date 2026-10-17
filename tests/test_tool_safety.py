"""Filesystem safety checks without downloads or actual Android SDK commands."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import refresh_docs_manifest as refresh
import setup_android_sdk as sdk


class ManifestSafetyTests(unittest.TestCase):
    def test_refresh_rejects_manifest_symlink_without_changing_external_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "checkout"
            root.mkdir()
            (root / "README.md").write_text("# Synthetic documentation\n", encoding="utf-8")
            target = Path(temporary) / "external-manifest.json"
            sentinel = json.dumps({"files": {"README.md": {}}}).encode("utf-8")
            target.write_bytes(sentinel)
            manifest = root / refresh.MANIFEST
            manifest.symlink_to(target)

            with patch.object(refresh, "ROOT", root), patch.object(
                sys, "argv", ["refresh_docs_manifest.py"]
            ):
                with self.assertRaisesRegex(SystemExit, "manifest.*symlink"):
                    refresh.main()

            self.assertEqual(target.read_bytes(), sentinel)
            self.assertTrue(manifest.is_symlink())


class AndroidSdkSelectionTests(unittest.TestCase):
    def check_selection(self, explicit_override: bool):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment_sdk = root / "environment-sdk"
            explicit_sdk = root / "explicit-sdk"
            selected = explicit_sdk if explicit_override else environment_sdk
            tools = selected / "cmdline-tools" / sdk.TOOLS_BUILD
            tools.mkdir(parents=True)
            arguments = ["setup_android_sdk.py"]
            if explicit_override:
                arguments += ["--sdk-root", str(explicit_sdk)]

            with (
                patch.dict(os.environ, {
                    "JAVA_HOME": str(root / "synthetic-jdk"),
                    "ANDROID_HOME": str(environment_sdk),
                }, clear=True),
                patch.object(Path, "home", return_value=root / "home"),
                patch.object(sys, "argv", arguments),
                patch.object(sdk.urllib.request, "urlretrieve",
                             side_effect=AssertionError("Downloads are forbidden")) as download,
                patch.object(sdk.subprocess, "run") as run,
            ):
                sdk.main()

            download.assert_not_called()
            run.assert_called_once_with(
                [str(tools / "bin/sdkmanager"), f"--sdk_root={selected}",
                 "platform-tools", "platforms;android-36", "build-tools;36.0.0"],
                input=None,
                text=True,
                check=True,
            )
            self.assertFalse((root / "home").exists())

    def test_android_home_selects_default_sdk(self):
        self.check_selection(explicit_override=False)

    def test_explicit_sdk_root_overrides_android_home(self):
        self.check_selection(explicit_override=True)


if __name__ == "__main__":
    unittest.main()
