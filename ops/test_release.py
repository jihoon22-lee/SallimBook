"""Build/sign two disposable synthetic releases; no real key, install, or upload."""

import argparse
import hashlib
import os
import secrets
import subprocess
import tempfile
from pathlib import Path

from ops import release
from ops.backup import OperationError


def main(sdk):
    if not os.environ.get("JAVA_HOME"):
        raise RuntimeError("Selected JDK 21 required")
    commit = release.run(["git", "rev-parse", "HEAD"], cwd=release.ROOT)
    keytool = str(Path(os.environ["JAVA_HOME"]) / "bin/keytool")
    with tempfile.TemporaryDirectory(
        prefix="sallimbook-synthetic-signing-"
    ) as temporary:
        directory = Path(temporary)
        password_file = directory / "synthetic-password"
        password_file.write_text(secrets.token_urlsafe(32))
        password_file.chmod(0o600)
        key_password_file = directory / "synthetic-key-password"
        key_password_file.write_bytes(password_file.read_bytes())
        key_password_file.chmod(0o600)
        keystore = directory / "synthetic-only.p12"
        result = subprocess.run(
            [
                keytool,
                "-genkeypair",
                "-storetype",
                "PKCS12",
                "-keystore",
                str(keystore),
                "-storepass:file",
                str(password_file),
                "-keypass:file",
                str(password_file),
                "-alias",
                "synthetic",
                "-keyalg",
                "RSA",
                "-keysize",
                "2048",
                "-validity",
                "1",
                "-dname",
                "CN=SallimBook Synthetic Test Only,O=Synthetic,C=KR",
            ],
            capture_output=True,
        )
        if result.returncode:
            raise RuntimeError("Synthetic key generation failed")
        keystore.chmod(0o600)
        certificate = subprocess.check_output(
            [
                keytool,
                "-exportcert",
                "-alias",
                "synthetic",
                "-keystore",
                str(keystore),
                "-storepass:file",
                str(password_file),
            ],
            stderr=subprocess.DEVNULL,
        )
        fingerprint = ":".join(
            f"{byte:02X}" for byte in hashlib.sha256(certificate).digest()
        )
        config = {
            "format": 1,
            "project": "sallimbook-staging",
            "fqdn": "synthetic.example.ts.net",
            "certificate_sha256": fingerprint,
            "api_image": "example.invalid/api:test@sha256:" + "1" * 64,
            "web_image": "example.invalid/web:test@sha256:" + "2" * 64,
            "runtime_directory": "/srv/sallimbook/sallimbook-staging",
            "version_code": 2,
            "version_name": "0.1.1",
            "source_commit": commit,
        }
        previous = directory / "first.apk"
        first = release.build(
            config,
            sdk,
            keystore,
            password_file,
            key_password_file,
            "synthetic",
            previous,
            0,
        )
        assert first["signed"] and first["version_code"] == 2
        print(
            "PASS: synthetic release v2 actual build, manifest/native configuration, alignment, signing/certificate",
            flush=True,
        )
        next_config = {**config, "version_code": 3, "version_name": "0.1.2"}
        result = release.build(
            next_config,
            sdk,
            keystore,
            password_file,
            key_password_file,
            "synthetic",
            directory / "next.apk",
            2,
            previous,
        )
        assert result["signed"] and result["version_code"] == 3
        tampered = directory / "tampered.apk"
        tampered.write_bytes(
            (directory / "next.apk").read_bytes() + b"synthetic-tamper"
        )
        try:
            release.inspect_apk(tampered, next_config, sdk, signed=True)
            raise AssertionError("Tampered signed APK accepted")
        except OperationError:
            pass
        print(
            "PASS: same-certificate prior-APK gate, increasing v3 release, tamper refusal. No device install/real signing key used."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    main(parser.parse_args().sdk)
