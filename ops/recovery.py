"""Prepare an isolated restore and verify recovery gates, without activating it."""

import argparse
import getpass
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from ops.backup import (
    OperationError,
    connect,
    digest,
    private_directory,
    publish_json,
    service_environment,
)

AUTH_REVOKE = {
    "registered_devices": "status = 'revoked', revoked_at = COALESCE(revoked_at, %s)",
    "auth_sessions": "revoked_at = COALESCE(revoked_at, %s)",
    "auth_credentials": "revoked_at = COALESCE(revoked_at, %s)",
    "invitations": "revoked_at = COALESCE(revoked_at, %s)",
    "refresh_tokens": "consumed_at = COALESCE(consumed_at, %s)",
    "auth_challenges": "consumed_at = COALESCE(consumed_at, %s)",
    "auth_step_up_grants": "consumed_at = COALESCE(consumed_at, %s)",
}


def write_receipt(path, value):
    publish_json(path, value)


def context(service_file, directory):
    directory = private_directory(directory)
    if not (directory / "QUARANTINE").is_file():
        raise OperationError("Quarantine marker required")
    restore = json.loads((directory / "restore.json").read_text())
    manifest = json.loads((directory / "backup-manifest.json").read_text())
    env, dbname = service_environment(service_file, restore=True)
    if restore["database"] != dbname or restore["backup_id"] != manifest["id"]:
        raise OperationError("Restore identity mismatch")
    return env, directory, restore, manifest


def prepare(service_file, directory, password_provider=None):
    """Only restored auth rows change. Vault/history/ciphertexts remain untouched."""
    from argon2.exceptions import VerifyMismatchError
    from sallimbook.identity.service import PASSWORD_HASHER

    env, directory, restored, manifest = context(service_file, directory)
    if (directory / "prepared.json").exists():
        raise OperationError(
            "Restore was already prepared; never silently reset it again"
        )
    if password_provider is None:
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise OperationError(
                "Password reset requires a private interactive terminal"
            )

        def password_provider(index):
            first = getpass.getpass(f"New account password for member {index}: ")
            second = getpass.getpass("Repeat new account password: ")
            if first != second:
                raise OperationError("Password confirmation differs")
            return first

    with connect(env) as conn:
        conn.execute("BEGIN")
        conn.execute("SET LOCAL lock_timeout = '5s'")
        # Prepared recovery has no serving API. Exclusive locks make an accidental
        # concurrent request unable to authenticate half-way through preparation.
        conn.execute(
            "LOCK TABLE users, household_members, registered_devices, auth_sessions, "
            "auth_credentials, invitations, refresh_tokens, auth_challenges, "
            "auth_step_up_grants IN ACCESS EXCLUSIVE MODE"
        )
        other = conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
            "AND pid <> pg_backend_pid() AND backend_type='client backend'"
        ).fetchone()[0]
        if other:
            raise OperationError("Disconnect all API and other database clients first")
        members = conn.execute(
            "SELECT u.id, u.password_hash, u.version FROM users u "
            "JOIN household_members m ON m.user_id=u.id "
            "WHERE m.status='active' AND u.disabled_at IS NULL ORDER BY m.slot"
        ).fetchall()
        if (
            len(members) != 2
            or conn.execute("SELECT count(*) FROM households").fetchone()[0] != 1
        ):
            raise OperationError(
                "Recovery requires the intended two active members and one household"
            )
        prepared = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        user_versions = {}
        for index, (user_id, old_hash, version) in enumerate(members, start=1):
            password = password_provider(index)
            if not isinstance(password, str) or not 15 <= len(password) <= 128:
                raise OperationError("New passwords must have 15 to 128 characters")
            try:
                if PASSWORD_HASHER.verify(old_hash, password):
                    raise OperationError(
                        "A different account password is required after restore"
                    )
            except VerifyMismatchError:
                pass
            encoded = PASSWORD_HASHER.hash(password)
            password = None
            conn.execute(
                "UPDATE users SET password_hash=%s, updated_at=%s, version=version+1 WHERE id=%s",
                (encoded, prepared, user_id),
            )
            user_versions[str(user_id)] = version + 1
        # Disabled users remain disabled. No old credential or token family becomes
        # usable after a restore. Rows are retained rather than erasing auth history.
        for table, assignments in AUTH_REVOKE.items():
            conn.execute(
                f"UPDATE {table} SET {assignments}, updated_at=%s, version=version+1",
                (prepared, prepared),
            )
        conn.execute("COMMIT")
    receipt = {
        "format": 1,
        "backup_id": manifest["id"],
        "database": restored["database"],
        "prepared_at": prepared.isoformat(),
        "user_versions": user_versions,
        "backup_manifest_sha256": digest(directory / "backup-manifest.json"),
        "auth_revoked": sorted(AUTH_REVOKE),
        "vault_policy": "rotate-before-promotion",
    }
    # A filesystem failure after commit is safe: quarantine remains, and preparation
    # can be repeated explicitly with new passwords if no receipt was published.
    write_receipt(directory / "prepared.json", receipt)
    return {"status": "prepared-quarantine", "backup_id": manifest["id"]}


