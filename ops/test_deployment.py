"""Validate pinned proxy images in disposable network-none containers; no node registration."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from ops.deploy import TAILSCALE, write_config


def command(args):
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("Isolated deployment validation failed")
    return result.stdout


def main(web_image):
    assert command(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "caddy",
            web_image,
            "version",
        ]
    ).startswith("v2.11.7 ")
    assert command(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "tailscale",
            TAILSCALE,
            "version",
        ]
    ).startswith("1.104.1\n")
    with tempfile.TemporaryDirectory(
        prefix="sallimbook-deploy-synthetic-"
    ) as temporary:
        root = Path(temporary)
        runtime = root / "sallimbook-staging"
        runtime.mkdir(mode=0o700)
        (runtime / "api.env").write_text("# Synthetic, not runnable API credentials\n")
        manifest = {
            "format": 1,
            "project": "sallimbook-staging",
            "fqdn": "synthetic.example.ts.net",
            "certificate_sha256": ":".join(["AB"] * 32),
            "api_image": "example.invalid/sallimbook/api:synthetic@sha256:" + "1" * 64,
            "web_image": "example.invalid/sallimbook/web:synthetic@sha256:" + "2" * 64,
            "runtime_directory": str(runtime),
            "version_code": 2,
            "version_name": "0.1.1",
            "source_commit": "a" * 40,
            "setup_identity_sha256": "a" * 64,
        }
        output = root / "rendered"
        previous = os.umask(0o077)
        try:
            write_config(manifest, output)
        finally:
            os.umask(previous)
        apk = output / "downloads/SallimBook.apk"
        apk.write_bytes(b"synthetic APK transport fixture, not an installable release")
        apk.chmod(0o644)
        (output / "downloads/other.apk").write_bytes(b"must not be served")
        (output / "downloads/other.apk").chmod(0o644)
        isolated = [
            "docker", "run", "--rm", "--network", "none", "--user", "10001:10001",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        ]
        assert command(isolated + ["--entrypoint", "getcap", web_image, "/usr/bin/caddy"]) == ""
        command([
            "docker", "run", "--rm", "--network", "none", "--user", "0:0",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--read-only", "--entrypoint", "sh",
            "-v", str(output / "node") + ":/config:ro",
            web_image, "-c", "test -x /config && test -r /config/serve.json",
        ])
        command(
            [
                "docker",
                "compose",
                "-f",
                str(output / "compose.json"),
                "config",
                "--quiet",
            ]
        )
        for filename in ("public.Caddyfile", "private.Caddyfile"):
            result = command(
                isolated + [
                    "--entrypoint",
                    "caddy",
                    "-v",
                    str(output / filename) + ":/etc/caddy/Caddyfile:ro",
                    web_image,
                    "validate",
                    "--config",
                    "/etc/caddy/Caddyfile",
                    "--adapter",
                    "caddyfile",
                ]
            )
            assert "Valid configuration" in result
        script = """set -eu
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile >/tmp/caddy.log 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
for i in 1 2 3 4 5 6 7 8 9 10; do
    if wget -q -O /tmp/body http://127.0.0.1:8081/.well-known/assetlinks.json 2>/dev/null; then
        break
    fi
    sleep 0.1
done
grep -q io.github.jihoon22lee.sallimbook /tmp/body
for path in / /api/v1/health /.well-known/assetlinks.json/ /private.key \\
    /downloads/SallimBook.apk; do
    if wget -S -O /tmp/body "http://127.0.0.1:8081$path" 2>/tmp/headers; then exit 1; fi
    grep -q '404 Not Found' /tmp/headers
done
"""
        command(
            isolated + [
                "--read-only",
                "--tmpfs",
                "/tmp:rw,nosuid,noexec,size=16m,uid=10001,gid=10001,mode=0700",
                "--entrypoint",
                "sh",
                "-v",
                str(output / "public.Caddyfile") + ":/etc/caddy/Caddyfile:ro",
                "-v",
                str(output / "public") + ":/srv/public:ro",
                web_image,
                "-c",
                script,
            ]
        )
        private_script = """set -eu
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile >/tmp/caddy.log 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
for i in 1 2 3 4 5 6 7 8 9 10; do
    if wget -q -O /tmp/apk --header='Host: synthetic.example.ts.net' \\
        http://127.0.0.1:8080/downloads/SallimBook.apk 2>/dev/null; then break; fi
    sleep 0.1
done
cmp /tmp/apk /srv/downloads/SallimBook.apk
wget -S -O /tmp/apk --header='Host: synthetic.example.ts.net' \\
    http://127.0.0.1:8080/downloads/SallimBook.apk 2>/tmp/headers
