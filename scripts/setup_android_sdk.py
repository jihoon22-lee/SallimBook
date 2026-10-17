"""Install checksum-pinned Linux Android tools in a dedicated SDK directory."""
import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

TOOLS_BUILD = "15859902"
TOOLS_SHA256 = "4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583"
TOOLS_URL = f"https://dl.google.com/android/repository/commandlinetools-linux-{TOOLS_BUILD}_latest.zip"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sdk-root", type=Path,
        default=Path(os.environ.get("ANDROID_HOME", str(Path.home() / "Android/Sdk"))),
        help="SDK directory (default: ANDROID_HOME, then ~/Android/Sdk)",
    )
    parser.add_argument("--accept-licenses", action="store_true", help="Accept SDK licenses explicitly")
    args = parser.parse_args()
    if not os.environ.get("JAVA_HOME"):
        raise SystemExit("Set JAVA_HOME to JDK 21 before installing the SDK.")
    destination = args.sdk_root / "cmdline-tools" / TOOLS_BUILD
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix="sallimbook-sdk-") as temporary:
            archive = Path(temporary) / "tools.zip"
            urllib.request.urlretrieve(TOOLS_URL, archive)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != TOOLS_SHA256:
                raise SystemExit("SDK archive checksum mismatch; no installation performed.")
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(temporary)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(Path(temporary) / "cmdline-tools"), destination)
            for executable in (destination / "bin").iterdir():
                executable.chmod(0o755)
    subprocess.run(
        [str(destination / "bin/sdkmanager"), f"--sdk_root={args.sdk_root}",
         "platform-tools", "platforms;android-36", "build-tools;36.0.0"],
        input="y\n" * 100 if args.accept_licenses else None,
        text=True,
        check=True,
    )


if __name__ == "__main__":
    main()