def check_rotations(conn, baseline, prepared):
    failures = []
    states = conn.execute(
        "SELECT household_id,current_key_version,rotation_required FROM vault_states"
    ).fetchall()
    if not set(baseline).issubset({str(row[0]) for row in states}):
        failures.append("vault-household-set")
    if conn.execute(
        "SELECT count(*) FROM vault_versions WHERE state='staging'"
    ).fetchone()[0]:
        failures.append("unfinished-vault-rotation")
    if conn.execute(
        "SELECT count(*) FROM vault_share_offers WHERE state='pending'"
    ).fetchone()[0]:
        failures.append("pending-vault-share")
    for household, version, rotation_required in states:
        if version <= baseline.get(str(household), 0) or rotation_required:
            failures.append("fresh-vault-version")
        active = conn.execute(
            "SELECT activated_at FROM vault_versions WHERE household_id=%s "
            "AND key_version=%s AND state='current'",
            (household, version),
        ).fetchone()
        if not active or active[0] <= prepared:
            failures.append("fresh-vault-activation")
        members = conn.execute(
            "SELECT count(*) FROM household_members WHERE household_id=%s "
            "AND status='active'",
            (household,),
        ).fetchone()[0]
        ready = conn.execute(
            "SELECT count(*) FROM household_members m JOIN vault_memberships v "
            "ON v.household_id=m.household_id AND v.member_id=m.id AND v.status='active' "
            "JOIN vault_member_wrappings w ON w.household_id=m.household_id "
            "AND w.member_id=m.id AND w.key_version=%s AND w.state='current' "
            "WHERE m.household_id=%s AND m.status='active' AND w.created_at>%s",
            (version, household, prepared),
        ).fetchone()[0]
        if members != 2 or ready != members:
            failures.append("both-member-wrappings")
        recovery = conn.execute(
            "SELECT count(*) FROM vault_recovery_wrappings WHERE household_id=%s "
            "AND key_version=%s AND is_current AND created_at>%s",
            (household, version, prepared),
        ).fetchone()[0]
        if recovery != 1:
            failures.append("new-recovery-wrapping")
    return failures


def check_ciphertexts(conn, objects, keyring_file):
    from sallimbook.accounts.crypto import KeyRing, SealedNumber, decrypt_number
    from sallimbook.documents.storage import PrivateStore
    from sallimbook.insurance.crypto import decrypt_number as decrypt_policy

    keyring = KeyRing.load(keyring_file)
    store = PrivateStore(objects)
    counts = {"documents": 0, "account_numbers": 0, "policy_numbers": 0}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT household_id,id,storage_key,encryption_key_version,nonce,mime_type,size_bytes,"
            "checksum_sha256 FROM documents WHERE state='ready'"
        )
        names = [column.name for column in cur.description]
        while rows := cur.fetchmany(100):
            for row in rows:
                plaintext = store.read(
                    SimpleNamespace(**dict(zip(names, row, strict=True))), keyring
                )
                del plaintext
                counts["documents"] += 1
    for table, column, decrypt, counter in (
        (
            "financial_accounts",
            "account_number_ciphertext",
            decrypt_number,
            "account_numbers",
        ),
        (
            "insurance_policies",
            "policy_number_ciphertext",
            decrypt_policy,
            "policy_numbers",
        ),
    ):
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT household_id,id,number_key_version,number_nonce,{column},last_four "
                f"FROM {table} WHERE {column} IS NOT NULL"
            )
            while rows := cur.fetchmany(100):
                for (
                    household,
                    identifier,
                    version,
                    nonce,
                    ciphertext,
                    last_four,
                ) in rows:
                    plaintext = decrypt(
                        keyring,
                        household,
                        identifier,
                        SealedNumber(version, nonce, ciphertext),
                    )
                    if plaintext[-4:] != last_four:
                        raise OperationError("Field ciphertext suffix mismatch")
                    del plaintext
                    counts[counter] += 1
    return counts


