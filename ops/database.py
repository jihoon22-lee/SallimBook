"""Dedicated PostgreSQL roles; no application schema changes or password generation."""

import argparse
import json
import os
import re
from pathlib import Path

from ops.backup import OperationError, connect, private_file, service_environment

ADMIN_ROLE = "sallimbook_admin"
APPLICATION_ROLE = "sallimbook_app"


def verify_role(conn):
    row = conn.execute(
        "SELECT current_user,rolsuper,rolcreatedb,rolcreaterole,"
        "rolreplication,rolbypassrls,rolcanlogin "
        "FROM pg_roles WHERE rolname=current_user"
    ).fetchone()
    if row != (APPLICATION_ROLE, False, False, False, False, False, True):
        raise OperationError("Runtime database role attributes are unsafe")
    if conn.execute(
        "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member "
        "WHERE r.rolname=current_user"
    ).fetchone()[0]:
        raise OperationError("Runtime role must not inherit another database role")
    privileges = conn.execute(
        "SELECT has_schema_privilege('public','CREATE'), "
        "has_database_privilege(current_database(),'CREATE'), "
        "has_database_privilege(current_database(),'TEMP'), "
        "has_table_privilege('public.alembic_version',"
        "'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN'), "
        "EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f') "
        "AND has_table_privilege(c.oid,'TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')), "
        "EXISTS (SELECT 1 FROM pg_namespace n WHERE has_schema_privilege(n.oid,'CREATE'))"
    ).fetchone()
    if any(privileges):
        raise OperationError("Runtime database role has schema/owner-level privileges")
    # Ownership dependencies cover pg_class, pg_proc (including guard functions),
    # pg_namespace, pg_type, pg_database and other owned objects, not a sample table.
    owners = conn.execute(
        "WITH me AS (SELECT oid FROM pg_roles WHERE rolname=current_user) "
        "SELECT EXISTS (SELECT 1 FROM pg_shdepend d,me WHERE d.refclassid='pg_authid'::regclass "
        "AND d.refobjid=me.oid AND d.deptype='o') OR "
        "EXISTS (SELECT 1 FROM pg_class,me WHERE relowner=me.oid) OR "
        "EXISTS (SELECT 1 FROM pg_proc,me WHERE proowner=me.oid) OR "
        "EXISTS (SELECT 1 FROM pg_namespace,me WHERE nspowner=me.oid) OR "
        "EXISTS (SELECT 1 FROM pg_type,me WHERE typowner=me.oid) OR "
        "EXISTS (SELECT 1 FROM pg_database,me WHERE datdba=me.oid)"
    ).fetchone()[0]
    if owners:
        raise OperationError("Runtime database role must not own application objects")
    required = conn.execute(
        "SELECT has_schema_privilege('public','USAGE'), "
        "has_database_privilege(current_database(),'CONNECT'), "
        "has_table_privilege('alembic_version','SELECT'), "
        "(SELECT bool_and(has_table_privilege('users',privilege)) FROM "
        "unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) AS privilege)"
    ).fetchone()
    if not all(required):
        raise OperationError(
            "Runtime database role lacks required application privileges"
        )
    return {
        "status": "runtime-role-verified",
        "role": APPLICATION_ROLE,
        "schema_ddl": False,
        "truncate": False,
        "superuser": False,
    }


