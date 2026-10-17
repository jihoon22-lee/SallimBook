"""Build/inspect/sign a release using existing external keys; never installs or uploads."""

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from ops.backup import OperationError, digest, private_directory, private_file
from ops.build_context import build_environment, source_snapshot
from ops.deploy import APP_ID, validate

ROOT = Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, check=False, **kwargs)
    if result.returncode:
        # Build/signing failures may contain local secret paths or passwords in
        # third-party diagnostics. Never echo their stdout/stderr automatically.
        raise OperationError(
            "Release tool failed; inspect locally without publishing sensitive output"
        )
    return result.stdout.decode().strip()


def tools(sdk):
    sdk = Path(sdk)
    build = sdk / "build-tools/36.0.0"
    # Same immutable Google package selected by scripts/setup_android_sdk.py.
    analyzer = sdk / "cmdline-tools/15859902/bin/apkanalyzer"
    paths = {
        "apksigner": build / "apksigner",
        "zipalign": build / "zipalign",
        "apkanalyzer": analyzer,
    }
    if any(not path.is_file() for path in paths.values()):
        raise OperationError("Repository Android SDK/build-tools 36.0.0 required")
    return paths


def inspect_apk(apk, config, sdk, *, signed):
    config = validate(config)
    binaries = tools(sdk)

    def analyze(*args):
        return run([str(binaries["apkanalyzer"]), *args, str(apk)])

    if analyze("manifest", "application-id") != APP_ID:
        raise OperationError("Release application ID mismatch")
    if analyze("manifest", "debuggable") != "false":
        raise OperationError("Debuggable APK is forbidden")
    if analyze("manifest", "version-code") != str(config["version_code"]):
        raise OperationError("APK version code mismatch")
    if analyze("manifest", "version-name") != config["version_name"]:
        raise OperationError("APK version name mismatch")
    manifest = analyze("manifest", "print")
    if (
        'android:allowBackup="false"' not in manifest
        or 'android:usesCleartextTraffic="false"' not in manifest
        or "debugproof" in manifest
    ):
        raise OperationError("Release manifest security configuration failed")
    with zipfile.ZipFile(apk) as archive:
        config_json = json.loads(archive.read("assets/capacitor.config.json"))
        server = config_json.get("server", {})
        android = config_json.get("android", {})
        if (
            server.get("url") is not None
            or server.get("allowNavigation") not in (None, [])
            or server.get("cleartext") is True
            or android.get("allowMixedContent") is True
        ):
            raise OperationError(
                "Remote WebView or cleartext configuration is forbidden"
            )
        dex = b"".join(
            archive.read(name)
            for name in archive.namelist()
            if re.fullmatch(r"classes[0-9]*\.dex", name)
        )
        expected = [
            "https://" + config["fqdn"] + ":8443",
            config["fqdn"],
            config["certificate_sha256"],
        ]
        if (
            any(value.encode() not in dex for value in expected)
            or b"debugproof" in dex
            or b"SecurityProofActivity" in dex
        ):
            raise OperationError(
                "Native release identity or proof-class exclusion failed"
            )
    if signed:
        report = run(
            [
                str(binaries["apksigner"]),
                "verify",
                "--verbose",
                "--print-certs",
                str(apk),
            ]
        )
        fingerprints = re.findall(
            r"Signer #[0-9]+ certificate SHA-256 digest: ([0-9a-fA-F]+)", report
        )
        wanted = config["certificate_sha256"].replace(":", "").lower()
        if fingerprints != [wanted]:
            raise OperationError("APK signing certificate mismatch")
        run([str(binaries["zipalign"]), "-c", "-P", "16", "-v", "4", str(apk)])
    return {
        "application_id": APP_ID,
        "version_code": config["version_code"],
        "version_name": config["version_name"],
        "sha256": digest(Path(apk)),
        "signed": signed,
        "source_commit": config["source_commit"],
    }


