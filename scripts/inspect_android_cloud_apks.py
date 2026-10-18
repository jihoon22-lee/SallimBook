"""Record APK hashes/identity/public signing fingerprints and release isolation.

This inspects bytes, not installed app behavior or hardware security. The normal
release is unsigned. Run once for normal outputs and once after the opt-in debug
fixture build (whose release is still built with an empty API origin).
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    b"sallimbook_cloud_", b"AndroidCloudOnboardingTest", b"CvcAcceptanceActivity",
    b"SecurityProofActivity", b"debugproof/",
)


def inspect_release(apk):
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        matches = []
        for name in names:
            content = archive.read(name)
            for marker in FORBIDDEN:
                if marker in content or marker.decode().encode("utf-16-le") in content:
                    matches.append({"entry": name, "marker": marker.decode()})
            if re.search(rb"https://127\.0\.0\.1:[0-9]+", content):
                matches.append({"entry": name, "marker": "loopback HTTPS test origin"})
    return {
        "status": "FAIL" if matches else "PASS", "entries_scanned": len(names),
        "dex_files": [name for name in names if name.endswith(".dex")],
        "markers": [marker.decode() for marker in FORBIDDEN], "matches": matches,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sdk = Path(os.environ["ANDROID_HOME"]) / "build-tools/36.0.0"
    directory = ROOT / "apps/client/android/app/build/outputs/apk"
    results = []
    for relative in ("debug/app-debug.apk", "androidTest/debug/app-debug-androidTest.apk",
                     "release/app-release-unsigned.apk"):
        apk = directory / relative
        badging = subprocess.check_output([str(sdk / "aapt"), "dump", "badging", str(apk)], text=True)
        signing = subprocess.run([str(sdk / "apksigner"), "verify", "--print-certs", str(apk)],
                                 capture_output=True, text=True, check=False)
        result = {
            "path": relative, "sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
            "metadata": [line for line in badging.splitlines()
                         if line.startswith(("package:", "sdkVersion:", "targetSdkVersion:"))],
            "signature_verified": signing.returncode == 0,
            "public_certificate_sha256": [line for line in signing.stdout.splitlines()
                                           if "certificate SHA-256 digest:" in line],
        }
        if relative.startswith("release/"):
            result["isolation"] = inspect_release(apk)
        results.append(result)
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    if any(result.get("isolation", {}).get("status") == "FAIL" for result in results):
        raise SystemExit("FAIL: cloud/debug markers found in release APK")
    if not all(result["signature_verified"] for result in results[:2]):
        raise SystemExit("FAIL: debug/test signing verification")
    print("PASS: APK inventory, debug/test signatures and release marker isolation (not device acceptance)")


if __name__ == "__main__":
    main()
