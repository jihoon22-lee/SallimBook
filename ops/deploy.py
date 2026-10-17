"""Render reviewable configuration. Never starts Docker or registers a node."""

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

APP_ID = "io.github.jihoon22lee.sallimbook"
CADDY = (
    "caddy:2.11.7-alpine@sha256:"
    "d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f"
)
TAILSCALE = (
    "tailscale/tailscale:v1.104.1@sha256:"
    "87c55d6be56ad85b3d8bceca5f87f73de288c609131460dd1be1874c250cc41d"
)
POSTGRES = (
    "postgres:18.6-bookworm@sha256:"
    "afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c"
)
IMAGE = re.compile(r"[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}")
REQUIRED = {
    "format",
    "project",
    "fqdn",
    "certificate_sha256",
    "api_image",
    "web_image",
    "runtime_directory",
    "version_code",
    "version_name",
    "source_commit",
}


def validate(config):
    if (
        set(config) != REQUIRED
        or type(config["format"]) is not int
        or config["format"] != 1
    ):
        raise ValueError("Unknown or missing deployment fields")
    if config["project"] not in {"sallimbook-prod", "sallimbook-staging"}:
        raise ValueError("Dedicated SallimBook project required")
    if not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.[a-z0-9-]+\.ts\.net", config["fqdn"]
    ):
        raise ValueError("An actual dedicated Tailscale FQDN is required")
    if not re.fullmatch(
        r"[0-9A-F]{2}(?::[0-9A-F]{2}){31}", config["certificate_sha256"]
    ):
        raise ValueError("SHA-256 signing certificate fingerprint required")
    for name in ("api_image", "web_image"):
        if not IMAGE.fullmatch(config[name]) or ":latest@" in config[name]:
            raise ValueError("Application images require immutable digests")
    path = Path(config["runtime_directory"])
    if (
        not path.is_absolute()
        or ".." in path.parts
        or not re.fullmatch(r"/[a-zA-Z0-9_./-]+", str(path))
        or path.name != config["project"]
        or len(path.parts) < 4
    ):
        raise ValueError("A dedicated absolute runtime directory is required")
    if (
        type(config["version_code"]) is not int
        or not 1 <= config["version_code"] <= 2100000000
    ):
        raise ValueError("Invalid Android version code")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", config["version_name"]):
        raise ValueError("Release version name must be numeric x.y.z")
    if not re.fullmatch(r"[0-9a-f]{40}", config["source_commit"]):
        raise ValueError("Exact source commit required")
    return config


def assetlinks(config):
    return [
        {
            "relation": [
                "delegate_permission/common.handle_all_urls",
                "delegate_permission/common.get_login_creds",
            ],
            "target": {
                "namespace": "android_app",
                "package_name": APP_ID,
                "sha256_cert_fingerprints": [config["certificate_sha256"]],
            },
        }
    ]