grep -q 'application/vnd.android.package-archive' /tmp/headers
grep -q 'attachment; filename=SallimBook.apk' /tmp/headers
grep -q 'no-store' /tmp/headers
wget --spider -S --header='Host: synthetic.example.ts.net' \\
    http://127.0.0.1:8080/downloads/SallimBook.apk 2>/tmp/headers
if wget -S -O /tmp/body --header='Host: synthetic.example.ts.net' --post-data=synthetic \\
    http://127.0.0.1:8080/downloads/SallimBook.apk 2>/tmp/headers; then exit 1; fi
grep -q '404 Not Found' /tmp/headers
for path in /downloads /downloads/ /downloads/other.apk /downloads/SallimBook.apk/; do
    if wget -S -O /tmp/body --header='Host: synthetic.example.ts.net' \\
        "http://127.0.0.1:8080$path" 2>/tmp/headers; then exit 1; fi
    grep -q '404 Not Found' /tmp/headers
done
for path in / /assets/index.js /downloads/SallimBook.apk; do
    wget -S -O /tmp/body --header='Host: synthetic.example.ts.net' \\
        "http://127.0.0.1:8080$path" 2>/tmp/headers || true
    for name in Content-Security-Policy Strict-Transport-Security X-Frame-Options \\
        X-Content-Type-Options Referrer-Policy; do
        grep -qi "^ *$name: " /tmp/headers
    done
done
"""
        command(isolated + [
            "--read-only", "--tmpfs",
            "/tmp:rw,nosuid,noexec,size=16m,uid=10001,gid=10001,mode=0700",
            "--entrypoint", "sh",
            "-v", str(output / "private.Caddyfile") + ":/etc/caddy/Caddyfile:ro",
            "-v", str(output / "downloads") + ":/srv/downloads:ro",
            web_image, "-c", private_script,
        ])
        # A synthetic upstream checks real Caddy forwarding, not Tailscale identity
        # authentication. Only this network-none fixture resolves api to loopback.
        proxy_fixture = output / "identity-proxy.Caddyfile"
        proxy_fixture.write_text(
            (output / "private.Caddyfile").read_text()
            + '\nhttp://:8000 {\n    bind 127.0.0.1\n'
            + '    respond "{http.request.header.Tailscale-User-Login}|'
            + '{http.request.header.Forwarded}|{http.request.header.X-Forwarded-For}"\n}\n'
        )
        proxy_fixture.chmod(0o644)
        identity_script = """set -eu
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile >/tmp/caddy.log 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
for i in 1 2 3 4 5 6 7 8 9 10; do
    if wget -q -O /tmp/body --header='Host: synthetic.example.ts.net' \\
        http://127.0.0.1:8080/api/probe 2>/dev/null; then break; fi
    sleep 0.1
done
test "$(cat /tmp/body)" = '||'
for identity in allowed@synthetic.invalid wrong@synthetic.invalid; do
    wget -q -O /tmp/body --header='Host: synthetic.example.ts.net' \\
        --header="Tailscale-User-Login: $identity" \\
        --header='Forwarded: for=192.0.2.123' --header='X-Forwarded-For: 192.0.2.123' \\
        http://127.0.0.1:8080/api/probe
    test "$(cat /tmp/body)" = "$identity||"
done
wget -S -O /tmp/body --header='Host: synthetic.example.ts.net' \\
    http://127.0.0.1:8080/api/probe 2>/tmp/headers
grep -qi '^ *X-Content-Type-Options: nosniff' /tmp/headers
grep -qi '^ *Strict-Transport-Security: ' /tmp/headers
if grep -qi -e '^ *Content-Security-Policy: ' -e '^ *X-Frame-Options: ' /tmp/headers; then exit 1; fi
"""
        command(isolated + [
            "--read-only", "--tmpfs",
            "/tmp:rw,nosuid,noexec,size=16m,uid=10001,gid=10001,mode=0700",
            "--add-host", "api:127.0.0.1", "--entrypoint", "sh",
            "-v", str(proxy_fixture) + ":/etc/caddy/Caddyfile:ro",
            web_image, "-c", identity_script,
        ])
        serve = json.loads((output / "node/serve.json").read_text())
        assert set(serve["AllowFunnel"]) == {manifest["fqdn"] + ":443"}
    print(
        "PASS: pinned Caddy/Tailscale versions, Compose/Caddy validation, "
        "strict-umask UID10001/cap-drop reads, private exact APK/public 404 routing, "
        "identity header forwarding and forwarded-IP removal. "
        "No tailnet node, installable APK, or real HTTPS tested."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-image", required=True)
    main(parser.parse_args().web_image)
