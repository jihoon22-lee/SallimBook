"""Synthetic operation boundaries; never starts a service or accesses a real account."""

import io
import json
import os
import re
import stat
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from ops import backup, build_context, database, deploy, health, preflight, recovery, release


def config():
    return {
        "format": 1,
        "project": "sallimbook-staging",
        "fqdn": "synthetic.example.ts.net",
        "certificate_sha256": ":".join(["AB"] * 32),
        "api_image": "example.invalid/sallimbook/api:0.1.0@sha256:" + "1" * 64,
        "web_image": "example.invalid/sallimbook/web:0.1.0@sha256:" + "2" * 64,
        "runtime_directory": "/srv/sallimbook/sallimbook-staging",
        "version_code": 2,
        "version_name": "0.1.1",
        "source_commit": "a" * 40,
    }


class DeploymentTests(unittest.TestCase):
    def test_private_caddy_renders_every_security_header_once(self):

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "rendered"
            deploy.write_config(config(), output)
            caddyfile = (output / "private.Caddyfile").read_text()
        names = [name for name, _ in deploy.PRIVATE_WEB_HEADERS]
        self.assertEqual(
            names,
            [
                "Content-Security-Policy",
                "Strict-Transport-Security",
                "X-Frame-Options",
                "X-Content-Type-Options",
                "Referrer-Policy",
            ],
        )
        for name, value in deploy.PRIVATE_WEB_HEADERS:
            line = re.compile(rf'^\s*header (@\w+ )?{name} "{re.escape(value)}"$', re.MULTILINE)
            self.assertEqual(len(line.findall(caddyfile)), 1, name)
        csp = dict(deploy.PRIVATE_WEB_HEADERS)["Content-Security-Policy"]
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("script-src 'self'", csp)
        # API responses keep their own content headers; page-only headers skip /api/*.
        self.assertIn("@page not path /api/*", caddyfile)
        self.assertIn("header @page Content-Security-Policy", caddyfile)

    def test_wrong_host_is_rejected_by_the_first_handle(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "rendered"
            deploy.write_config(config(), output)
            caddyfile = (output / "private.Caddyfile").read_text()
        # A top-level respond is ordered after every handle, so the catch-all handle
        # would answer first. The 421 must be a handle written before all others.
        self.assertNotIn("respond @wrong_host", caddyfile)
        self.assertIn("@wrong_host not host synthetic.example.ts.net", caddyfile)
        handles = re.findall(r"^    handle( \S+)? \{$", caddyfile, re.MULTILINE)
        self.assertEqual(handles[0].strip(), "@wrong_host")
        self.assertIn("    handle @wrong_host {\n        respond 421\n    }\n", caddyfile)
        self.assertLess(
            caddyfile.index("handle @wrong_host"), caddyfile.index("handle @apk"), caddyfile
        )
        self.assertLess(
            caddyfile.index("handle @wrong_host"), caddyfile.index("handle /api/*"), caddyfile
        )

    def test_self_setup_is_an_explicit_manifest_opt_in(self):
        original = config()
        disabled = deploy.render(original)
        identity_key = "SALLIMBOOK_SELF_SETUP_IDENTITY_SHA256"
        proxy_key = "SALLIMBOOK_SELF_SETUP_PROXY_HOST"
        for service in disabled["compose.json"]["services"].values():
            self.assertNotIn(identity_key, service.get("environment", {}))
            self.assertNotIn(proxy_key, service.get("environment", {}))
        self.assertEqual(original, config())
        for digest in ("ab" * 32, "AB" * 32):
            enabled = deploy.render({**original, "setup_identity_sha256": digest})
            services = enabled["compose.json"]["services"]
            environment = services["api"]["environment"]
            self.assertEqual(environment[identity_key], digest.lower())
            self.assertEqual(environment[proxy_key], "node")
            for name, service in services.items():
                if name != "api":
                    self.assertNotIn(identity_key, service.get("environment", {}))
                    self.assertNotIn(proxy_key, service.get("environment", {}))
            for name in ("public.Caddyfile", "private.Caddyfile", "node/serve.json",
                         "android-public.json"):
                self.assertEqual(enabled[name], disabled[name])

    def test_self_setup_rejects_invalid_identity_and_proxy_override(self):
        for value in (None, True, 123, [], "", "a" * 63, "a" * 65, "g" * 64,
                      "a" * 64 + "\n", " " + "a" * 64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                deploy.render({**config(), "setup_identity_sha256": value})
        with self.assertRaises(ValueError):
            deploy.render({**config(), "setup_identity_sha256": "a" * 64,
                           "setup_proxy_host": "attacker"})

    def test_self_setup_trusts_only_node_namespace_without_forwarded_ip(self):
        rendered = deploy.render({**config(), "setup_identity_sha256": "a" * 64})
        compose = rendered["compose.json"]
        services = compose["services"]
        self.assertEqual(services["web"]["network_mode"], "service:node")
        self.assertEqual(services["public"]["network_mode"], "service:node")
        self.assertEqual(services["node"]["networks"], ["edge", "app"])
        self.assertEqual(services["api"]["networks"], ["app", "database"])
        self.assertEqual(compose["networks"]["app"], {"internal": True})
        self.assertIn("--no-proxy-headers", services["api"]["command"])
        for service in services.values():
            self.assertNotIn("ports", service)
            self.assertNotIn("extra_hosts", service)
        for name in ("public.Caddyfile", "private.Caddyfile"):
            self.assertIn("bind 127.0.0.1", rendered[name])
        self.assertIn("header_up -Forwarded", rendered["private.Caddyfile"])
        self.assertIn("header_up -X-Forwarded-For", rendered["private.Caddyfile"])
        self.assertNotIn("reverse_proxy", rendered["public.Caddyfile"])
        self.assertEqual(rendered["node/serve.json"]["AllowFunnel"],
                         {config()["fqdn"] + ":443": True})
        self.assertEqual(rendered["node/serve.json"]["Web"][config()["fqdn"] + ":8443"],
                         {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8080"}}})

    def test_self_setup_environment_cannot_bypass_manifest_or_drift_check(self):
        password = "synthetic-runtime-password-only"
        values = {"SALLIMBOOK_DATABASE_URL":
                  f"postgresql+psycopg://sallimbook_app:{password}@db:5432/sallimbook_prod"}
        for key in ("SALLIMBOOK_SELF_SETUP_IDENTITY_SHA256", "SALLIMBOOK_SELF_SETUP_PROXY_HOST"):
            with self.subTest(key=key), self.assertRaisesRegex(
                backup.OperationError, "Unexpected runtime environment"
            ):
                preflight.validate_database_settings({**values, key: "forged"}, password)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "rendered"
            deploy.write_config({**config(), "setup_identity_sha256": "a" * 64}, output)
            path = output / "compose.json"
            compose = json.loads(path.read_text())
            compose["services"]["api"]["environment"]["SALLIMBOOK_SELF_SETUP_PROXY_HOST"] = "api"
            path.write_text(json.dumps(compose))
            with patch.object(preflight, "private_file") as secret_read, self.assertRaisesRegex(
                backup.OperationError, "configuration drift"
            ):
                preflight.check(output)
            secret_read.assert_not_called()

    def test_public_mounts_remain_readable_under_strict_umask(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "rendered"
            previous = os.umask(0o077)
            try:
                deploy.write_config(config(), output)
            finally:
                os.umask(previous)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
            self.assertEqual(list((output / "downloads").iterdir()), [])
            for path in output.rglob("*"):
                self.assertEqual(
                    stat.S_IMODE(path.stat().st_mode), 0o755 if path.is_dir() else 0o644
                )

    def test_apk_download_exists_only_on_private_exact_route(self):
        files = deploy.render(config())
        self.assertIn("path /downloads/SallimBook.apk", files["private.Caddyfile"])
        self.assertIn("method GET HEAD", files["private.Caddyfile"])
        self.assertIn("@other_downloads path /downloads /downloads/*", files["private.Caddyfile"])
        self.assertNotIn("downloads", files["public.Caddyfile"])
        services = files["compose.json"]["services"]
        self.assertIn("./downloads:/srv/downloads:ro", services["web"]["volumes"])
        for name, service in services.items():
            if name != "web":
                self.assertFalse(any("downloads" in path for path in service.get("volumes", [])))

    def test_image_source_revision_and_role_must_match_manifest(self):
        for role in ("api", "web"):
            labels = {build_context.REVISION_LABEL: "a" * 40, build_context.ROLE_LABEL: role}
            details = [{"Architecture": "amd64", "Os": "linux", "Config": {"Labels": labels}}]
            preflight.verify_image_details(details, revision="a" * 40, role=role)
            for invalid in (
                {},
                {**labels, build_context.REVISION_LABEL: "b" * 40},
                {**labels, build_context.ROLE_LABEL: "web" if role == "api" else "api"},
            ):
                with self.subTest(role=role, labels=invalid), self.assertRaises(
                    backup.OperationError
                ):
                    preflight.verify_image_details(
                        [{**details[0], "Config": {"Labels": invalid}}],
                        revision="a" * 40, role=role,
                    )

    def test_source_revision_is_literal_in_both_generated_image_contexts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template"
            template.write_text("FROM synthetic.invalid/base:fixed\n")
            for role in ("api", "web"):
                directory = root / role
                directory.mkdir()
                build_context.write_image_source(directory, template, "a" * 40, role)
                self.assertEqual(
                    json.loads((directory / "source-revision.json").read_text()),
                    {"source_commit": "a" * 40, "image_role": role},
                )
                dockerfile = (directory / "Dockerfile").read_text()
                self.assertIn(f'{build_context.REVISION_LABEL}="' + "a" * 40 + '"', dockerfile)
                self.assertIn(f'{build_context.ROLE_LABEL}="{role}"', dockerfile)
                self.assertNotIn("ARG", dockerfile)

    def test_container_health_requires_scanner_inspector_and_database_readiness(self):
        with (
            patch.object(health, "scanner_ready") as scanner,
            patch.object(health, "inspector_ready") as inspector,
            patch.object(health.urllib.request, "urlopen") as http,
        ):
            response = MagicMock(status=200)
            http.return_value.__enter__.return_value = response
            health.check("inspector")
            inspector.assert_called_once()
            scanner.assert_not_called()
            http.assert_not_called()
            inspector.reset_mock()
            health.check("scanner")
            inspector.assert_not_called()
            http.assert_not_called()
            health.check("api")
            inspector.assert_called_once()
            http.assert_called_once()
            for reason in ("scanner-down", "scanner-stale"):
                scanner.side_effect = RuntimeError(reason)
                http.reset_mock()
                for mode in ("scanner", "api"):
                    with self.subTest(reason=reason, mode=mode), self.assertRaises(RuntimeError):
                        health.check(mode)
                http.assert_not_called()
            scanner.side_effect = None
            inspector.side_effect = RuntimeError("inspector-down")
            http.reset_mock()
            for mode in ("inspector", "api"):
                with self.subTest(mode=mode), self.assertRaises(RuntimeError):
                    health.check(mode)
            http.assert_not_called()
            inspector.side_effect = None
            response.status = 503
            with self.assertRaises(RuntimeError):
                health.check("api")

    def test_no_host_resources_or_public_api_upstream(self):
        rendered = deploy.render(config())
        compose = rendered["compose.json"]
        self.assertEqual(compose["services"]["node"]["logging"], {"driver": "none"})
        self.assertEqual(
            compose["services"]["api"]["depends_on"]["scanner"]["condition"], "service_healthy"
        )
        for role in ("api", "scanner", "inspector"):
            self.assertEqual(
                compose["services"][role]["healthcheck"]["test"],
                ["CMD", "python", "-m", "ops.health", role],
            )
        for service in compose["services"].values():
            self.assertNotIn("ports", service)
            self.assertNotIn("container_name", service)
            self.assertNotEqual(service.get("network_mode"), "host")
            self.assertNotIn("privileged", service)
            self.assertNotIn("cap_add", service)
            self.assertNotIn("devices", service)
        self.assertEqual(compose["networks"]["database"], {"internal": True})
        self.assertNotIn("reverse_proxy", rendered["public.Caddyfile"])
        public = compose["services"]["public"]
        self.assertEqual(public["image"], config()["web_image"])
        self.assertEqual(len(public["volumes"]), 2)
        self.assertNotIn("env_file", public)
        self.assertEqual(
            rendered["node/serve.json"]["AllowFunnel"],
            {"synthetic.example.ts.net:443": True},
        )

    def test_public_identity_is_consistent(self):
        rendered = deploy.render(config())
        public = rendered["android-public.json"]
        env = rendered["compose.json"]["services"]["api"]["environment"]
        self.assertEqual(
            json.loads(env["SALLIMBOOK_WEBAUTHN_WEB_ORIGINS"]), [public["api_origin"]]
        )
        self.assertEqual(
            json.loads(env["SALLIMBOOK_WEBAUTHN_NATIVE_ORIGINS"]),
            [public["native_origin"]],
        )
        self.assertEqual(public["rp_id"], config()["fqdn"])
        self.assertEqual(public["application_id"], deploy.APP_ID)
        self.assertNotIn("=", public["native_origin"])

    def test_invalid_deployments_rejected(self):
        cases = [
            ("api_image", "api:latest"),
            ("api_image", "sha256:" + "a" * 12),
            ("api_image", "sha256:" + "a" * 63),
            ("api_image", "sha256:" + "a" * 65),
            ("web_image", "web:latest@sha256:" + "a" * 64),
            ("fqdn", "https://example.ts.net"),
            ("fqdn", "host.tail.ts.net:8443"),
            ("project", "existing-project"),
            ("runtime_directory", "/srv/../sallimbook-staging"),
            ("version_code", True),
            ("certificate_sha256", "placeholder"),
            ("source_commit", "HEAD"),
            ("unknown", "secret"),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                deploy.render({**config(), key: value})

    def test_document_inspector_is_isolated_from_network_secrets_and_storage(self):
        compose = deploy.render(config())["compose.json"]
        inspector, api = compose["services"]["inspector"], compose["services"]["api"]
        self.assertEqual(inspector["image"], config()["api_image"])
        self.assertEqual(inspector["network_mode"], "none")
        self.assertEqual(inspector["user"], "10002:10003")
        self.assertTrue(inspector["read_only"])
        self.assertEqual(inspector["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", inspector["security_opt"])
        self.assertEqual(inspector["volumes"], ["inspector_socket:/run/inspector"])
        for key in ("env_file", "environment", "networks", "depends_on", "group_add", "ports"):
            self.assertNotIn(key, inspector)
        self.assertEqual(inspector["mem_limit"], inspector["memswap_limit"])
        self.assertEqual(inspector["pids_limit"], 32)
        self.assertIs(inspector["init"], True)
        self.assertEqual(
            inspector["command"],
            ["python", "-B", "-m", "sallimbook.documents.inspector", "--socket",
             "/run/inspector/inspector.sock"],
        )
        self.assertEqual(api["group_add"], ["10003"])
        self.assertIn("inspector_socket:/run/inspector:ro", api["volumes"])
        self.assertEqual(
            api["environment"]["SALLIMBOOK_DOCUMENT_INSPECTOR_SOCKET"],
            "/run/inspector/inspector.sock",
        )
        self.assertEqual(api["depends_on"]["inspector"], {"condition": "service_healthy"})
        self.assertEqual(compose["volumes"]["inspector_socket"], {})
        for name, service in compose["services"].items():
            if name not in {"api", "inspector"}:
                self.assertFalse(any("inspector" in v for v in service.get("volumes", [])), name)
        dockerfile = (Path(__file__).resolve().parents[2] / "ops/Dockerfile.api").read_text()
        self.assertIn("install -d -o 10002 -g 10003 -m 0750 /run/inspector", dockerfile)

    def test_full_local_image_ids_are_preserved_without_repository_prefix(self):
        local = {**config(), "api_image": "sha256:" + "a" * 64,
                 "web_image": "sha256:" + "b" * 64}
        services = deploy.render(local)["compose.json"]["services"]
        for name in ("api", "scanner", "inspector"):
            self.assertEqual(services[name]["image"], local["api_image"])
        for name in ("web", "public"):
            self.assertEqual(services[name]["image"], local["web_image"])

    def test_output_is_new_and_checksums_cover_generated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "rendered"
            deploy.write_config(config(), output)
            checks = json.loads((output / "checksums.json").read_text())
            self.assertEqual(set(checks), set(deploy.render(config())))
            for name, expected in checks.items():
                self.assertEqual(backup.digest(output / name), expected)
            with self.assertRaises(FileExistsError):
                deploy.write_config(config(), output)


def archive_bytes(members):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as tar:
        for name, data, kind in members:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.type = kind
            tar.addfile(member, io.BytesIO(data))
    output.seek(0)
    return output


class BackupTests(unittest.TestCase):
    def test_backup_rejects_overlapping_paths_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = root / "documents"
            documents.mkdir(mode=0o700)
            nested = documents / "backups"
            nested.mkdir(mode=0o700)
            sibling = root / "backups"
            sibling.mkdir(mode=0o700)
            manifest = root / "deployment.json"
            manifest.write_text(json.dumps(config()))
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            with (
                patch.object(backup, "verify_tools"),
                patch.object(backup, "service_environment") as service,
                patch.object(backup.tempfile, "TemporaryDirectory") as workspace,
            ):
                for destination in (documents, nested, root, sibling / ".."):
                    with self.subTest(destination=destination), self.assertRaisesRegex(
                        backup.OperationError, "separate from document storage"
                    ):
                        backup.backup(
                            root / "unused-service", documents, destination,
                            "age1" + "a" * 58, "a" * 40, manifest,
                        )
                service.assert_not_called()
                workspace.assert_not_called()
                self.assertEqual(
                    sorted(str(path.relative_to(root)) for path in root.rglob("*")), before
                )
                # Valid siblings pass the separation boundary. The existing real
                # PostgreSQL/age integration exercises their complete backup path.
                service.side_effect = RuntimeError("valid sibling boundary reached")
                with self.assertRaisesRegex(RuntimeError, "valid sibling boundary reached"):
                    backup.backup(
                        root / "unused-service", documents, sibling,
                        "age1" + "a" * 58, "a" * 40, manifest,
                    )
                workspace.assert_not_called()

    def test_maximum_object_manifest_roundtrips_above_one_megabyte(self):
        import hashlib

        payload = b"synthetic opaque!"
        objects = {
            f"{index:032x}.sbdoc": {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            for index in range(backup.MAX_ENTRIES)
        }
        manifest = {
            "format": 1,
            "postgres_major": 18,
            "objects": objects,
            "database": {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            },
        }
        encoded = backup.encode_manifest(manifest)
        self.assertGreater(len(encoded), 1024 * 1024)
        self.assertLessEqual(len(encoded), backup.MAX_MANIFEST_BYTES)
        entries = [
            ("manifest.json", encoded, tarfile.REGTYPE),
            ("database.dump.age", payload, tarfile.REGTYPE),
        ] + [("objects/" + name, payload, tarfile.REGTYPE) for name in objects]
        with tempfile.TemporaryDirectory() as tmp:
            backup.unpack_stream(archive_bytes(entries), Path(tmp))
            self.assertEqual(backup.verify_inventory(Path(tmp)), manifest)
        with self.assertRaises(backup.OperationError):
            backup.encode_manifest({"too_large": "x" * backup.MAX_MANIFEST_BYTES})

    def test_completion_receipt_is_exclusive_and_no_partial_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            backup.publish_json(path, {"complete": True})
            with self.assertRaises(FileExistsError):
                backup.publish_json(path, {"complete": False})
            self.assertEqual(json.loads(path.read_text()), {"complete": True})
            self.assertEqual(list(Path(tmp).glob("*.partial")), [])

    def test_reverification_receipts_preserve_previous_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            first = recovery.write_verification_receipt(directory, {"observed": "first"})
            original = (directory / first["receipt"]).read_bytes()
            second = recovery.write_verification_receipt(directory, {"observed": "second"})
            self.assertNotEqual(first["verification_id"], second["verification_id"])
            self.assertEqual((directory / first["receipt"]).read_bytes(), original)
            self.assertEqual(json.loads((directory / second["receipt"]).read_text()), second)
            self.assertEqual(len(list(directory.glob("recovery-check-*.json"))), 2)
            self.assertEqual(list(directory.glob("*.partial")), [])

    def test_tar_rejects_traversal_links_duplicate_unexpected_and_incomplete(self):
        cases = [
            [("../escape", b"x", tarfile.REGTYPE)],
            [("objects/" + "a" * 32 + ".sbdoc", b"x", tarfile.SYMTYPE)],
            [("manifest.json", b"{}", tarfile.REGTYPE)] * 2,
            [("field-keyring.json", b"x", tarfile.REGTYPE)],
            [("manifest.json", b"{}", tarfile.REGTYPE)],
        ]
        for members in cases:
            with self.subTest(members=members), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(backup.OperationError):
                    backup.unpack_stream(archive_bytes(members), Path(tmp))

    def test_unpack_and_verify_rejects_ciphertext_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            dump = b"age-encryption.org/v1 synthetic encrypted payload"
            obj = b"x" * 20
            name = "a" * 32 + ".sbdoc"
            import hashlib

            manifest = {
                "format": 1,
                "postgres_major": 18,
                "database": {
                    "sha256": hashlib.sha256(dump).hexdigest(),
                    "bytes": len(dump),
                },
                "objects": {
                    name: {"sha256": hashlib.sha256(obj).hexdigest(), "bytes": len(obj)}
                },
            }
            entries = [
                ("manifest.json", json.dumps(manifest).encode(), tarfile.REGTYPE),
                ("database.dump.age", dump, tarfile.REGTYPE),
                ("objects/" + name, obj, tarfile.REGTYPE),
            ]
            backup.unpack_stream(archive_bytes(entries), work)
            self.assertEqual(backup.verify_inventory(work), manifest)
            (work / "objects" / name).write_bytes(b"y" * 20)
            with self.assertRaises(backup.OperationError):
                backup.verify_inventory(work)

    def test_service_rejects_non_restore_database_and_injected_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "service.conf"
            for contents in (
                "[sallimbook]\ndbname=existing_prod\n",
                "[sallimbook]\ndbname=sallimbook_prod\n",
                "[sallimbook]\ndbname=sallimbook_a_restorecheck\noptions=-c search_path=public\n",
            ):
                path.write_text(contents)
                path.chmod(0o600)
                with self.assertRaises(backup.OperationError):
                    backup.service_environment(path, restore=True)
            path.write_text("[sallimbook]\ndbname=sallimbook_a_restorecheck\n")
            with patch.dict(
                os.environ, {"PGHOST": "unrelated-host", "PGOPTIONS": "malicious"}
            ):
                env, dbname = backup.service_environment(path, restore=True)
            self.assertEqual(dbname, "sallimbook_a_restorecheck")
            self.assertNotIn("PGHOST", env)
            self.assertNotIn("PGOPTIONS", env)

    def test_private_paths_refuse_symlink_hardlink_and_public_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret"
            path.write_bytes(b"synthetic")
            # Exercise a public file even on runners with a private default umask.
            path.chmod(0o644)
            with self.assertRaises(backup.OperationError):
                backup.private_file(path)
            path.chmod(0o600)
            link = Path(tmp) / "link"
            link.symlink_to(path)
            with self.assertRaises(backup.OperationError):
                backup.private_file(link)
            link.unlink()
            os.link(path, link)
            with self.assertRaises(backup.OperationError):
                backup.private_file(path)

    def test_copy_objects_rejects_unexpected_and_preserves_ciphertext(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            source.mkdir(mode=0o700)
            name = "a" * 32 + ".sbdoc"
            (source / name).write_bytes(b"opaque ciphertext" * 2)
            (source / name).chmod(0o600)
            inventory = backup.copy_objects(source, base / "target")
            self.assertEqual(
                (source / name).read_bytes(), (base / "target" / name).read_bytes()
            )
            self.assertEqual(inventory[name]["sha256"], backup.digest(source / name))
            (source / "unexpected.key").write_bytes(b"synthetic")
            with self.assertRaises(backup.OperationError):
                backup.copy_objects(source, base / "other")


class ReleaseTests(unittest.TestCase):
    def test_preflight_requires_sdk_for_existing_apk_and_refuses_unsafe_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            downloads = directory / "downloads"
            downloads.mkdir()
            apk = downloads / "SallimBook.apk"
            self.assertEqual(
                preflight.verify_download_apk(directory, config(), None), {"status": "not-present"}
            )
            self.make_apk(apk)
            apk.chmod(0o644)
            with patch.object(preflight, "inspect_apk") as inspect:
                with self.assertRaisesRegex(backup.OperationError, "--sdk"):
                    preflight.verify_download_apk(directory, config(), None)
                apk.chmod(0o666)
                with self.assertRaises(backup.OperationError):
                    preflight.verify_download_apk(directory, config(), directory)
                apk.unlink()
                apk.symlink_to(directory / "missing.apk")
                with self.assertRaises(backup.OperationError):
                    preflight.verify_download_apk(directory, config(), directory)
                inspect.assert_not_called()

    def test_preflight_rejects_changed_bytes_and_unverified_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "downloads").mkdir()
            apk = directory / "downloads/SallimBook.apk"
            self.make_apk(apk)
            apk.chmod(0o644)
            expected = backup.digest(apk)
            for result in (
                {"signed": False, "sha256": expected},
                {"signed": True, "sha256": "0" * 64},
            ):
                with patch.object(preflight, "inspect_apk", return_value=result):
                    with self.assertRaises(backup.OperationError):
                        preflight.verify_download_apk(directory, config(), directory)

            def changed_file(*args, **kwargs):
                apk.write_bytes(b"different unverified APK")
                return {"signed": True, "sha256": expected}

            with patch.object(preflight, "inspect_apk", side_effect=changed_file):
                with self.assertRaisesRegex(backup.OperationError, "changed"):
                    preflight.verify_download_apk(directory, config(), directory)

    def test_preflight_checks_actual_apk_instead_of_trusting_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "downloads").mkdir()
            apk = directory / "downloads/SallimBook.apk"
            self.make_apk(apk)
            apk.chmod(0o644)
            apk.with_suffix(".receipt.json").write_text(json.dumps({"signed": True}))
            with (
                patch.object(release, "tools", return_value={
                    key: key for key in ("apksigner", "zipalign", "apkanalyzer")
                }),
                patch.object(release, "run", side_effect=self.tool_output),
            ):
                verified = preflight.verify_download_apk(directory, config(), directory)
                self.assertEqual(verified["status"], "verified")
                self.assertTrue(verified["signed"])
                self.assertEqual(verified["sha256"], backup.digest(apk))

                def wrong_certificate(command, **kwargs):
                    if command[1] == "verify":
                        return "Signer #1 certificate SHA-256 digest: " + "cd" * 32
                    return self.tool_output(command, **kwargs)

                with patch.object(release, "run", side_effect=wrong_certificate):
                    with self.assertRaisesRegex(backup.OperationError, "certificate mismatch"):
                        preflight.verify_download_apk(directory, config(), directory)
                with self.assertRaises(backup.OperationError):
                    preflight.verify_download_apk(
                        directory, {**config(), "version_code": 3}, directory
                    )
                # The sidecar still claims success, but the current APK is invalid.
                apk.write_bytes(b"not an APK")
                with self.assertRaises(zipfile.BadZipFile):
                    preflight.verify_download_apk(directory, config(), directory)

    def test_source_snapshot_excludes_ignored_private_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=root, stderr=subprocess.DEVNULL
                )

            git("init", "-q")
            git("config", "user.email", "synthetic@example.invalid")
            git("config", "user.name", "Synthetic")
            (root / ".gitignore").write_text("private.env\n")
            (root / "code.txt").write_text("reviewed source")
            (root / "private.env").write_text("SYNTHETIC_PRIVATE_NOT_FOR_BUILD")
            git("add", ".")
            git("commit", "-qm", "synthetic")
            commit = git("rev-parse", "HEAD").decode().strip()
            with patch.object(build_context, "ROOT", root):
                with build_context.source_snapshot(commit, Path(tmp)) as checkout:
                    self.assertEqual(
                        (checkout / "code.txt").read_text(), "reviewed source"
                    )
                    self.assertFalse((checkout / "private.env").exists())
            with patch.dict(os.environ, {"VITE_PRIVATE_TOKEN": "synthetic"}):
                self.assertNotIn(
                    "VITE_PRIVATE_TOKEN", build_context.build_environment()
                )

    def make_apk(self, path, capacitor=None, dex=None):
        with zipfile.ZipFile(path, "w") as zip:
            zip.writestr("assets/capacitor.config.json", json.dumps(capacitor or {}))
            zip.writestr(
                "classes.dex",
                dex
                or (
                    "https://"
                    + config()["fqdn"]
                    + ":8443 "
                    + config()["certificate_sha256"]
                    + " NativeVaultAcceptanceGate"
                ).encode(),
            )

    def tool_output(self, command, **kwargs):
        if command[1:3] == ["manifest", "application-id"]:
            return deploy.APP_ID
        if command[1:3] == ["manifest", "version-code"]:
            return "2"
        if command[1:3] == ["manifest", "version-name"]:
            return "0.1.1"
        if command[1:3] == ["manifest", "debuggable"]:
            return "false"
        if command[1:3] == ["manifest", "print"]:
            return '<application android:allowBackup="false" android:usesCleartextTraffic="false"/>'
        if command[1] == "verify":
            return "Signer #1 certificate SHA-256 digest: " + "ab" * 32
        return ""

    def test_release_inspection_forbids_remote_navigation_proof_and_wrong_certificate(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            apk = Path(tmp) / "synthetic.apk"
            with (
                patch.object(
                    release,
                    "tools",
                    return_value={
                        key: key for key in ("apksigner", "zipalign", "apkanalyzer")
                    },
                ),
                patch.object(release, "run", side_effect=self.tool_output),
            ):
                self.make_apk(apk)
                self.assertTrue(
                    release.inspect_apk(apk, config(), tmp, signed=True)["signed"]
                )
                with zipfile.ZipFile(apk) as archive:
                    valid_identity = archive.read("classes.dex")
                for marker in (
                    b"debugproof",
                    b"SecurityProofActivity",
                    b"CvcAcceptanceActivity",
                    b"CvcAcceptanceFixtures",
                    b"NativeVaultAcceptanceGate$Owner",
                    b"SALLIMBOOK DEBUG CVC ACCEPTANCE V1",
                    b"beginSyntheticCvcAcceptance",
                    b"armSyntheticCvcWriteFailure",
                    b"NativeVaultCvcAcceptanceTest",
                ):
                    with self.subTest(proof_marker=marker):
                        self.make_apk(apk, dex=valid_identity)
                        with zipfile.ZipFile(apk, "a") as archive:
                            archive.writestr("classes2.dex", marker)
                        with self.assertRaisesRegex(
                            backup.OperationError, "proof-class exclusion"
                        ):
                            release.inspect_apk(apk, config(), tmp, signed=True)
                for capacitor, dex in (
                    ({"server": {"url": "https://remote.invalid"}}, None),
                    ({"server": {"allowNavigation": ["*"]}}, None),
                    ({"android": {"allowMixedContent": True}}, None),
                ):
                    self.make_apk(apk, capacitor, dex)
                    with self.assertRaises(backup.OperationError):
                        release.inspect_apk(apk, config(), tmp, signed=True)
                self.make_apk(apk)
                with self.assertRaises(backup.OperationError):
                    release.inspect_apk(
                        apk,
                        {**config(), "certificate_sha256": ":".join(["CD"] * 32)},
                        tmp,
                        signed=True,
                    )

    def test_version_cannot_be_reused(self):
        with self.assertRaises(backup.OperationError):
            release.build(
                config(),
                Path("/none"),
                Path("/none"),
                Path("/none"),
                Path("/none"),
                "alias",
                Path("/none"),
                2,
            )


class SchemaRevisionTests(unittest.TestCase):
    known = {"0014_vault", "0015_rule_revocation", "0016_replacement_override"}

    def state(self, current, head="0016_replacement_override", required=None):
        return database.schema_state(current, head, self.known, required or head)

    def test_database_at_the_image_head_is_current(self):
        self.assertEqual(self.state("0016_replacement_override"), "current")

    def test_known_older_revision_needs_the_reviewed_migration(self):
        self.assertEqual(self.state("0014_vault"), "upgrade-required")

    def test_unknown_or_newer_revision_is_refused(self):
        # An old image started on an upgraded DB sees a revision it does not know.
        for current in ("0017_future", None, ""):
            with self.assertRaises(backup.OperationError):
                self.state(current)

    def test_image_whose_required_revision_is_not_its_head_is_refused(self):
        with self.assertRaises(backup.OperationError):
            self.state("0016_replacement_override", required="0015_rule_revocation")

    def test_runbook_migration_command_is_the_rehearsed_argv(self):
        runbook = (Path(__file__).resolve().parents[2] / "docs/operations-runbook.md").read_text()
        command = database.migration_command(
            "PROJECT_database", "/PRIVATE_CONFIG/migration.env", "NEW_API_IMAGE",
            "upgrade", "head",
        )
        self.assertIn(" ".join(command), runbook)
        self.assertIn("downgrade 0014_vault", runbook)
        # The APK is in downloads/ by then, and preflight refuses to run without --sdk.
        section = runbook.split("### 스키마가 바뀌는 업그레이드")[1].split("\n## ")[0]
        self.assertIn("ops.preflight NEW --verify-database --sdk /DEDICATED_ANDROID_SDK", section)
        for line in section.splitlines():
            if "--verify-database" in line:
                self.assertIn("--sdk", line)

    def test_preflight_reports_the_schema_state_from_the_new_image(self):
        for schema in ("current", "upgrade-required"):
            output = json.dumps({"status": "runtime-role-verified", "schema": schema,
                                 "schema_revision": "0014_vault"})
            self.assertEqual(preflight.database_report(output), schema)
        for output in (
            json.dumps({"status": "runtime-role-verified"}),
            json.dumps({"status": "runtime-role-verified", "schema": "unknown"}),
            json.dumps({"status": "failed", "schema": "current"}),
            "not json",
        ):
            with self.assertRaises(backup.OperationError):
                preflight.database_report(output)


if __name__ == "__main__":
    unittest.main()