def render(config):
    c = validate(config)
    fqdn = c["fqdn"]
    origin = "https://" + fqdn + ":8443"
    native_origin = "android:apk-key-hash:" + base64.urlsafe_b64encode(
        bytes.fromhex(c["certificate_sha256"].replace(":", ""))
    ).decode().rstrip("=")
    runtime = c["runtime_directory"]
    public_caddy = """{
    admin off
    auto_https off
}
http://:8081 {
    bind 127.0.0.1
    @verification {
        method GET HEAD
        path /.well-known/assetlinks.json
    }
    handle @verification {
        root * /srv/public
        header Content-Type application/json
        header X-Content-Type-Options nosniff
        file_server
    }
    handle {
        respond 404
    }
}
"""
    private_caddy = f"""{{
    admin off
    auto_https off
}}
http://:8080 {{
    bind 127.0.0.1
    @wrong_host not host {fqdn}
    respond @wrong_host 421
    header X-Content-Type-Options nosniff
    header Referrer-Policy no-referrer
    handle /api/* {{
        reverse_proxy api:8000 {{
            header_up Host {fqdn}:8443
            header_up X-Forwarded-Proto https
            header_up X-Forwarded-Host {fqdn}:8443
            header_up -X-Forwarded-For
            header_up -Forwarded
        }}
    }}
    handle {{
        root * /srv/web
        try_files {{path}} /index.html
        header Cache-Control no-cache
        file_server
    }}
}}
"""
    # Both proxies share only this dedicated node's namespace. Serve accepts loopback
    # upstreams; no host networking, host ports, /dev/net/tun or NET_ADMIN is needed.
    serve = {
        "TCP": {"443": {"HTTPS": True}, "8443": {"HTTPS": True}},
        "Web": {
            fqdn + ":443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8081"}}},
            fqdn + ":8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8080"}}},
        },
        "AllowFunnel": {fqdn + ":443": True},
    }
    common = {
        "restart": "unless-stopped",
        "security_opt": ["no-new-privileges:true"],
        "cap_drop": ["ALL"],
        "logging": {"driver": "local", "options": {"max-size": "10m", "max-file": "3"}},
    }
    services = {
        "node": {
            **common,
            "image": TAILSCALE,
            "hostname": c["project"],
            "environment": {
                "TS_USERSPACE": "true",
                "TS_STATE_DIR": "/var/lib/tailscale",
                "TS_SERVE_CONFIG": "/config/serve.json",
                "TS_AUTH_ONCE": "true",
            },
            "volumes": ["node_state:/var/lib/tailscale", "./node:/config:ro"],
            "networks": ["edge", "app"],
            "mem_limit": "256m",
        },
        "public": {
            **common,
            "image": CADDY,
            "network_mode": "service:node",
            "user": "10001:10001",
            "read_only": True,
            "volumes": [
                "./public.Caddyfile:/etc/caddy/Caddyfile:ro",
                "./public:/srv/public:ro",
            ],
            "tmpfs": [
                "/config:mode=0700,uid=10001,gid=10001",
                "/data:mode=0700,uid=10001,gid=10001",
            ],
            "depends_on": ["node"],
            "mem_limit": "64m",
        },
        "web": {
            **common,
            "image": c["web_image"],
            "network_mode": "service:node",
            "user": "10001:10001",
            "read_only": True,
            "volumes": ["./private.Caddyfile:/etc/caddy/Caddyfile:ro"],
            "tmpfs": [
                "/config:mode=0700,uid=10001,gid=10001",
                "/data:mode=0700,uid=10001,gid=10001",
            ],
            "depends_on": ["node", "api"],
            "mem_limit": "128m",
        },
        "api": {
            **common,
            "image": c["api_image"],
            "user": "10001:10001",
            "read_only": True,
            "env_file": [{"path": runtime + "/api.env", "format": "raw"}],
            "environment": {
                "SALLIMBOOK_ENVIRONMENT": "production",
                "SALLIMBOOK_ALLOWED_ORIGINS": json.dumps([origin]),
                "SALLIMBOOK_WEBAUTHN_RP_ID": fqdn,
                "SALLIMBOOK_WEBAUTHN_WEB_ORIGINS": json.dumps([origin]),
                "SALLIMBOOK_WEBAUTHN_NATIVE_ORIGINS": json.dumps([native_origin]),
                "SALLIMBOOK_FIELD_ENCRYPTION_KEY_FILE": "/run/secrets/field-keyring.json",
                "SALLIMBOOK_DOCUMENT_STORAGE_DIRECTORY": "/srv/documents",
                "SALLIMBOOK_DOCUMENT_SCANNER_SOCKET": "/run/scanner/clamd.sock",
            },
            "volumes": [
                runtime + "/field-keyring.json:/run/secrets/field-keyring.json:ro",
                runtime + "/documents:/srv/documents",
                "scanner_socket:/run/scanner:ro",
            ],
            "tmpfs": [
                "/tmp:rw,noexec,nosuid,nodev,size=160m,mode=0700,uid=10001,gid=10001"
            ],
            "mem_limit": "768m",
            "memswap_limit": "768m",
            "networks": ["app", "database"],
            "command": [
                "uvicorn",
                "sallimbook.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--workers",
                "1",
                "--no-access-log",
                "--no-proxy-headers",
            ],
            "depends_on": {
                "db": {"condition": "service_healthy"},
                "scanner": {"condition": "service_started"},
            },
            "healthcheck": {
                "test": [
                    "CMD",
                    "python",
                    "-c",
                    "import urllib.request; "
                    "urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', "
                    "timeout=2).close()",
                ],
                "interval": "30s",
                "timeout": "3s",
                "retries": 3,
            },
        },
        "scanner": {
            **common,
            "image": c["api_image"],
            "user": "10001:10001",
            "read_only": True,
            "network_mode": "none",
            "volumes": ["scanner_socket:/run/scanner"],
            "tmpfs": [
                "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=0700,uid=10001,gid=10001"
            ],
            "command": [
                "/usr/local/sbin/clamd",
                "--foreground",
                "--config-file=/etc/sallimbook/clamd.conf",
            ],
            "mem_limit": "1536m",
            "memswap_limit": "1536m",
        },
        "db": {
            "image": POSTGRES,
            "restart": "unless-stopped",
            "networks": ["database"],
            "security_opt": ["no-new-privileges:true"],
            "environment": {
                "POSTGRES_DB": "sallimbook_prod",
                "POSTGRES_USER": "sallimbook_admin",
                "POSTGRES_PASSWORD_FILE": "/run/secrets/db-admin-password",
                "POSTGRES_HOST_AUTH_METHOD": "scram-sha-256",
            },
            "volumes": [
                "db_data:/var/lib/postgresql",
                runtime + "/db-admin-password:/run/secrets/db-admin-password:ro",
            ],
            "healthcheck": {
                "test": [
                    "CMD",
                    "pg_isready",
                    "-U",
                    "sallimbook_admin",
                    "-d",
                    "sallimbook_prod",
                ],
                "interval": "5s",
                "timeout": "3s",
                "retries": 30,
            },
            "mem_limit": "1g",
            "command": [
                "postgres",
                "-c",
                "cluster_name=" + c["project"],
                "-c",
                "log_statement=none",
                "-c",
                "log_parameter_max_length=0",
                "-c",
                "log_parameter_max_length_on_error=0",
            ],
            "logging": common["logging"],
        },
    }
    compose = {
        "name": c["project"],
        "services": services,
        "networks": {
            "edge": {},
            "app": {"internal": True},
            "database": {"internal": True},
        },
        "volumes": {"node_state": {}, "db_data": {}, "scanner_socket": {}},
    }
    return {
        "compose.json": compose,
        "node/serve.json": serve,
        "public/.well-known/assetlinks.json": assetlinks(c),
        "public.Caddyfile": public_caddy,
        "private.Caddyfile": private_caddy,
        "android-public.json": {
            "api_origin": origin,
            "rp_id": fqdn,
            "native_origin": native_origin,
            "application_id": APP_ID,
            "certificate_sha256": c["certificate_sha256"],
            "version_code": c["version_code"],
            "version_name": c["version_name"],
        },
        "deployment.json": c,
    }


def write_config(config, output):
    files = render(config)
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    checksums = {}
    for name, value in files.items():
        content = (
            value if isinstance(value, str) else json.dumps(value, indent=2) + "\n"
        )
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        checksums[name] = hashlib.sha256(content.encode()).hexdigest()
    (output / "checksums.json").write_text(json.dumps(checksums, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    write_config(json.loads(args.manifest.read_text()), args.output)
    print(
        "Configuration rendered. No services started; deployment acceptance remains pending."
    )


if __name__ == "__main__":
    main()