def build(
    config,
    sdk,
    keystore,
    store_password_file,
    key_password_file,
    alias,
    output,
    previous_version,
    previous_apk=None,
):
    config = validate(config)
    if type(previous_version) is not int or config["version_code"] <= previous_version:
        raise OperationError(
            "versionCode must increase over the previously distributed release"
        )
    if previous_version < 0:
        raise OperationError("Invalid previous version code")
    if previous_version > 0:
        if previous_apk is None:
            raise OperationError(
                "The previously distributed signed APK is required for an update"
            )
        binaries = tools(sdk)
        old_name = run(
            [
                str(binaries["apkanalyzer"]),
                "manifest",
                "version-name",
                str(previous_apk),
            ]
        )
        inspect_apk(
            previous_apk,
            {**config, "version_code": previous_version, "version_name": old_name},
            sdk,
            signed=True,
        )
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", alias):
        raise OperationError("Invalid signing alias")
    for path in (keystore, store_password_file, key_password_file):
        secret = private_file(path)
        if secret.is_relative_to(ROOT):
            raise OperationError("Signing material must be outside the repository")
    output = Path(output).absolute()
    private_directory(output.parent)
    if output.exists() or output.is_relative_to(ROOT):
        raise OperationError(
            "Use a new APK path in an external private release directory"
        )
    if run(["git", "status", "--porcelain"], cwd=ROOT):
        raise OperationError("Build requires a clean reviewed source tree")
    if run(["git", "rev-parse", "HEAD"], cwd=ROOT) != config["source_commit"]:
        raise OperationError("Build commit does not match deployment manifest")
    with source_snapshot(config["source_commit"], output.parent) as checkout:
        return build_snapshot(
            config,
            sdk,
            keystore,
            store_password_file,
            key_password_file,
            alias,
            output,
            checkout,
        )


def build_snapshot(
    config,
    sdk,
    keystore,
    store_password_file,
    key_password_file,
    alias,
    output,
    checkout,
):
    binaries = tools(sdk)
    env = {**build_environment(), "ANDROID_HOME": str(Path(sdk).absolute())}
    if not env.get("JAVA_HOME"):
        raise OperationError("Set JAVA_HOME to the selected JDK 21")
    run(["pnpm", "install", "--frozen-lockfile"], cwd=checkout, env=env)
    run(["pnpm", "android:sync"], cwd=checkout, env=env)
    properties = {
        "sallimbookApiOrigin": "https://" + config["fqdn"] + ":8443",
        "sallimbookPasskeyRpId": config["fqdn"],
        "sallimbookPasskeyCertSha256": config["certificate_sha256"],
        "sallimbookReleaseVersionCode": str(config["version_code"]),
        "sallimbookReleaseVersionName": config["version_name"],
    }
    # These properties are public application identity; no signing password is
    # passed to Gradle, environment variables, command arguments, or a build cache.
    run(
        [
            "./gradlew",
            "--no-daemon",
            "--no-configuration-cache",
            "--max-workers=2",
            "-I",
            str(checkout / "ops/release.init.gradle"),
            *["-P" + key + "=" + value for key, value in properties.items()],
            "assembleRelease",
            "testReleaseUnitTest",
        ],
        cwd=checkout / "apps/client/android",
        env=env,
    )
    apk = (
        checkout
        / "apps/client/android/app/build/outputs/apk/release/app-release-unsigned.apk"
    )
    inspect_apk(apk, config, sdk, signed=False)
    with tempfile.TemporaryDirectory(
        prefix=".sallimbook-release-", dir=output.parent
    ) as temporary:
        aligned = Path(temporary) / "aligned.apk"
        signed = Path(temporary) / "signed.apk"
        run([str(binaries["zipalign"]), "-P", "16", "-v", "4", str(apk), str(aligned)])
        run(
            [
                str(binaries["apksigner"]),
                "sign",
                "--ks",
                str(Path(keystore).absolute()),
                "--ks-key-alias",
                alias,
                "--ks-pass",
                "file:" + str(Path(store_password_file).absolute()),
                "--key-pass",
                "file:" + str(Path(key_password_file).absolute()),
                "--out",
                str(signed),
                str(aligned),
            ]
        )
        result = inspect_apk(signed, config, sdk, signed=True)
        with output.open("xb") as stream, signed.open("rb") as source:
            os.chmod(output, 0o600)
            shutil.copyfileobj(source, stream)
            stream.flush()
            os.fsync(stream.fileno())
    with output.with_suffix(".receipt.json").open("x") as stream:
        os.chmod(stream.name, 0o600)
        json.dump(result, stream, sort_keys=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--keystore", type=Path, required=True)
    parser.add_argument("--store-password-file", type=Path, required=True)
    parser.add_argument("--key-password-file", type=Path, required=True)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous-version", type=int, required=True)
    parser.add_argument(
        "--previous-apk",
        type=Path,
        help="Required when previous-version is greater than zero",
    )
    args = vars(parser.parse_args())
    args["config"] = json.loads(args.pop("manifest").read_text())
    try:
        result = build(**args)
    except Exception:
        raise SystemExit(
            "Release preparation failed. Nothing installed or published."
        ) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