def provision(admin_service_file, application_password_file):
    from psycopg import sql

    password = private_file(application_password_file).read_text().removesuffix("\n")
    if not 24 <= len(password) <= 256 or any(ord(char) < 32 for char in password):
        raise OperationError(
            "A private application DB password of at least 24 characters is required"
        )
    env, database = service_environment(admin_service_file)
    with connect(env) as conn:
        current, owner, cluster = conn.execute(
            "SELECT current_user,pg_get_userbyid(datdba), "
            "current_setting('cluster_name') FROM pg_database WHERE datname=current_database()"
        ).fetchone()
        if (
            current != ADMIN_ROLE
            or owner != ADMIN_ROLE
            or not re.fullmatch(
                r"sallimbook-(?:prod|staging|ops-smoke-[0-9a-f]{12})", cluster
            )
        ):
            raise OperationError(
                "Dedicated owner/migration role and cluster identity required"
            )
        databases = {
            row[0]
            for row in conn.execute(
                "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname<>'postgres'"
            )
        }
        if databases != {database}:
            raise OperationError(
                "Role provisioning requires a dedicated single-application cluster"
            )
        if conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname=%s", (APPLICATION_ROLE,)
        ).fetchone():
            raise OperationError(
                "Runtime role already exists; nothing changed, use verify-runtime"
            )
        if not conn.execute("SELECT version_num FROM alembic_version").fetchone():
            raise OperationError("Run reviewed migrations with the admin role first")
        conn.execute("BEGIN")
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL log_statement='none'")
        conn.execute("SET LOCAL log_min_error_statement='panic'")
        conn.execute("SET LOCAL log_parameter_max_length=0")
        conn.execute("SET LOCAL log_parameter_max_length_on_error=0")
        conn.execute("SELECT pg_advisory_xact_lock(91544042505045)")
        # libpq's standard SCRAM implementation keeps the clear password out of
        # SQL statements, server command logs, and activity views.
        verifier = conn.pgconn.encrypt_password(
            password.encode(), APPLICATION_ROLE.encode(), b"scram-sha-256"
        ).decode()
        password = None
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD {}"
            ).format(sql.Identifier(APPLICATION_ROLE), sql.Literal(verifier))
        )
        conn.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                sql.Identifier(database)
            )
        )
        conn.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(APPLICATION_ROLE)
            )
        )
        conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        conn.execute("GRANT USAGE ON SCHEMA public TO sallimbook_app")
        conn.execute(
            "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO sallimbook_app"
        )
        conn.execute(
            "REVOKE INSERT,UPDATE,DELETE ON alembic_version FROM sallimbook_app"
        )
        conn.execute(
            "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO sallimbook_app"
        )
        conn.execute("REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC")
        conn.execute(
            "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO sallimbook_app"
        )
        conn.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE sallimbook_admin IN SCHEMA public "
            "GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO sallimbook_app"
        )
        conn.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE sallimbook_admin IN SCHEMA public "
            "GRANT USAGE,SELECT ON SEQUENCES TO sallimbook_app"
        )
        conn.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE sallimbook_admin "
            "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
        )
        conn.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE sallimbook_admin IN SCHEMA public "
            "GRANT EXECUTE ON FUNCTIONS TO sallimbook_app"
        )
        conn.execute("COMMIT")
    return {
        "status": "runtime-role-provisioned",
        "role": APPLICATION_ROLE,
        "migration_role": ADMIN_ROLE,
    }


def verify_runtime():
    import psycopg
    from sallimbook.config import Settings
    from sqlalchemy.engine import make_url

    settings = Settings(_env_file=None)
    url = make_url(settings.database_url.get_secret_value())
    if (
        url.drivername != "postgresql+psycopg"
        or url.host != "db"
        or url.port != 5432
        or url.username != APPLICATION_ROLE
        or not re.fullmatch(r"sallimbook_[a-z0-9_]+", url.database)
        or url.query
        or any(key.startswith("PG") and value for key, value in os.environ.items())
    ):
        raise OperationError("Dedicated application database settings required")
    with psycopg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname=url.database,
        sslmode="disable",
        connect_timeout=5,
        options="-c default_transaction_read_only=on -c search_path=public",
    ) as conn:
        return verify_role(conn)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    provision_parser = sub.add_parser("provision")
    provision_parser.add_argument("--admin-service-file", type=Path, required=True)
    provision_parser.add_argument(
        "--application-password-file", type=Path, required=True
    )
    sub.add_parser("verify-runtime")
    args = vars(parser.parse_args())
    operation = args.pop("command")
    try:
        report = provision(**args) if operation == "provision" else verify_runtime()
    except Exception:
        raise SystemExit(
            "Database role check/provisioning failed; inspect only in a private operator session."
        ) from None
    print(json.dumps(report, sort_keys=True))
