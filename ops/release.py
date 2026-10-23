"""Build/inspect/sign a release using existing external keys; never installs or uploads."""

import argparse
import contextlib
import ctypes
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from ops.backup import OperationError, digest, private_directory, private_file
from ops.build_context import PNPM_INSTALL, build_environment, source_snapshot
from ops.deploy import APP_ID, validate

ROOT = Path(__file__).resolve().parents[1]
DEBUG_PROOF_MARKERS = (
    b"debugproof",
    b"SecurityProofActivity",
    b"CvcAcceptanceActivity",
    b"CvcAcceptanceFixtures",
    b"NativeVaultAcceptanceGate$Owner",
    b"SALLIMBOOK DEBUG CVC ACCEPTANCE V1",
    b"beginSyntheticCvcAcceptance",
    b"armSyntheticCvcWriteFailure",
    b"NativeVaultCvcAcceptanceTest",
)


# prctl(2) option that makes every orphaned descendant a child of this process.
PR_SET_CHILD_SUBREAPER = 36
# Time for the killed leftovers of a build command to be reaped before they count as left.
LEFTOVER_SETTLE_SECONDS = 5
# The pinned SDK packages whose files take part in aligning, signing and inspecting.
SIGNING_TOOL_DIRECTORIES = ("build-tools/36.0.0", "cmdline-tools/15859902")


class ReleaseAbort(OperationError):
    """A refusal with a fixed code that is safe to show; the message stays private."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, check=False, **kwargs)
    if result.returncode:
        # Build/signing failures may contain local secret paths or passwords in
        # third-party diagnostics. Never echo their stdout/stderr automatically.
        raise OperationError(
            "Release tool failed; inspect locally without publishing sensitive output"
        )
    return result.stdout.decode().strip()


def containment_unavailable():
    return ReleaseAbort(
        "BUILD_CONTAINMENT_UNAVAILABLE",
        "Processes left by build commands could not be collected on this host",
    )


def child_processes():
    """Ids of this process's children, live or exited but not yet reaped, from /proc."""
    me = os.getpid()
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:  # The process went away meanwhile.
            continue
        # The command name may hold spaces or parentheses; the fields after the last ")" do not.
        if int(stat.rsplit(")", 1)[1].split()[1]) == me:
            found.append(int(entry.name))
    return found


def reap_leftovers():
    """Kill and reap everything a finished build command left behind; prove none is left.

    This process is the subreaper (see check_containment), so a descendant whose parent
    exits, including one that detached with setsid or a double fork, becomes its child.
    """
    deadline = time.monotonic() + LEFTOVER_SETTLE_SECONDS
    while children := child_processes():
        for pid in children:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        for pid in children:
            with contextlib.suppress(ChildProcessError):
                os.waitpid(pid, os.WNOHANG)
        if time.monotonic() >= deadline:
            raise ReleaseAbort(
                "BUILD_PROCESS_LEFT_RUNNING",
                "A process started by the build is still running after it was killed",
            )
        time.sleep(0.05)


