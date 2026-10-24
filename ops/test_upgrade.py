"""Rehearse the runbook's schema upgrade and pre-update rollback on synthetic data.

A new disposable ``sallimbook-ops-smoke-*`` Compose project with no host ports, node or
real key. The old release migrates its own schema, seeds data through its HTTP API and
takes a backup with its own tool. The new image then runs the runbook's preflight
schema check and literal migration command, starts, and is rolled back with
``downgrade 0014_vault`` from the new image. The old release starts again, the schema is
upgraded once more and obligations are regenerated. Only this project is removed.
"""

import argparse
import json
import secrets
import subprocess
import tempfile
import types
from pathlib import Path
from uuid import uuid4

from ops.build_context import REVISION_LABEL
from ops.database import migration_command
from ops.deploy import render
from ops.preflight import database_report, verify_database_command, verify_image_details

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "Synthetic upgrade password only 2026!"
# Columns added after 0014 are left out so snapshots compare across the downgrade
# (0015 revoked_at, 0016 the two cleared_* columns, 0018 the two install_* columns), and
# manual_override, which 0015 normalizes.
NEW_COLUMNS = (
    "revoked_at",
    "cleared_link_version",
    "cleared_next_check_override",
    "install_key_hash",
    "install_session_id",
)
IGNORED_COLUMNS = ("manual_override", *NEW_COLUMNS)

CLIENT = """
import json, urllib.error, urllib.request
from datetime import date, timedelta
from uuid import uuid4

def call(method, path, value=None, token=None, version=None):
    headers = {"X-SallimBook-Native": "1", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if method == "POST":
        headers["Idempotency-Key"] = "synthetic-" + uuid4().hex
    if version is not None:
        headers["If-Match"] = '"%d"' % version
    data = None if value is None else json.dumps(value).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1" + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, None

def login():
    status, body = call("POST", "/auth/native/login", {
        "login_name": "upgrade_test", "password": PASSWORD,
        "device_label": "Synthetic upgrade native",
    })
    assert status == 200, status
    return body["access_token"]

def expect(status, wanted, label):
    if status != wanted:
        raise SystemExit("unexpected status for " + label + ": " + str(status))
"""

SEED = """
from sqlalchemy.orm import Session
from sallimbook.config import Settings
from sallimbook.core.database import make_engine
from sallimbook.identity import service
from sallimbook.identity.schemas import InvitationAcceptance

engine = make_engine(Settings(_env_file=None).database_url.get_secret_value())
with Session(engine) as session:
    invitation = service.create_bootstrap_invitation(
        session, "Synthetic upgrade household", "upgrade_test"
    )
    session.commit()
    service.accept_invitation(session, InvitationAcceptance(
        token=invitation.token, password=PASSWORD, display_name="Synthetic upgrade owner",
    ), "synthetic-upgrade")
engine.dispose()
token = login()
today = date.today()
status, rule = call("POST", "/recurring-rules", {
    "title": "합성 업그레이드 정기 비용", "category": "subscription", "amount_mode": "fixed",
    "expected_amount_krw": "33000", "economic_type": "expense", "frequency": "monthly",
    "anchor_date": (today + timedelta(days=7)).isoformat(),
    "effective_from": today.isoformat(),
}, token)
expect(status, 201, "rule")
status, generated = call("POST", "/obligations/generate", {
    "start_date": today.isoformat(), "end_date": (today + timedelta(days=150)).isoformat(),
    "rule_id": rule["id"],
}, token)
expect(status, 201, "generate")
rows = sorted((call("GET", "/obligations/" + item["id"], token=token)[1]
               for item in generated["items"]), key=lambda row: row["nominal_date"])
assert len(rows) >= 3, len(rows)
skipped, released = rows[0], rows[1]
status, _ = call("POST", "/obligations/" + skipped["id"] + "/skip",
                 {"reason": "합성 건너뛰기"}, token, skipped["version"])
expect(status, 200, "skip")
status, moved = call("POST", "/obligations/" + released["id"] + "/skip",
                     {"reason": "합성 건너뛰기"}, token, released["version"])
expect(status, 200, "skip second")
# The old release keeps manual_override after this; 0015 normalizes it away.
status, _ = call("POST", "/obligations/" + released["id"] + "/unskip",
                 {"reason": "합성 건너뛰기 해제"}, token, moved["version"])
expect(status, 200, "unskip")
status, appliance = call("POST", "/appliances", {"name": "합성 정수기"}, token)
expect(status, 201, "appliance")
status, stock = call("POST", "/consumables",
                     {"name": "합성 필터", "unit": "개", "low_stock_threshold": 1}, token)
expect(status, 201, "consumable")
status, _ = call("POST", "/consumables/" + stock["id"] + "/stock-movements", {
    "kind": "receipt", "quantity_delta": 3, "occurred_on": today.isoformat(),
}, token, stock["version"])
expect(status, 201, "receipt")
status, link = call("POST", "/appliance-consumables", {
    "appliance_id": appliance["id"], "consumable_id": stock["id"],
    "interval_unit": "months", "interval_count": 3,
}, token)
expect(status, 201, "link")
status, link = call("GET", "/appliance-consumables/" + link["id"], token=token)
expect(status, 200, "link read")
status, _ = call("POST", "/appliance-consumables/" + link["id"] + "/replacements", {
    "replaced_on": today.isoformat(), "quantity": 1, "link_version": link["version"],
    "clear_next_check_override": False,
}, token, link["stock_version"])
expect(status, 201, "replacement")
print(json.dumps({"rule": rule["id"], "skipped": skipped["id"], "released": released["id"],
                  "link": link["id"]}))
"""