ACKS = {
    "rpo_loss_accepted_by_both",
    "money_and_stock_reconciled",
    "deletion_and_membership_reviewed",
    "both_new_password_logins_verified",
    "both_vault_passwords_verified",
    "new_recovery_code_verified",
    "old_device_local_state_cleared",
    "old_server_and_node_offline",
    "private_recovery_access_verified",
    "fixtures_and_old_app_compatibility_verified",
}


def verify(service_file, directory, keyring_file, evidence_file):
    env, directory, restored, manifest = context(service_file, directory)
    prepared = json.loads((directory / "prepared.json").read_text())
    evidence = json.loads(Path(evidence_file).read_text())
    if (
        prepared["backup_id"] != manifest["id"]
        or prepared["database"] != restored["database"]
        or prepared["backup_manifest_sha256"]
        != digest(directory / "backup-manifest.json")
    ):
        raise OperationError("Preparation receipt does not match restore")
    if (
        set(evidence) != {"format", "backup_id", "acknowledgements", "evidence_sha256"}
        or evidence["format"] != 1
        or evidence["backup_id"] != manifest["id"]
        or set(evidence["acknowledgements"]) != ACKS
        or any(value is not True for value in evidence["acknowledgements"].values())
        or not isinstance(evidence["evidence_sha256"], str)
        or len(evidence["evidence_sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in evidence["evidence_sha256"])
    ):
        raise OperationError("Both members' recovery acceptance evidence is incomplete")
    epoch = datetime.fromisoformat(prepared["prepared_at"])
    with connect(env) as conn:
        conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        failures = []
        for table in AUTH_REVOKE:
            field = (
                "revoked_at"
                if table
                in {
                    "registered_devices",
                    "auth_sessions",
                    "auth_credentials",
                    "invitations",
                }
                else "consumed_at"
            )
            count = conn.execute(
                f"SELECT count(*) FROM {table} WHERE created_at<=%s AND {field} IS NULL",
                (epoch,),
            ).fetchone()[0]
            if count:
                failures.append("old-" + table)
        for user_id, minimum_version in prepared["user_versions"].items():
            row = conn.execute(
                "SELECT version,updated_at,disabled_at FROM users WHERE id=%s",
                (UUID(user_id),),
            ).fetchone()
            if (
                not row
                or row[0] < minimum_version
                or row[1] < epoch
                or row[2] is not None
            ):
                failures.append("new-account-passwords")
            if not conn.execute(
                "SELECT 1 FROM auth_sessions s JOIN registered_devices d ON d.id=s.device_id "
                "WHERE s.user_id=%s AND s.created_at>%s AND s.authenticated_at>%s "
                "AND d.created_at>%s AND d.status='active' AND d.revoked_at IS NULL "
                "AND s.revoked_at IS NULL LIMIT 1",
                (UUID(user_id), epoch, epoch, epoch),
            ).fetchone():
                failures.append("new-device-login")
        failures += check_rotations(conn, manifest["vault_max_versions"], epoch)
        counts = check_ciphertexts(conn, directory / "objects", keyring_file)
        conn.execute("COMMIT")
    if failures:
        raise OperationError(
            "Recovery gates failed: " + ",".join(sorted(set(failures)))
        )
    result = {
        "format": 1,
        "status": "ready-for-operator-review",
        "backup_id": manifest["id"],
        "verified_at": datetime.now(UTC).isoformat(),
        "ciphertexts_verified": counts,
        "acceptance_sha256": digest(Path(evidence_file)),
        "prepared_sha256": digest(directory / "prepared.json"),
    }
    write_receipt(directory / "recovery-check.json", result)
    # Do not remove QUARANTINE or start/rename a database. The report is an
    # observed instant, not a capability to promote a later modified database.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    verify_parser = sub.add_parser("verify")
    for child in (prep, verify_parser):
        child.add_argument("--service-file", type=Path, required=True)
        child.add_argument("--directory", type=Path, required=True)
    verify_parser.add_argument("--keyring-file", type=Path, required=True)
    verify_parser.add_argument("--evidence-file", type=Path, required=True)
    args = vars(parser.parse_args())
    command = args.pop("command")
    try:
        result = prepare(**args) if command == "prepare" else verify(**args)
    except OperationError as exc:
        raise SystemExit(str(exc)) from None
    except Exception:
        raise SystemExit(
            "Recovery failed. Keep quarantine; inspect private state with the operator."
        ) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