def check_containment():
    """Collect orphans from here on, and prove it works before a long build; no fallback."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
            raise containment_unavailable()
    except (OSError, AttributeError) as error:
        raise containment_unavailable() from error
    if child_processes():
        raise containment_unavailable()
    # A detached process like a build daemon must come back as this process's child.
    probe = subprocess.Popen(
        ["/bin/sh", "-c", "/usr/bin/setsid /bin/sleep 30 </dev/null >/dev/null 2>&1 &"],
        cwd="/",
        env={"PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if probe.wait():
            raise containment_unavailable()
        if not [pid for pid in child_processes() if pid != probe.pid]:
            raise containment_unavailable()
    finally:
        reap_leftovers()


def run_build(command, *, cwd, env):
    """Run one build command with exactly `env`; nothing it started may outlive it.

    Third-party build code runs as this user. Whatever it leaves running (a Gradle or Kotlin
    daemon, a background script) is killed before the next step, so no survivor can change
    the build output or the signing tools after their check. This is not secrecy: while the
    build runs, its code can read anything this user can, signing files included; see the
    runbook.
    """
    try:
        process = subprocess.Popen(
            [str(item) for item in command],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise OperationError(
            "Release tool failed; inspect locally without publishing sensitive output"
        ) from error
    try:
        status = process.wait()
    finally:
        # An interrupted wait leaves the command itself running; it is a child too.
        reap_leftovers()
    if status:
        # Build output may contain local paths or secrets; never echo it.
        raise OperationError(
            "Release tool failed; inspect locally without publishing sensitive output"
        )


def fingerprint(*roots):
    """Mode and SHA-256 of every file under the roots; links by target. Any change differs."""
    result = {}
    for root in roots:
        for directory, names, files in os.walk(root, followlinks=False):
            for name in (*names, *files):
                path = Path(directory) / name
                info = path.lstat()
                mode = format(info.st_mode & 0o7777, "o")
                if path.is_symlink():
                    result[str(path)] = f"link:{mode}:{os.readlink(path)}"
                elif path.is_file():
                    result[str(path)] = f"file:{mode}:{digest(path)}"
                else:
                    result[str(path)] = f"dir:{mode}"
    return result


def signing_fingerprints(sdk, jdk):
    """Everything the align/sign/inspect commands execute or load: SDK tools and the JDK."""
    return fingerprint(*(Path(sdk) / name for name in SIGNING_TOOL_DIRECTORIES), jdk)


def signing_jdk(java_home):
    jdk = Path(java_home).resolve(strict=True)
    if not (jdk / "bin/java").is_file() or not (jdk / "lib/modules").is_file():
        raise OperationError("Set JAVA_HOME to the selected JDK 21")
    return jdk


def signing_environment(jdk):
    """Only the verified JDK and system tools; no inherited JAVA_TOOL_OPTIONS or CLASSPATH."""
    return {"JAVA_HOME": str(jdk), "PATH": str(jdk / "bin") + ":/usr/bin:/bin", "LANG": "C.UTF-8"}


def tools(sdk):
    sdk = Path(sdk)
    build = sdk / SIGNING_TOOL_DIRECTORIES[0]
    # Same immutable Google package selected by scripts/setup_android_sdk.py.
    analyzer = sdk / SIGNING_TOOL_DIRECTORIES[1] / "bin/apkanalyzer"
    paths = {
        "apksigner": build / "apksigner",
        "zipalign": build / "zipalign",
        "apkanalyzer": analyzer,
    }
    if any(not path.is_file() for path in paths.values()):
        raise OperationError("Repository Android SDK/build-tools 36.0.0 required")
    return paths


def inspect_apk(apk, config, sdk, *, signed, env=None):
    config = validate(config)
    binaries = tools(sdk)

    def analyze(*args):
        return run([str(binaries["apkanalyzer"]), *args, str(apk)], env=env)

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
            raise OperationError("Remote WebView or cleartext configuration is forbidden")
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
        if any(value.encode() not in dex for value in expected) or any(
            marker in dex for marker in DEBUG_PROOF_MARKERS
        ):
            raise OperationError("Native release identity or proof-class exclusion failed")
    if signed:
        report = run(
            [
                str(binaries["apksigner"]),
                "verify",
                "--verbose",
                "--print-certs",
                str(apk),
            ],
            env=env,
        )
        fingerprints = re.findall(
            r"Signer #[0-9]+ certificate SHA-256 digest: ([0-9a-fA-F]+)", report
        )
        wanted = config["certificate_sha256"].replace(":", "").lower()
        if fingerprints != [wanted]:
            raise OperationError("APK signing certificate mismatch")
        run([str(binaries["zipalign"]), "-c", "-P", "16", "-v", "4", str(apk)], env=env)
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
        raise OperationError("versionCode must increase over the previously distributed release")
    if previous_version < 0:
        raise OperationError("Invalid previous version code")
    if previous_version > 0:
        if previous_apk is None:
            raise OperationError("The previously distributed signed APK is required for an update")
        binaries = tools(sdk)
        if not os.environ.get("JAVA_HOME"):
            raise OperationError("Set JAVA_HOME to the selected JDK 21")
        # The same fixed environment as signing: no inherited Java options reach the tools.
        inspection = signing_environment(signing_jdk(os.environ["JAVA_HOME"]))
        old_name = run(
            [
                str(binaries["apkanalyzer"]),
                "manifest",
                "version-name",
                str(previous_apk),
            ],
            env=inspection,
        )
        inspect_apk(
            previous_apk,
            {**config, "version_code": previous_version, "version_name": old_name},
            sdk,
            signed=True,
            env=inspection,
        )
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", alias):
        raise OperationError("Invalid signing alias")
    if Path(store_password_file).absolute() == Path(key_password_file).absolute():
        raise OperationError(
            "Use separate store/key password files; apksigner consumes each source sequentially"
        )
    for path in (keystore, store_password_file, key_password_file):
        secret = private_file(path)
        if secret.is_relative_to(ROOT):
            raise OperationError("Signing material must be outside the repository")
    output = Path(output).absolute()
    private_directory(output.parent)
    if output.exists() or output.is_relative_to(ROOT):
        raise OperationError("Use a new APK path in an external private release directory")
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
    tools(sdk)  # Fail before a long build when the SDK is incomplete.
    env = {**build_environment(), "ANDROID_HOME": str(Path(sdk).absolute())}
    if not env.get("JAVA_HOME"):
        raise OperationError("Set JAVA_HOME to the selected JDK 21")
    jdk = signing_jdk(env["JAVA_HOME"])
    check_containment()
    # Third-party build code runs as this user and could rewrite the tools that later
    # see the signing key. Pin them now and compare right before they are used.
    pinned = signing_fingerprints(sdk, jdk)
    output = Path(output)
    # Step 1 has no access to signing material, and every process left by each build
    # command was killed and reaped (or the release aborted) before anything below exists.
    unsigned = build_unsigned(config, checkout, env)
    # The private directory is created only now, so build code never saw it. The unsigned
    # APK is copied into it at once; only the copy is inspected and signed.
    with tempfile.TemporaryDirectory(prefix=".sallimbook-release-", dir=output.parent) as temporary:
        candidate = Path(temporary) / "unsigned.apk"
        copy_private(unsigned, candidate)
        if signing_fingerprints(sdk, jdk) != pinned:
            raise ReleaseAbort(
                "SIGNING_TOOLS_CHANGED",
                "A signing tool or the JDK changed while the build ran",
            )
        return sign_release(
            config,
            sdk,
            candidate,
            keystore,
            store_password_file,
            key_password_file,
            alias,
            output,
            signing_environment(jdk),
        )


def copy_private(source, destination):
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        raise OperationError("The build did not produce a regular unsigned APK")
    with source.open("rb") as stream:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            shutil.copyfileobj(stream, target)
            target.flush()
            os.fsync(target.fileno())


def build_unsigned(config, checkout, env):
    checkout = Path(checkout)
    # Dependency install scripts are skipped; the lockfile records none that are needed
    # (see build_context.INSTALL_SCRIPT_PACKAGES). Only the project's own scripts run.
    run_build(PNPM_INSTALL, cwd=checkout, env=env)
    run_build(["pnpm", "android:sync"], cwd=checkout, env=env)
    properties = {
        "sallimbookApiOrigin": "https://" + config["fqdn"] + ":8443",
        "sallimbookPasskeyRpId": config["fqdn"],
        "sallimbookPasskeyCertSha256": config["certificate_sha256"],
        "sallimbookReleaseVersionCode": str(config["version_code"]),
        "sallimbookReleaseVersionName": config["version_name"],
    }
    # These properties are public application identity; no signing password is
    # passed to Gradle, environment variables, command arguments, or a build cache.
    run_build(
        [
            "./gradlew",
            "--no-daemon",
            "--no-configuration-cache",
            "--max-workers=2",
            # Compile Kotlin inside the build, so no Kotlin daemon outlives it.
            "-Pkotlin.compiler.execution.strategy=in-process",
            "-I",
            str(checkout / "ops/release.init.gradle"),
            *["-P" + key + "=" + value for key, value in properties.items()],
            "assembleRelease",
            "testReleaseUnitTest",
        ],
        cwd=checkout / "apps/client/android",
        env=env,
    )
    return checkout / "apps/client/android/app/build/outputs/apk/release/app-release-unsigned.apk"


def sign_release(
    config,
    sdk,
    apk,
    keystore,
    store_password_file,
    key_password_file,
    alias,
    output,
    env,
):
    binaries = tools(sdk)
    apk = Path(apk)
    inspect_apk(apk, config, sdk, signed=False, env=env)
    aligned = apk.parent / "aligned.apk"
    signed = apk.parent / "signed.apk"
    run([str(binaries["zipalign"]), "-P", "16", "-v", "4", str(apk), str(aligned)], env=env)
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
        ],
        env=env,
    )
    result = inspect_apk(signed, config, sdk, signed=True, env=env)
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
    except ReleaseAbort as abort:
        raise SystemExit(
            f"Release preparation failed ({abort.code}). Nothing installed or published."
        ) from None
    except Exception:
        raise SystemExit("Release preparation failed. Nothing installed or published.") from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
