"""Validate pinned proxy images in disposable network-none containers; no node registration."""

import json
import subprocess
import tempfile
from pathlib import Path

from ops.deploy import CADDY, TAILSCALE, write_config


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("Isolated deployment validation failed")
    return result.stdout


def main():
    assert command(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "caddy",
            CADDY,
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
        }
        output = root / "rendered"
        write_config(manifest, output)
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
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--entrypoint",
                    "caddy",
                    "-v",
                    str(output) + ":/config:ro",
                    CADDY,
                    "validate",
                    "--config",
                    "/config/" + filename,
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
    if wget -q -O /tmp/body http://127.0.0.1:8081/.well-known/assetlinks.json 2>/dev/null; then break; fi
    sleep 0.1
done
grep -q io.github.jihoon22lee.sallimbook /tmp/body
for path in / /api/v1/health /.well-known/assetlinks.json/ /private.key; do
    if wget -S -O /tmp/body "http://127.0.0.1:8081$path" 2>/tmp/headers; then exit 1; fi
    grep -q '404 Not Found' /tmp/headers
done
"""
        command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,nosuid,noexec,size=16m",
                "--entrypoint",
                "sh",
                "-v",
                str(output / "public.Caddyfile") + ":/etc/caddy/Caddyfile:ro",
                "-v",
                str(output / "public") + ":/srv/public:ro",
                CADDY,
                "-c",
                script,
            ]
        )
        serve = json.loads((output / "node/serve.json").read_text())
        assert set(serve["AllowFunnel"]) == {manifest["fqdn"] + ":443"}
    print(
        "PASS: pinned Caddy/Tailscale versions, Compose/Caddy validation, isolated public JSON/404 routing. No tailnet node or real HTTPS tested."
    )


if __name__ == "__main__":
    main()
