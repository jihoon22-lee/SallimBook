"""Explicit Docker integration with new synthetic resources, never an existing deployment.

Run only during a coordinated Docker window, from a clean committed checkout.
The fixture intentionally contains just the tables consumed by backup/integrity,
with real account, policy and document AEAD ciphertext; it is not an API test.
"""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ops import automation, automation_runtime, backup, deploy

FIXTURE = """import base64,hashlib,json,os,secrets
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from ops.backup import connect,service_environment
from sallimbook.accounts.crypto import KeyRing,encrypt_number
from sallimbook.insurance.crypto import encrypt_number as encrypt_policy
from sallimbook.documents.storage import PrivateStore
os.umask(0o077)
root=Path('/fixture')
ring_path=root/'runtime/field-keyring.json'
ring_path.write_text(json.dumps({'schema_version':1,'active_key_version':1,
                              'keys':{'1':base64.b64encode(secrets.token_bytes(32)).decode()}}))
ring=KeyRing.load(ring_path)
row=SimpleNamespace(household_id=uuid4(),id=uuid4(),mime_type='text/plain',
                    size_bytes=28,
                    checksum_sha256=hashlib.sha256(b'synthetic restore proof only').hexdigest())
sealed=PrivateStore(root/'runtime/documents').put(row,b'synthetic restore proof only',ring)
env,_=service_environment(root/'credentials/service.conf')
with connect(env) as conn:
 conn.execute('CREATE TABLE alembic_version(version_num text PRIMARY KEY)')
 conn.execute("INSERT INTO alembic_version VALUES ('synthetic_automation_1')")
 conn.execute('CREATE TABLE vault_versions(household_id uuid,key_version integer)')
 conn.execute('CREATE TABLE documents(household_id uuid,id uuid,storage_key text,'
              'encryption_key_version integer,nonce bytea,mime_type text,size_bytes integer,'
              'checksum_sha256 text,state text)')
 conn.execute('INSERT INTO documents VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
              (row.household_id,row.id,sealed.storage_key,sealed.key_version,sealed.nonce,
               row.mime_type,row.size_bytes,row.checksum_sha256,'ready'))
 for table,column,encrypt in [
  ('financial_accounts','account_number_ciphertext',encrypt_number),
  ('insurance_policies','policy_number_ciphertext',encrypt_policy)]:
  conn.execute('CREATE TABLE '+table+'(household_id uuid,id uuid,number_key_version integer,'
               'number_nonce bytea,'+column+' bytea,last_four text)')
  identifier=uuid4();value=encrypt(ring,row.household_id,identifier,'123456789012')
  conn.execute('INSERT INTO '+table+' VALUES (%s,%s,%s,%s,%s,%s)',
               (row.household_id,identifier,value.key_version,value.nonce,value.ciphertext,'9012'))
print(json.dumps({'status':'synthetic-fixture-created','authenticated_field_kinds':3}))
"""


def private_text(path, content):
    with path.open("x") as stream:
        stream.write(content)
    path.chmod(0o600)


