"""Build a debug APK with an explicitly selected JDK and SDK."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    sdk = Path(os.environ.get("ANDROID_HOME", str(Path.home() / "Android/Sdk")))
    if not (sdk / "platforms/android-36/android.jar").exists():
        raise SystemExit("Android SDK 36 required. Set ANDROID_HOME; see docs/development-environment.md.")
    if not os.environ.get("JAVA_HOME"):
        raise SystemExit("Set JAVA_HOME to the selected JDK 21 installation.")
    subprocess.run(
        ["./gradlew", "--no-daemon", "assembleDebug", "testDebugUnitTest"],
        cwd=ROOT / "apps/client/android",
        env={**os.environ, "ANDROID_HOME": str(sdk)},
        check=True,
    )