REGENERATE = """
token = login()
today = date.today()
status, generated = call("POST", "/obligations/generate", {
    "start_date": today.isoformat(), "end_date": (today + timedelta(days=150)).isoformat(),
    "rule_id": SEEDED["rule"],
}, token)
expect(status, 201, "regenerate")
rows = {item["id"]: call("GET", "/obligations/" + item["id"], token=token)[1]
        for item in generated["items"]}
assert rows[SEEDED["skipped"]]["skipped"] and rows[SEEDED["skipped"]]["manual_override"]
assert not rows[SEEDED["released"]]["skipped"]
assert not rows[SEEDED["released"]]["manual_override"]
status, page = call("GET", "/appliance-consumables/" + SEEDED["link"] + "/replacements",
                    token=token)
expect(status, 200, "replacements")
assert len(page["items"]) == 1
print(json.dumps({"regenerated": len(rows)}))
"""

SNAPSHOT = """
SELECT c.relname,
  (xpath('/row/n/text()', query_to_xml(format(
     'SELECT count(*) AS n FROM public.%I', c.relname), false, true, '')))[1]::text,
  (xpath('/row/h/text()', query_to_xml(format(
     'SELECT md5(coalesce(string_agg(x, %L ORDER BY x), %L)) AS h FROM ('
     'SELECT (to_jsonb(t){ignored})::text AS x FROM public.%I t) s',
     ',', '', {names}, c.relname), false, true, '')))[1]::text
FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
  AND c.relname <> 'alembic_version'
ORDER BY c.relname
""".replace("{ignored}", " - %L" * len(IGNORED_COLUMNS)).replace(
    "{names}", ", ".join(f"'{name}'" for name in IGNORED_COLUMNS)
)