def run_check(image, app_source, age_keygen, output):
    os.umask(0o077)
    if output.is_relative_to(automation.ROOT):
        raise automation.AutomationError("INTEGRATION_OUTPUT_MUST_BE_EXTERNAL")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=automation.ROOT, text=True, timeout=10
    ).strip()
    project = "sallimbook-staging"
    config = {
        "format": 1,
        "project": project,
        "operator_source_commit": revision,
        "deployment_sha256": "0" * 64,
        "deployment_directory": str(output / "deployment"),
        "python_executable": sys.executable,
        "uv_executable": shutil.which("uv") or "/usr/bin/uv",
        "sdk_directory": "/opt/synthetic-unused-sdk",
        "java_home": "/opt/synthetic-unused-jdk",
    }
    for key, name in (
        ("state_directory", "state"),
        ("build_directory", "builds"),
        ("backup_directory", "backups"),
        ("restore_directory", "restores"),
    ):
        path = output / name / project
        path.mkdir(parents=True, mode=0o700)
        config[key] = str(path)
    credentials = output / "credentials"
    credentials.mkdir(mode=0o700)
    runtime = output / "runtime" / project
    runtime.mkdir(parents=True, mode=0o700)
    (runtime / "documents").mkdir(mode=0o700)
    for key, name in (
        ("backup_service_file", "service.conf"),
        ("backup_recipient_file", "recipient.txt"),
        ("restore_identity_file", "identity.txt"),
    ):
        config[key] = str(credentials / name)
    runner = automation.Runner(config)
    automation.verify_operator_source(config, runner)
    version = runner.run([age_keygen, "--version"], timeout=10).strip()
    if version != "v1.3.2":
        raise automation.AutomationError("INTEGRATION_AGE_VERSION")
    runner.run([age_keygen, "-o", credentials / "identity.txt"], timeout=10)
    recipient = runner.run([age_keygen, "-y", credentials / "identity.txt"], timeout=10).strip()
    private_text(credentials / "recipient.txt", recipient + "\n")
    password = secrets.token_urlsafe(36)
    private_text(credentials / "db-password", password)
    private_text(
        credentials / "service.conf",
        "[sallimbook]\nhost=db\nport=5432\n"
        "dbname=sallimbook_prod\nuser=sallimbook_app\npassword=" + password + "\nsslmode=disable\n",
    )
    del password, recipient
    manifest = {
        "format": 1,
        "project": project,
        "fqdn": "synthetic.example.ts.net",
        "certificate_sha256": ":".join(["AB"] * 32),
        "api_image": image,
        "web_image": "example.invalid/sallimbook/web:synthetic@sha256:" + "1" * 64,
        "runtime_directory": str(runtime),
        "version_code": 2,
        "version_name": "0.1.1",
        "source_commit": app_source,
    }
    # Validate backup's manifest contract without rendering/starting Compose.
    deploy.validate(manifest)
    deployment = output / "deployment"
    deployment.mkdir(mode=0o700)
    (deployment / "deployment.json").write_text(json.dumps(manifest))
    (deployment / "deployment.json").chmod(0o644)
    config["deployment_sha256"] = backup.digest(deployment / "deployment.json")
    private_text(output / "configuration.json", json.dumps(config))
    config_sha = backup.digest(output / "configuration.json")
    binding = {
        "directory": str(deployment),
        "sha256": config["deployment_sha256"],
        "manifest": manifest,
        "source_run": None,
    }
    journal = automation.Journal(config, "backup", config_sha)
    operator = automation_runtime.Runtime(config, binding, runner, journal)
    operator.image(image)
    fixture = output / "fixture.py"
    fixture.write_text(FIXTURE)
    fixture.chmod(0o644)
    setup = operator.resource("container", "fixture-ownership")
    network = operator.resource("network", "fixture-source")
    database = operator.resource("container", "fixture-db")
    client = operator.resource("container", "fixture-data")
    began = time.monotonic()
    try:
        # All paths are freshly created by this invocation. This changes no
        # existing operator, production, user or unrelated container ownership.
        ownership = (
            "import os;from pathlib import Path;"
            "roots=[Path('/fixture/credentials'),Path('/fixture/runtime'),"
            "Path('/fixture/backups/sallimbook-staging'),Path('/fixture/restores/sallimbook-staging')];"
            "[(os.chown(p,10001,10001),os.chmod(p,0o700 if p.is_dir() else 0o600)) "
            "for root in roots for p in [*root.rglob('*'),root]]"
        )
        operator.docker(
            "run",
            "--rm",
            "--name",
            setup,
            *operator.labels(),
            "--network",
            "none",
            "--user",
            "0:0",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "CHOWN",
            "--cap-add",
            "DAC_OVERRIDE",
            "--security-opt",
            "no-new-privileges:true",
            "--log-driver",
            "none",
            *operator.mount(output, "/fixture", readonly=False),
            image,
            "python",
            "-c",
            ownership,
            timeout=30,
        )
        operator.docker("network", "create", "--internal", *operator.labels(), network)
        operator.docker(
            "run",
            "--detach",
            "--name",
            database,
            *operator.labels(),
            "--network",
            network,
            "--network-alias",
            "db",
            "--read-only",
            "--log-driver",
            "none",
            "--memory",
            "512m",
            "--memory-swap",
            "512m",
            "--pids-limit",
            "96",
            "--tmpfs",
            "/var/lib/postgresql:rw,nosuid,nodev,size=256m",
            "--tmpfs",
            "/var/run/postgresql:rw,nosuid,nodev,size=4m",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=16m",
            *operator.mount(credentials / "db-password", "/run/fixture-password"),
            "--env",
            "POSTGRES_PASSWORD_FILE=/run/fixture-password",
            "--env",
            "POSTGRES_HOST_AUTH_METHOD=scram-sha-256",
            "--env",
            "POSTGRES_USER=sallimbook_app",
            "--env",
            "POSTGRES_DB=sallimbook_prod",
            deploy.POSTGRES,
            "-c",
            "shared_buffers=32MB",
            "-c",
            "max_connections=10",
            "-c",
            "min_wal_size=32MB",
            "-c",
            "max_wal_size=64MB",
        )
        deadline = time.monotonic() + 90
        while True:
            try:
                operator.docker(
                    "exec",
                    "--user",
                    "postgres",
                    database,
                    "pg_isready",
                    "-U",
                    "sallimbook_app",
                    "-d",
                    "sallimbook_prod",
                    timeout=10,
                )
                break
            except automation.AutomationError:
                if time.monotonic() >= deadline:
                    raise automation.AutomationError("INTEGRATION_DATABASE_START") from None
                time.sleep(1)
        fixture_result = json.loads(
            operator.docker(
                "run",
                "--rm",
                "--name",
                client,
                *operator.labels(),
                "--network",
                network,
                "--user",
                "10001:10001",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--log-driver",
                "none",
                *operator.mount(runtime, "/fixture/runtime", readonly=False),
                *operator.mount(credentials, "/fixture/credentials"),
                *operator.mount(fixture, "/fixture/fixture.py"),
                image,
                "python",
                "/fixture/fixture.py",
                timeout=60,
            )
        )
        if fixture_result != {
            "status": "synthetic-fixture-created",
            "authenticated_field_kinds": 3,
        }:
            raise automation.AutomationError("INTEGRATION_FIXTURE")
        result = operator.worker(
            "backup",
            network=network,
            mounts=[
                operator.mount(credentials / "service.conf", "/run/private/backup-service.conf"),
                operator.mount(credentials / "recipient.txt", "/run/private/backup-recipient.txt"),
                operator.mount(runtime / "documents", "/srv/documents"),
                operator.mount(config["backup_directory"], "/srv/backups", readonly=False),
                operator.mount(deployment / "deployment.json", "/run/deployment.json"),
            ],
            timeout=180,
        )
        if result.get("status") != "backup-verified":
            raise automation.AutomationError("INTEGRATION_BACKUP")
        operator.register_backup(result["backup"])
        operator.acknowledge_backup(result["backup"])
        journal.finish(status="completed", result=result)
        restore_journal = automation.Journal(config, "restore-check", config_sha)
        restore_operator = automation_runtime.Runtime(config, binding, runner, restore_journal)
        restored = restore_operator.restore_check()
        restore_journal.finish(status="completed", result=restored)
        evidence = {
            "format": 1,
            "status": "synthetic-backup-restore-verified",
            "operator_source_commit": revision,
            "app_source_commit": app_source,
            "backup": result["backup"],
            "restore": restored["integrity"],
            "authenticated_field_kinds": 3,
            "production_accessed": False,
            "elapsed_seconds": round(time.monotonic() - began, 3),
        }
        backup.publish_json(output / "integration-result.json", evidence)
        return evidence
    finally:
        for name in (client, setup, database):
            operator.remove_container(name)
        operator._remove_owned("network", network, journal.run_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--app-source", required=True)
    parser.add_argument("--age-keygen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_check(args.image, args.app_source, args.age_keygen, args.output.absolute())
    except Exception as failure:
        code = (
            failure.code
            if isinstance(failure, automation.AutomationError)
            else "INTEGRATION_FAILED"
        )
        print(json.dumps({"status": "failed", "code": code}))
        return 1
    print(
        json.dumps(
            {key: result[key] for key in ("status", "authenticated_field_kinds", "elapsed_seconds")}
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
