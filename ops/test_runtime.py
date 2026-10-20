"""Run actual API/scanner/inspector/DB in a new disposable Compose project with no host ports."""

import argparse
import json
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from ops.backup import OperationError
from ops.build_context import REVISION_LABEL
from ops.deploy import render
from ops.preflight import verify_image_details


def run(command, *, report=False):
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if result.returncode:
        # The probe prints only synthetic, schema-controlled status. Infrastructure
        # diagnostics can contain environment values; keep those out of stdout.
        if report:
            print(result.stdout[-2000:])
            print(result.stderr[-2000:])
        raise RuntimeError("Isolated runtime command failed")
    if report:
        print(result.stdout.strip())
    return result.stdout


def main(image):
    # A local build is identified by its immutable image ID, without publishing it.
    inspected = json.loads(run(["docker", "image", "inspect", image]))[0]
    revision = (inspected.get("Config", {}).get("Labels") or {}).get(REVISION_LABEL)
    if not revision:
        raise RuntimeError("Source-labelled application image required")
    verify_image_details([inspected], revision=revision, role="api")
    for wanted_revision, wanted_role in (
        ("b" * 40 if revision != "b" * 40 else "c" * 40, "api"),
        (revision, "web"),
    ):
        try:
            verify_image_details([inspected], revision=wanted_revision, role=wanted_role)
        except OperationError:
            pass
        else:
            raise AssertionError("Actual image accepted a mismatched revision or role")
    image_id = inspected["Id"]
    for mode in ("scanner", "inspector", "api"):
        cold = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", "--read-only",
             "--entrypoint", "python", image_id, "-m", "ops.health", mode],
            capture_output=True, timeout=15, check=False,
        )
        assert cold.returncode == 1, "Cold readiness unexpectedly passed: " + mode
    project = "sallimbook-ops-smoke-" + uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix=project + "-") as temporary:
        directory = Path(temporary)
        password = secrets.token_urlsafe(32)
        admin_password = secrets.token_urlsafe(32)
        database = "sallimbook_ops_" + uuid4().hex[:12] + "_test"
        env = directory / "synthetic.env"
        env.write_text(
            "SALLIMBOOK_DATABASE_URL=postgresql+psycopg://sallimbook_app:"
            + password
            + "@db:5432/"
            + database
            + "\n"
        )
        env.chmod(0o600)
        migration_env = directory / "synthetic-migration.env"
        migration_env.write_text(
            "SALLIMBOOK_DATABASE_URL=postgresql+psycopg://sallimbook_admin:"
            + admin_password
            + "@db:5432/"
            + database
            + "\n"
        )
        migration_env.chmod(0o600)
        init_env = directory / "synthetic-init.env"
        init_env.write_text(
            "OPS_DB_PASSWORD="
            + password
            + "\nOPS_ADMIN_DB_PASSWORD="
            + admin_password
            + "\nOPS_DATABASE="
            + database
            + "\n"
        )
        init_env.chmod(0o600)
        config = {
            "format": 1,
            "project": "sallimbook-staging",
            "fqdn": "synthetic.example.ts.net",
            "certificate_sha256": ":".join(["AB"] * 32),
            "api_image": "example.invalid/api:test@" + image_id,
            "web_image": "example.invalid/web:test@sha256:" + "1" * 64,
            "runtime_directory": str(directory / "sallimbook-staging"),
            "version_code": 2,
            "version_name": "0.1.1",
            "source_commit": revision,
        }
        production = render(config)["compose.json"]
        services = {
            name: production["services"][name] for name in ("api", "db", "scanner", "inspector")
        }
        for name in ("api", "scanner", "inspector"):
            services[name]["image"] = image_id
            services[name]["restart"] = "no"
            services[name]["healthcheck"]["interval"] = "1s"
            services[name]["healthcheck"]["retries"] = 1
        services["api"]["env_file"] = [str(env)]
        services["api"]["healthcheck"]["start_period"] = "10s"
        services["api"]["environment"].update(
            SALLIMBOOK_ENVIRONMENT="test", SALLIMBOOK_OPS_SYNTHETIC="1"
        )
        services["api"]["volumes"] = [
            "synthetic_secrets:/run/secrets:ro",
            "synthetic_documents:/srv/documents",
            "scanner_socket:/run/scanner:ro",
            "inspector_socket:/run/inspector:ro",
        ]
        services["db"]["environment"]["POSTGRES_DB"] = database
        services["db"]["healthcheck"]["test"][-1] = database
        services["db"]["volumes"] = [
            "db_data:/var/lib/postgresql",
            "synthetic_secrets:/run/secrets:ro",
        ]
        services["db"]["restart"] = "no"
        services["db"]["command"][2] = "cluster_name=" + project
        init = """import base64,json,os,pathlib
for name in ['/run/secrets','/srv/documents','/run/scanner','/run/operator']:
 p=pathlib.Path(name); p.mkdir(exist_ok=True); p.chmod(0o700); os.chown(p,10001,10001)
p=pathlib.Path('/run/secrets/field-keyring.json')
p.write_text(json.dumps({'schema_version':1,'active_key_version':1,'keys':{'1':base64.b64encode(bytes(range(32))).decode()}}))
p.chmod(0o600); os.chown(p,10001,10001)
p=pathlib.Path('/run/secrets/db-admin-password')
p.write_text(os.environ['OPS_ADMIN_DB_PASSWORD']); p.chmod(0o600)
p=pathlib.Path('/run/operator/app-db-password')
p.write_text(os.environ['OPS_DB_PASSWORD']); p.chmod(0o600); os.chown(p,10001,10001)
p=pathlib.Path('/run/operator/admin-service.conf')
p.write_text('[sallimbook]\\nhost=db\\nport=5432\\nuser=sallimbook_admin\\nsslmode=disable\\ndbname='+os.environ['OPS_DATABASE']+'\\npassword='+os.environ['OPS_ADMIN_DB_PASSWORD']+'\\n')
p.chmod(0o600); os.chown(p,10001,10001)
"""
        services["init"] = {
            "image": image_id,
            "user": "0:0",
            "network_mode": "none",
            "restart": "no",
            "env_file": [str(init_env)],
            "volumes": [
                "synthetic_secrets:/run/secrets",
                "synthetic_documents:/srv/documents",
                "scanner_socket:/run/scanner",
                "operator_secrets:/run/operator",
            ],
            "entrypoint": ["python", "-c", init],
            "mem_limit": "128m",
        }
        services["migrate"] = {
            "image": image_id,
            "user": "10001:10001",
            "read_only": True,
            "networks": ["database"],
            "env_file": [str(migration_env)],
            "profiles": ["tools"],
            "command": [
                "alembic",
                "-c",
                "/opt/sallimbook/alembic.ini",
                "upgrade",
                "head",
            ],
        }
        services["provision"] = {
            "image": image_id,
            "user": "10001:10001",
            "read_only": True,
            "networks": ["database"],
            "volumes": ["operator_secrets:/run/operator:ro"],
            "profiles": ["tools"],
            "command": [
                "python",
                "-m",
                "ops.database",
                "provision",
                "--admin-service-file",
                "/run/operator/admin-service.conf",
                "--application-password-file",
                "/run/operator/app-db-password",
            ],
        }
        services["privilege_probe"] = {
            **services["provision"],
            "env_file": [str(env)],
            "environment": {"SALLIMBOOK_OPS_SYNTHETIC": "1"},
            "command": [
                "python",
                "-m",
                "ops.runtime_privilege_probe",
                "--admin-service-file",
                "/run/operator/admin-service.conf",
            ],
        }
        compose = {
            "name": project,
            "services": services,
            "networks": {"app": {"internal": True}, "database": {"internal": True}},
            "volumes": {
                name: {}
                for name in (
                    "db_data",
                    "scanner_socket",
                    # Not mounted by init: like production, the empty volume takes the
                    # image directory's owner and mode, which the inspector probe checks.
                    "inspector_socket",
                    "synthetic_secrets",
                    "synthetic_documents",
                    "operator_secrets",
                )
            },
        }
        compose_file = directory / "compose.json"
        compose_file.write_text(json.dumps(compose))
        command = ["docker", "compose", "-p", project, "-f", str(compose_file)]
        try:
            run(command + ["run", "--rm", "init"])
            run(command + ["up", "-d", "--wait", "db", "scanner", "inspector"])
            run(command + ["run", "--rm", "--no-deps", "migrate"])
            run(command + ["run", "--rm", "--no-deps", "provision"])
            run(command + ["run", "--rm", "--no-deps", "privilege_probe"], report=True)
            run(command + ["up", "-d", "--wait", "--wait-timeout", "90", "api"])
            run(
                command + ["exec", "-T", "api", "python", "-m", "ops.runtime_probe"],
                report=True,
            )
            run(
                command + ["exec", "-T", "inspector", "python", "-B", "-m", "ops.inspector_probe"],
                report=True,
            )
            for name in ("api", "scanner", "inspector"):
                identifier = run(command + ["ps", "-q", name]).strip()
                state = json.loads(run(["docker", "inspect", identifier]))[0]
                assert state["HostConfig"]["ReadonlyRootfs"] is True
                assert (
                    state["HostConfig"]["Memory"] == state["HostConfig"]["MemorySwap"]
                )
                assert not state["HostConfig"]["PortBindings"]
                assert state["State"]["Health"]["Status"] == "healthy"
                if name == "inspector":
                    assert state["Config"]["User"] == "10002:10003"
                    assert state["HostConfig"]["NetworkMode"] == "none"
                    assert state["HostConfig"]["PidsLimit"] == 32
                    # Compose passes named volumes through Binds; no host path may appear.
                    assert all(not bind.startswith("/") for bind in state["HostConfig"]["Binds"] or [])
                    # The /tmp tmpfs is in HostConfig.Tmpfs, not in Mounts.
                    assert {(m["Type"], m["Destination"]) for m in state["Mounts"]} == {
                        ("volume", "/run/inspector")
                    }
                else:
                    assert state["Config"]["User"] == "10001:10001"
                if name == "api":
                    assert state["HostConfig"]["GroupAdd"] == ["10003"]
            api_id = run(command + ["ps", "-q", "api"]).strip()
            # 64 MiB blocks of b"x" touch every page, so the cgroup limit (not malloc
            # overcommit refusal) must stop this synthetic hog.
            hog = subprocess.run(
                command + ["exec", "-T", "inspector", "python", "-c",
                           "blocks = [b'x' * (64 * 1024 ** 2) for _ in range(64)]"],
                capture_output=True, timeout=120, check=False,
            )
            assert hog.returncode == 137, "Inspector memory limit did not stop the hog"
            api_state = json.loads(run(["docker", "inspect", api_id]))[0]
            assert api_state["State"]["OOMKilled"] is False
            assert api_state["RestartCount"] == 0
            assert api_state["State"]["Health"]["Status"] == "healthy"
            inspector_id = run(command + ["ps", "-q", "inspector"]).strip()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                state = json.loads(run(["docker", "inspect", inspector_id]))[0]
                if state["State"]["Running"] and state["State"]["Health"]["Status"] == "healthy":
                    break
                time.sleep(0.25)
            else:
                raise AssertionError("Inspector server did not survive the hog")
            run(command + ["stop", "scanner"])
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                state = json.loads(run(["docker", "inspect", api_id]))[0]
                if state["State"]["Health"]["Status"] == "unhealthy":
                    break
                time.sleep(0.25)
            else:
                raise AssertionError("API stayed healthy after scanner stopped")
            # A database-only HTTP probe still passes, so the observed unhealthy
            # state comes from the real scanner dependency, not an API shutdown.
            run(command + ["exec", "-T", "api", "python", "-c",
                "import urllib.request; "
                "urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready').close()"])
            run(command + ["up", "-d", "--wait", "--wait-timeout", "120", "scanner"])
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                state = json.loads(run(["docker", "inspect", api_id]))[0]
                if state["State"]["Health"]["Status"] == "healthy":
                    break
                time.sleep(0.25)
            else:
                raise AssertionError("API readiness did not recover with the scanner")
            run(command + ["stop", "inspector"])
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                state = json.loads(run(["docker", "inspect", api_id]))[0]
                if state["State"]["Health"]["Status"] == "unhealthy":
                    break
                time.sleep(0.25)
            else:
                raise AssertionError("API stayed healthy after the inspector stopped")
            run(command + ["exec", "-T", "api", "python", "-c", (
                "import urllib.request; "
                "urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready').close()"
            )])
            run(command + ["up", "-d", "--wait", "--wait-timeout", "120", "inspector"])
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                state = json.loads(run(["docker", "inspect", api_id]))[0]
                if state["State"]["Health"]["Status"] == "healthy":
                    break
                time.sleep(0.25)
            else:
                raise AssertionError("API readiness did not recover with the inspector")
            print(
                "PASS: image startup/migration/readiness, scanner-down unhealthy/recovery, "
                "inspector isolation/memory containment/down-recovery, "
                "production UID/mount/memory; no published ports, node, real account, or real key"
            )
        finally:
            # Only this unique project and its newly created synthetic volumes.
            run(command + ["down", "--volumes", "--remove-orphans"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    main(parser.parse_args().image)
