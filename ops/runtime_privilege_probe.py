"""Adversarial role drift checks in a disposable test cluster, before API startup."""

import argparse
import os
from pathlib import Path

from ops.backup import OperationError, connect, service_environment
from ops.database import verify_runtime


def main(service_file):
    env, database = service_environment(service_file)
    if (
        not database.startswith("sallimbook_ops_")
        or not database.endswith("_test")
        or os.environ.get("SALLIMBOOK_OPS_SYNTHETIC") != "1"
    ):
        raise RuntimeError("Dedicated synthetic role test required")
    assert verify_runtime()["status"] == "runtime-role-verified"
    cases = [
        (
            "GRANT INSERT ON alembic_version TO sallimbook_app",
            "REVOKE INSERT ON alembic_version FROM sallimbook_app",
        ),
        (
            "GRANT DELETE ON alembic_version TO sallimbook_app",
            "REVOKE DELETE ON alembic_version FROM sallimbook_app",
        ),
        (
            "GRANT TRUNCATE ON audit_events TO sallimbook_app",
            "REVOKE TRUNCATE ON audit_events FROM sallimbook_app",
        ),
        (
            "ALTER FUNCTION public.protect_document() OWNER TO sallimbook_app",
            "ALTER FUNCTION public.protect_document() OWNER TO sallimbook_admin",
        ),
        (
            "REVOKE SELECT ON documents FROM sallimbook_app",
            "GRANT SELECT ON documents TO sallimbook_app",
        ),
        (
            "CREATE TABLE public.ops_privilege_probe (id integer); "
            "REVOKE INSERT ON public.ops_privilege_probe FROM sallimbook_app",
            "DROP TABLE public.ops_privilege_probe",
        ),
        (
            "CREATE SEQUENCE public.ops_privilege_probe; "
            "REVOKE USAGE ON public.ops_privilege_probe FROM sallimbook_app",
            "DROP SEQUENCE public.ops_privilege_probe",
        ),
        (
            "CREATE SEQUENCE public.ops_privilege_probe; "
            "REVOKE SELECT ON public.ops_privilege_probe FROM sallimbook_app",
            "DROP SEQUENCE public.ops_privilege_probe",
        ),
    ]
    with connect(env) as conn:
        for grant, undo in cases:
            conn.execute(grant)
            try:
                try:
                    verify_runtime()
                except OperationError:
                    pass
                else:
                    raise AssertionError("Unsafe runtime role drift was accepted")
            finally:
                conn.execute(undo)
            assert verify_runtime()["status"] == "runtime-role-verified"
    print(
        "PASS: runtime verifier rejects Alembic INSERT/DELETE, audit TRUNCATE, "
        "immutable guard-function ownership, missing document/new-table/new-sequence grants"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-service-file", required=True, type=Path)
    main(parser.parse_args().admin_service_file)