def run(command, *, stdin=None, timeout=300):
    result = subprocess.run(
        command, check=False, input=stdin, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode:
        # Synthetic-only stack; still keep infrastructure diagnostics short.
        print(result.stdout[-1500:])
        print(result.stderr[-1500:])
        raise RuntimeError("Isolated upgrade rehearsal command failed")
    return result.stdout


def old_render(revision, config):
    """Render the old release with that commit's own deploy.py, not today's renderer."""
    source = run(["git", "show", revision + ":ops/deploy.py"], timeout=30)
    module = types.ModuleType("sallimbook_old_deploy")
    exec(compile(source, "old-deploy.py", "exec"), module.__dict__)  # noqa: S102
    return module.render(config)["compose.json"]


def bech32_recipient(key):
    """A synthetic age X25519 recipient; its archive is never restored here."""
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    data, accumulator, bits = [], 0, 0
    for byte in key:
        accumulator, bits = (accumulator << 8) | byte, bits + 8
        while bits >= 5:
            bits -= 5
            data.append((accumulator >> bits) & 31)
    if bits:
        data.append((accumulator << (5 - bits)) & 31)

    def polymod(values):
        check = 1
        for value in values:
            top = check >> 25
            check = (check & 0x1FFFFFF) << 5 ^ value
            for index, generator in enumerate(
                (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
            ):
                check ^= generator if (top >> index) & 1 else 0
        return check

    prefix = [ord(c) >> 5 for c in "age"] + [0] + [ord(c) & 31 for c in "age"]
    remainder = polymod(prefix + data + [0] * 6) ^ 1
    checksum = [(remainder >> 5 * (5 - index)) & 31 for index in range(6)]
    return "age1" + "".join(charset[value] for value in data + checksum)


def label(image):
    inspected = json.loads(run(["docker", "image", "inspect", image], timeout=30))[0]
    revision = (inspected.get("Config", {}).get("Labels") or {}).get(REVISION_LABEL)
    if not revision:
        raise RuntimeError("Source-labelled application image required")
    verify_image_details([inspected], revision=revision, role="api")
    return inspected["Id"], revision


def main(old_image, new_image):
    old_id, old_revision = label(old_image)
    new_id, new_revision = label(new_image)
    if old_revision == new_revision:
        raise RuntimeError("Two different releases are required")
    project = "sallimbook-ops-smoke-" + uuid4().hex[:12]
    network = project + "_database"
    with tempfile.TemporaryDirectory(prefix=project + "-") as temporary:
        directory = Path(temporary)
        password, admin_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        database = "sallimbook_ops_" + uuid4().hex[:12] + "_test"

        def private(name, text):
            path = directory / name
            path.write_text(text)
            path.chmod(0o600)
            return path

        app_env = private(
            "synthetic.env",
            f"SALLIMBOOK_DATABASE_URL=postgresql+psycopg://sallimbook_app:{password}"
            f"@db:5432/{database}\n",
        )
        # The runbook's 0600 admin env file for the one-off migration container.
        admin_env = private(
            "synthetic-migration.env",
            f"SALLIMBOOK_DATABASE_URL=postgresql+psycopg://sallimbook_admin:{admin_password}"
            f"@db:5432/{database}\n",
        )
        init_env = private(
            "synthetic-init.env",
            f"OPS_DB_PASSWORD={password}\nOPS_ADMIN_DB_PASSWORD={admin_password}\n"
            f"OPS_DATABASE={database}\n",
        )

        def config(image_id, revision):
            return {
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

        old_config = config(old_id, old_revision)
        init = (
            "import base64,json,os,pathlib\n"
            "for name in ['/run/secrets','/srv/documents','/run/scanner','/run/operator',"
            "'/srv/backups']:\n"
            " p=pathlib.Path(name); p.mkdir(exist_ok=True); p.chmod(0o700);"
            " os.chown(p,10001,10001)\n"
            "def put(name, text, owner=10001):\n"
            " p=pathlib.Path(name); p.write_text(text); p.chmod(0o600); os.chown(p,owner,owner)\n"
            "put('/run/secrets/field-keyring.json', json.dumps({'schema_version':1,"
            "'active_key_version':1,'keys':{'1':base64.b64encode(bytes(range(32))).decode()}}))\n"
            "put('/run/secrets/db-admin-password', os.environ['OPS_ADMIN_DB_PASSWORD'], 0)\n"
            "put('/run/operator/app-db-password', os.environ['OPS_DB_PASSWORD'])\n"
            "for name, user, key in (('admin-service.conf','sallimbook_admin',"
            "'OPS_ADMIN_DB_PASSWORD'), "
            "('backup-service.conf','sallimbook_app','OPS_DB_PASSWORD')):\n"
            " put('/run/operator/'+name, '[sallimbook]\\nhost=db\\nport=5432\\nuser='+user+"
            "'\\nsslmode=disable\\ndbname='+os.environ['OPS_DATABASE']+'\\npassword='"
            "+os.environ[key]+'\\n')\n"
            "put('/run/operator/deployment.json', os.environ['OPS_DEPLOYMENT'])\n"
        )
        deployment_line = "OPS_DEPLOYMENT=" + json.dumps(old_config) + "\n"
        init_env.write_text(init_env.read_text() + deployment_line)

        def services(rendered, image_id, names):
            result = {name: rendered["services"][name] for name in ("db", *names)}
            for name in names:
                result[name]["image"] = image_id
                result[name]["restart"] = "no"
                result[name]["healthcheck"]["interval"] = "1s"
                result[name]["healthcheck"]["retries"] = 1
            api = result["api"]
            api["env_file"] = [str(app_env)]
            api["healthcheck"]["start_period"] = "15s"
            api["environment"].update(
                SALLIMBOOK_ENVIRONMENT="test", SALLIMBOOK_OPS_SYNTHETIC="1"
            )
            api["volumes"] = [
                "synthetic_secrets:/run/secrets:ro",
                "synthetic_documents:/srv/documents",
                "scanner_socket:/run/scanner:ro",
            ] + (["inspector_socket:/run/inspector:ro"] if "inspector" in names else [])
            db = result["db"]
            db["environment"]["POSTGRES_DB"] = database
            db["healthcheck"]["test"][-1] = database
            db["volumes"] = ["db_data:/var/lib/postgresql", "synthetic_secrets:/run/secrets:ro"]
            db["restart"] = "no"
            db["command"][2] = "cluster_name=" + project
            return result

        def tool(image_id, command, *, volumes=(), env_file=admin_env):
            return {
                "image": image_id,
                "user": "10001:10001",
                "read_only": True,
                "networks": ["database"],
                "env_file": [str(env_file)],
                "volumes": list(volumes),
                "profiles": ["tools"],
                "command": command,
            }

        old = services(old_render(old_revision, old_config), old_id, ("scanner", "api"))
        old["init"] = {
            "image": new_id,
            "user": "0:0",
            "network_mode": "none",
            "restart": "no",
            "env_file": [str(init_env)],
            "volumes": [
                "synthetic_secrets:/run/secrets",
                "synthetic_documents:/srv/documents",
                "scanner_socket:/run/scanner",
                "operator_secrets:/run/operator",
                "backups:/srv/backups",
            ],
            "entrypoint": ["python", "-c", init],
            "profiles": ["tools"],
        }
        old["migrate"] = tool(
            old_id, ["alembic", "-c", "/opt/sallimbook/alembic.ini", "upgrade", "head"]
        )
        old["provision"] = tool(
            old_id,
            ["python", "-m", "ops.database", "provision",
             "--admin-service-file", "/run/operator/admin-service.conf",
             "--application-password-file", "/run/operator/app-db-password"],
            volumes=["operator_secrets:/run/operator:ro"],
        )
        recipient = bech32_recipient(secrets.token_bytes(32))
        old["backup"] = tool(
            old_id,
            ["python", "-m", "ops.backup", "create",
             "--service-file", "/run/operator/backup-service.conf",
             "--documents", "/srv/documents", "--destination", "/srv/backups",
             "--recipient", recipient, "--source-commit", old_revision,
             "--deployment-manifest", "/run/operator/deployment.json"],
            volumes=["operator_secrets:/run/operator:ro", "synthetic_documents:/srv/documents",
                     "backups:/srv/backups"],
            env_file=app_env,
        )
        old["backup"]["tmpfs"] = ["/tmp"]
        new = services(render(config(new_id, new_revision))["compose.json"], new_id,
                       ("scanner", "inspector", "api"))
        volumes = {name: {} for name in (
            "db_data", "scanner_socket", "inspector_socket", "synthetic_secrets",
            "synthetic_documents", "operator_secrets", "backups",
        )}
        networks = {"app": {"internal": True}, "database": {"internal": True}}
        files = {}
        for name, value in (("old", old), ("new", new)):
            files[name] = directory / (name + ".json")
            files[name].write_text(json.dumps(
                {"name": project, "services": value, "networks": networks, "volumes": volumes}
            ))

        def compose(release, *arguments, **options):
            return run(["docker", "compose", "-p", project, "-f", str(files[release]),
                        *arguments], **options)

        def python_in_api(release, script, seeded=None):
            prelude = "PASSWORD = " + json.dumps(PASSWORD) + "\n"
            if seeded is not None:
                prelude += "SEEDED = " + json.dumps(seeded) + "\n"
            output = compose(release, "exec", "-T", "api", "python", "-",
                             stdin=prelude + CLIENT + script)
            return json.loads(output.strip().splitlines()[-1])

        def snapshot():
            output = compose("new", "exec", "-T", "db", "psql", "-U", "sallimbook_admin",
                             "-d", database, "-AtF", "\t", "-c", SNAPSHOT)
            tables = {}
            for line in output.strip().splitlines():
                name, count, digest = line.split("\t")
                tables[name] = (int(count), digest)
            overrides = compose("new", "exec", "-T", "db", "psql", "-U", "sallimbook_admin",
                                "-d", database, "-At", "-c",
                                "SELECT id, manual_override FROM scheduled_obligations "
                                "ORDER BY id")
            return tables, dict(line.split("|") for line in overrides.split())

        def same(left, right, message):
            if left != right:
                # Synthetic table names and row counts only.
                print({name: (left.get(name, ("-",))[0], right.get(name, ("-",))[0])
                       for name in set(left) | set(right) if left.get(name) != right.get(name)})
                raise AssertionError(message)

        def schema(image_id):
            return database_report(run(verify_database_command(network, app_env, image_id)))

        def healthy(release, names):
            for name in names:
                identifier = compose(release, "ps", "-q", name).strip()
                state = json.loads(run(["docker", "inspect", identifier]))[0]
                assert state["State"]["Health"]["Status"] == "healthy", name

        try:
            # Old release as deployed: own schema, roles, data and backup.
            compose("old", "run", "--rm", "init")
            compose("old", "up", "-d", "--wait", "db", "scanner")
            compose("old", "run", "--rm", "--no-deps", "migrate")
            compose("old", "run", "--rm", "--no-deps", "provision")
            compose("old", "up", "-d", "--wait", "--wait-timeout", "120", "api")
            seeded = python_in_api("old", SEED)
            backed_up = compose("old", "run", "--rm", "--no-deps", "backup")
            assert json.loads(backed_up.strip().splitlines()[-1])
            listing = compose("old", "run", "--rm", "--no-deps", "--entrypoint", "python",
                              "backup", "-c",
                              "import json, os; print(json.dumps(os.listdir('/srv/backups')))")
            names = json.loads(listing.strip().splitlines()[-1])
            assert any(name.endswith(".complete.json") for name in names), names
            before, before_overrides = snapshot()
            assert before_overrides[seeded["released"]] == "t"

            # Maintenance window: stop the old app, check, migrate, start the new image.
            compose("old", "stop", "api", "scanner")
            assert schema(new_id) == "upgrade-required"
            run(migration_command(network, admin_env, new_id, "upgrade", "head"))
            assert schema(new_id) == "current"
            compose("new", "up", "-d", "--wait", "--wait-timeout", "180",
                    "scanner", "inspector", "api")
            healthy("new", ("api", "scanner", "inspector", "db"))
            upgraded, upgraded_overrides = snapshot()
            same(before, upgraded, "Upgrade changed rows beyond the documented fields")
            changed = {key for key in before_overrides
                       if before_overrides[key] != upgraded_overrides[key]}
            assert changed == {seeded["released"]}, changed

            # Rollback before any phone update: downgrade with the new image's scripts.
            compose("new", "stop", "api", "inspector", "scanner")
            run(migration_command(network, admin_env, new_id, "downgrade", "0014_vault"))
            assert schema(new_id) == "upgrade-required"
            rolled_back, rolled_overrides = snapshot()
            same(before, rolled_back, "Rollback did not restore the old rows")
            # Documented loss: the stale override that 0015 cleared stays cleared.
            assert rolled_overrides == upgraded_overrides
            compose("old", "up", "-d", "--wait", "--wait-timeout", "120",
                    "--remove-orphans", "scanner", "api")
            healthy("old", ("api", "scanner", "db"))

            # Upgrade again, then regenerate the open schedule.
            compose("old", "stop", "api", "scanner")
            run(migration_command(network, admin_env, new_id, "upgrade", "head"))
            assert schema(new_id) == "current"
            compose("new", "up", "-d", "--wait", "--wait-timeout", "180",
                    "scanner", "inspector", "api")
            healthy("new", ("api", "scanner", "inspector", "db"))
            regenerated = python_in_api("new", REGENERATE, seeded)
            print(
                "PASS: old " + old_revision[:7] + " seed/backup, new " + new_revision[:7]
                + " preflight upgrade-required, migration, start, rollback to 0014_vault"
                " with the old release healthy (row counts and hashes kept; one stale"
                " manual_override stays cleared), re-upgrade and regeneration of "
                + str(regenerated["regenerated"]) + " obligations; no ports, node or real key"
            )
        finally:
            # Only this unique project and its newly created synthetic volumes.
            # Both files: tool-only volumes (backups, operator secrets) live in "old".
            run(["docker", "compose", "-p", project, "-f", str(files["new"]),
                 "down", "--volumes", "--remove-orphans"])
            # Volumes used only by "old" tool services are not removed by down.
            for volume in run(["docker", "volume", "ls", "-q", "--filter",
                               "label=com.docker.compose.project=" + project]).split():
                run(["docker", "volume", "rm", volume])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-image", required=True)
    parser.add_argument("--new-image", required=True)
    arguments = parser.parse_args()
    main(arguments.old_image, arguments.new_image)
