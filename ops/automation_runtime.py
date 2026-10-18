"""Bounded Docker operations used only by explicit automation.run invocations."""

import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from ops.automation import (
    AutomationError,
    atomic_json,
    read_json,
)
from ops.backup import digest, private_directory, publish_json
from ops.build_context import source_snapshot, stage_api_snapshot
from ops.deploy import POSTGRES, write_config
from ops.preflight import verify_image_details

DOCKER = ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock"]
PROJECT_LABEL = "io.sallimbook.automation.project"
RUN_LABEL = "io.sallimbook.automation.run"
SOURCE_LABEL = "io.sallimbook.automation.operator-source"
CONTAINER_FORMAT = (
    '{"name":{{json .Name}},"running":{{json .State.Running}},'
    '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},'
    '"restarts":{{json .RestartCount}},"image":{{json .Config.Image}},'
    '"labels":{{json .Config.Labels}}}'
)
IMAGE_FORMAT = (
    '[{"Id":{{json .Id}},"Architecture":{{json .Architecture}},"Os":{{json .Os}},'
    '"Config":{"User":{{json .Config.User}},"Labels":{{json .Config.Labels}}}}]'
)


class Runtime:
    def __init__(self, config, binding, runner, journal):
        self.config, self.binding, self.runner, self.journal = config, binding, runner, journal
        self.project = config["project"]
        self.manifest = binding["manifest"]
        self.sequence = 0
        self._bundle = None

    def docker(self, *args, timeout=60):
        return self.runner.run(DOCKER + list(args), timeout=timeout)

    def image(self, image, role="api"):
        value = json.loads(self.docker("image", "inspect", "--format", IMAGE_FORMAT, image))
        verify_image_details(value, revision=self.manifest["source_commit"], role=role)
        if value[0]["Config"]["User"] != "10001:10001":
            raise AutomationError("IMAGE_USER")
        return value[0]["Id"]

    def compose(self, *args, binding=None, timeout=600):
        binding = binding or self.binding
        return self.docker(
            "compose",
            "--project-name",
            self.project,
            "--file",
            str(Path(binding["directory"]) / "compose.json"),
            *args,
            timeout=timeout,
        )

    def preflight(self, binding=None):
        binding = binding or self.binding
        value = json.loads(
            self.runner.run(
                [
                    self.config["python_executable"],
                    "-m",
                    "ops.preflight",
                    binding["directory"],
                    "--sdk",
                    self.config["sdk_directory"],
                ],
                timeout=180,
            )
        )
        if value.get("status") != "configuration-checked" or (
            value.get("source_commit") != binding["manifest"]["source_commit"]
        ):
            raise AutomationError("PREFLIGHT_FAILED")

    def labels(self, run_id=None):
        return [
            "--label",
            PROJECT_LABEL + "=" + self.project,
            "--label",
            RUN_LABEL + "=" + (run_id or self.journal.run_id),
            "--label",
            SOURCE_LABEL + "=" + self.config["operator_source_commit"],
        ]

    def resource(self, kind, suffix):
        self.sequence += 1
        name = self.project + "-automation-" + self.journal.run_id.replace("-", "") + "-" + suffix
        self.journal.phase("resource-" + str(self.sequence).zfill(4), kind=kind, name=name)
        return name

    def bundle(self):
        if self._bundle is not None:
            return self._bundle
        root = self.journal.directory / "tools"
        root.mkdir(mode=0o755)
        files = {}
        for name in ("automation_worker.py", "restore_check.py"):
            content = self.runner.run(
                ["git", "show", self.config["operator_source_commit"] + ":ops/" + name]
            )
            path = root / name
            path.write_text(content)
            path.chmod(0o644)
            files[name] = digest(path)
        marker = root / "operator-source.json"
        marker.write_text(
            json.dumps({"source_commit": self.config["operator_source_commit"], "files": files})
        )
        marker.chmod(0o644)
        # Explicit mode survives the scheduler's restrictive umask. The outer
        # operator-owned state/run directory remains 0700 on the host.
        root.chmod(0o755)
        self._bundle = root
        return root

    def job_file(self, action, *, backup=None, run_id=None):
        self.sequence += 1
        path = self.journal.directory / ("job-" + str(self.sequence).zfill(4) + ".json")
        value = {
            "action": action,
            "run_id": run_id or self.journal.run_id,
            "app_source_commit": self.manifest["source_commit"],
            "operator_source_commit": self.config["operator_source_commit"],
        }
        if backup is not None:
            value["backup"] = backup
        path.write_text(json.dumps(value, sort_keys=True))
        path.chmod(0o644)
        return path

    @staticmethod
    def mount(source, target, *, readonly=True, volume=False):
        return [
            "--mount",
            "type="
            + ("volume" if volume else "bind")
            + ",source="
            + str(source)
            + ",target="
            + target
            + (",readonly" if readonly else ""),
        ]

    def worker_args(self, name, job, *, image=None, network="none", mounts=()):
        args = [
            "run",
            "--rm",
            "--name",
            name,
            *self.labels(),
            "--network",
            network,
            "--user",
            "10001:10001",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "128",
            "--memory",
            "768m",
            "--memory-swap",
            "768m",
            "--log-driver",
            "none",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=256m,mode=0700,uid=10001,gid=10001",
        ]
        args += self.mount(self.bundle(), "/run/operator-tools")
        args += self.mount(job, "/run/job.json")
        for mount in mounts:
            args += mount
        args += [
            "--entrypoint",
            "python",
            image or self.manifest["api_image"],
            "/run/operator-tools/automation_worker.py",
        ]
        return args

    def owned_containers(self, run_id):
        output = self.docker(
            "container",
            "ls",
            "--all",
            "--filter",
            "label=" + PROJECT_LABEL + "=" + self.project,
            "--filter",
            "label=" + RUN_LABEL + "=" + run_id,
            "--format",
            "{{json .Names}}",
        )
        return {json.loads(line) for line in output.splitlines() if line.strip()}

    def remove_container(self, name, *, run_id=None):
        run_id = run_id or self.journal.run_id
        if name not in self.owned_containers(run_id):
            return
        inspected = json.loads(
            self.docker("container", "inspect", "--format", CONTAINER_FORMAT, name)
        )
        labels = inspected["labels"] or {}
        if (
            labels.get(PROJECT_LABEL) != self.project
            or labels.get(RUN_LABEL) != run_id
            or labels.get(SOURCE_LABEL) != self.config["operator_source_commit"]
        ):
            raise AutomationError("RESOURCE_IDENTITY")
        self.docker("container", "rm", "--force", name)

    def worker(
        self,
        action,
        *,
        backup=None,
        run_id=None,
        image=None,
        network="none",
        mounts=(),
        timeout=1800,
    ):
        self.image(image or self.manifest["api_image"])
        name = self.resource("container", action + "-" + str(self.sequence))
        args = self.worker_args(
            name,
            self.job_file(action, backup=backup, run_id=run_id),
            image=image,
            network=network,
            mounts=mounts,
        )
        try:
            result = json.loads(self.docker(*args, timeout=timeout))
            if not isinstance(result, dict) or result.get("status") in {None, "failed"}:
                raise AutomationError("WORKER_FAILED")
            return result
        except Exception:
            try:
                self.remove_container(name)
            except Exception:
                self.journal.phase("needs-recovery", reason="worker-cleanup")
                raise AutomationError("RESOURCE_CLEANUP_FAILED") from None
            raise

    def database_network(self):
        name = self.project + "_database"
        value = json.loads(
            self.docker(
                "network",
                "inspect",
                "--format",
                '{"internal":{{json .Internal}},"labels":{{json .Labels}}}',
                name,
            )
        )
        labels = value["labels"] or {}
        if (
            not value["internal"]
            or labels.get("com.docker.compose.project") != self.project
            or (labels.get("com.docker.compose.network") != "database")
        ):
            raise AutomationError("DATABASE_NETWORK_IDENTITY")
        return name

    def backup_mount(self):
        return self.mount(self.config["backup_directory"], "/srv/backups")

    def register_backup(self, receipt):
        from uuid import UUID

        # The worker already re-hashed the real archive. Persist a separate
        # operator-owned anchor, not another reference to the backup directory.
        if str(UUID(receipt["id"])) != receipt["id"]:
            raise AutomationError("BACKUP_RECEIPT")
        root = Path(self.config["state_directory"]) / "backups"
        root.mkdir(mode=0o700, exist_ok=True)
        private_directory(root)
        path = root / (receipt["id"] + ".json")
        value = {
            "format": 1,
            "app_source_commit": self.manifest["source_commit"],
            "operator_source_commit": self.config["operator_source_commit"],
            "backup": receipt,
        }
        if path.exists():
            if read_json(path) != value:
                raise AutomationError("BACKUP_ANCHOR_CHANGED")
        else:
            publish_json(path, value)

    def latest_backup(self):
        root = Path(self.config["state_directory"]) / "backups"
        if not root.exists():
            raise AutomationError("BACKUP_MISSING")
        private_directory(root)
        values = []
        for path in root.iterdir():
            item = read_json(path)
            if (
                item.get("format") != 1
                or item.get("app_source_commit") != self.manifest["source_commit"]
            ):
                raise AutomationError("BACKUP_ANCHOR_CHANGED")
            receipt = item["backup"]
            if path.name != receipt["id"] + ".json":
                raise AutomationError("BACKUP_ANCHOR_CHANGED")
            completed = datetime.fromisoformat(receipt["completed_at"])
            if completed.tzinfo is None:
                raise AutomationError("BACKUP_ANCHOR_CHANGED")
            values.append((completed, receipt))
        if not values:
            raise AutomationError("BACKUP_MISSING")
        return max(values, key=lambda item: item[0])[1]

    def backup(self):
        runtime = Path(self.manifest["runtime_directory"])
        result = self.worker(
            "backup",
            network=self.database_network(),
            mounts=[
                self.mount(self.config["backup_service_file"], "/run/private/backup-service.conf"),
                self.mount(
                    self.config["backup_recipient_file"], "/run/private/backup-recipient.txt"
                ),
                self.mount(runtime / "documents", "/srv/documents"),
                self.mount(self.config["backup_directory"], "/srv/backups", readonly=False),
                self.mount(
                    Path(self.binding["directory"]) / "deployment.json", "/run/deployment.json"
                ),
            ],
        )
        if result.get("status") != "backup-verified":
            raise AutomationError("BACKUP_FAILED")
        try:
            self.register_backup(result["backup"])
            self.acknowledge_backup(result["backup"])
        except Exception:
            self.journal.phase("needs-recovery", reason="backup-anchor-ack")
            raise
        return result

    def acknowledge_backup(self, receipt, run_id=None):
        result = self.worker(
            "backup-ack",
            backup=receipt,
            run_id=run_id,
            timeout=60,
            mounts=[self.mount(self.config["backup_directory"], "/srv/backups", readonly=False)],
        )
        if result.get("status") != "backup-acknowledged":
            raise AutomationError("BACKUP_ACK_FAILED")

    def services(self, *, require_healthy=True):
        rows = self.compose("ps", "--all", "--format", "json")
        rows = (
            json.loads(rows)
            if rows.strip().startswith("[")
            else [json.loads(line) for line in rows.splitlines() if line]
        )
        expected = {"api", "db", "scanner", "node", "web", "public"}
        if {row["Service"] for row in rows} != expected or len(rows) != len(expected):
            raise AutomationError("SERVICE_SET")
        result = {}
        for row in rows:
            value = json.loads(
                self.docker("container", "inspect", "--format", CONTAINER_FORMAT, row["ID"])
            )
            labels = value["labels"] or {}
            service = row["Service"]
            if labels.get("com.docker.compose.project") != self.project or (
                labels.get("com.docker.compose.service") != service
            ):
                raise AutomationError("SERVICE_IDENTITY")
            if not value["running"] or (
                require_healthy
                and service in {"api", "db", "scanner"}
                and value["health"] != "healthy"
            ):
                raise AutomationError("SERVICE_UNHEALTHY")
            role = "api" if service in {"api", "scanner"} else "web"
            if service in {"api", "scanner", "web", "public"} and (
                value["image"] != self.manifest[role + "_image"]
            ):
                raise AutomationError("SERVICE_IMAGE_CHANGED")
            result[service] = {
                "running": value["running"],
                "health": value["health"],
                "restart_count": value["restarts"],
            }
        return result

    def scanner(self):
        volume = self.project + "_scanner_socket"
        value = json.loads(self.docker("volume", "inspect", "--format", "{{json .Labels}}", volume))
        if value.get("com.docker.compose.project") != self.project or (
            value.get("com.docker.compose.volume") != "scanner_socket"
        ):
            raise AutomationError("SCANNER_VOLUME_IDENTITY")
        return self.worker(
            "scanner", mounts=[self.mount(volume, "/run/scanner", volume=True)], timeout=60
        )

    def health(self):
        services = self.services()
        scanner = self.scanner()
        if not scanner.get("fresh"):
            raise AutomationError("SCANNER_STALE")
        backup = self.latest_backup()
        age = (datetime.now(UTC) - datetime.fromisoformat(backup["completed_at"])).total_seconds()
        storage = self.worker(
            "backup-stat", backup=backup, mounts=[self.backup_mount()], timeout=60
        )
        if age < -300 or age > 26 * 3600:
            raise AutomationError("BACKUP_STALE")
        free = shutil.disk_usage(self.config["state_directory"]).free
        if min(free, storage["disk_free_bytes"]) < 1024**3:
            raise AutomationError("DISK_SPACE_LOW")
        return {
            "services": services,
            "scanner": scanner,
            "backup_age_seconds": int(age),
            "state_disk_free_bytes": free,
            "backup_disk_free_bytes": storage["disk_free_bytes"],
            "backup_hash_rechecked": False,
        }

    def startup(self):
        self.preflight()
        self.compose("up", "--detach", "--wait", "--wait-timeout", "300", timeout=360)
        services = self.services()
        scanner = self.scanner()
        if not scanner.get("fresh"):
            raise AutomationError("SCANNER_STALE")
        return {"status": "services-ready", "services": services, "scanner": scanner}

    def _remove_owned(self, kind, name, run_id):
        if kind == "container":
            self.remove_container(name, run_id=run_id)
            return
        listed = self.docker(
            kind,
            "ls",
            "--filter",
            "label=" + PROJECT_LABEL + "=" + self.project,
            "--filter",
            "label=" + RUN_LABEL + "=" + run_id,
            "--format",
            "{{json .Name}}",
        )
        if name not in {json.loads(line) for line in listed.splitlines() if line}:
            return
        labels = json.loads(self.docker(kind, "inspect", "--format", "{{json .Labels}}", name))
        if (
            labels.get(PROJECT_LABEL) != self.project
            or labels.get(RUN_LABEL) != run_id
            or labels.get(SOURCE_LABEL) != self.config["operator_source_commit"]
        ):
            raise AutomationError("RESOURCE_IDENTITY")
        self.docker(kind, "rm", name)

    def restore_check(self):
        backup = self.latest_backup()
        self.worker("backup-verify", backup=backup, mounts=[self.backup_mount()], timeout=600)
        prepared = self.worker(
            "restore-prepare",
            mounts=[
                self.mount(self.config["restore_directory"], "/srv/restores", readonly=False),
            ],
            timeout=60,
        )
        if prepared.get("status") != "restore-prepared":
            raise AutomationError("RESTORE_PREPARE_FAILED")
        network = self.resource("network", "restore")
        volume = self.resource("volume", "restore-db")
        database = self.resource("container", "restore-db")
        success = False
        try:
            self.docker("network", "create", "--internal", *self.labels(), network)
            self.docker("volume", "create", *self.labels(), volume)
            self.docker(
                "run",
                "--detach",
                "--name",
                database,
                *self.labels(),
                "--network",
                network,
                "--network-alias",
                "restore-db",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "CHOWN",
                "--cap-add",
                "DAC_OVERRIDE",
                "--cap-add",
                "FOWNER",
                "--cap-add",
                "SETUID",
                "--cap-add",
                "SETGID",
                "--security-opt",
                "no-new-privileges:true",
                "--log-driver",
                "none",
                "--memory",
                "768m",
                "--memory-swap",
                "768m",
                "--pids-limit",
                "128",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=128m",
                "--tmpfs",
                "/var/run/postgresql:rw,nosuid,nodev,mode=0775,uid=999,gid=999",
                *self.mount(volume, "/var/lib/postgresql", readonly=False, volume=True),
                "--env",
                "POSTGRES_HOST_AUTH_METHOD=scram-sha-256",
                *self.mount(
                    Path(self.config["restore_directory"]) / self.journal.run_id / "db-password",
                    "/run/restore-password",
                ),
                "--env",
                "POSTGRES_PASSWORD_FILE=/run/restore-password",
                "--env",
                "POSTGRES_USER=sallimbook_restore",
                "--env",
                "POSTGRES_DB=postgres",
                POSTGRES,
                "-c",
                "log_statement=none",
                "-c",
                "log_min_error_statement=panic",
            )
            deadline = time.monotonic() + 90
            while True:
                try:
                    self.docker(
                        "exec",
                        "--user",
                        "postgres",
                        database,
                        "pg_isready",
                        "-U",
                        "sallimbook_restore",
                        "-d",
                        "postgres",
                        timeout=10,
                    )
                    break
                except AutomationError:
                    if time.monotonic() >= deadline:
                        raise AutomationError("RESTORE_DATABASE_UNAVAILABLE") from None
                    time.sleep(1)
            result = self.worker(
                "restore-check",
                backup=backup,
                network=network,
                timeout=5400,
                mounts=[
                    self.backup_mount(),
                    self.mount(self.config["restore_directory"], "/srv/restores", readonly=False),
                    self.mount(
                        self.config["restore_identity_file"], "/run/private/restore-identity.txt"
                    ),
                    self.mount(
                        Path(self.manifest["runtime_directory"]) / "field-keyring.json",
                        "/run/private/field-keyring.json",
                    ),
                ],
            )
            if result.get("status") != "restored-integrity-verified":
                raise AutomationError("RESTORE_CHECK_FAILED")
            success = True
            return result
        finally:
            try:
                self._remove_owned("container", database, self.journal.run_id)
                self._remove_owned("network", network, self.journal.run_id)
                if success:
                    self._remove_owned("volume", volume, self.journal.run_id)
                else:
                    self.journal.phase("restore-quarantined", database_volume=volume)
            except Exception:
                self.journal.phase("needs-recovery", reason="restore-cleanup")
                raise AutomationError("RESOURCE_CLEANUP_FAILED") from None

    def candidate_scanner(self, image):
        name = self.resource("container", "candidate-scanner")
        job = self.job_file("scanner")
        try:
            self.docker(
                "run",
                "--detach",
                "--name",
                name,
                *self.labels(),
                "--network",
                "none",
                "--user",
                "10001:10001",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--log-driver",
                "none",
                "--memory",
                "1536m",
                "--memory-swap",
                "1536m",
                "--pids-limit",
                "128",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=64m,mode=0700,uid=10001,gid=10001",
                "--tmpfs",
                "/run/scanner:rw,nosuid,nodev,size=1m,mode=0700,uid=10001,gid=10001",
                *self.mount(self.bundle(), "/run/operator-tools"),
                *self.mount(job, "/run/job.json"),
                "--entrypoint",
                "/usr/local/sbin/clamd",
                image,
                "--foreground",
                "--config-file=/etc/sallimbook/clamd.conf",
            )
            deadline = time.monotonic() + 120
            while True:
                try:
                    value = json.loads(
                        self.docker(
                            "exec",
                            "--user",
                            "10001:10001",
                            name,
                            "python",
                            "/run/operator-tools/automation_worker.py",
                            timeout=15,
                        )
                    )
                    if (
                        value.get("status") != "scanner-checked"
                        or not value.get("fresh")
                        or value.get("refresh_due")
                    ):
                        raise AutomationError("CANDIDATE_SCANNER_STALE")
                    return value
                except AutomationError as failure:
                    if failure.code == "CANDIDATE_SCANNER_STALE" or time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
        finally:
            try:
                self.remove_container(name)
            except Exception:
                self.journal.phase("needs-recovery", reason="candidate-scanner-cleanup")
                raise AutomationError("RESOURCE_CLEANUP_FAILED") from None

    def cvd_refresh(self):
        self.preflight()
        self.services(require_healthy=False)
        current = self.scanner()
        if current.get("fresh") and not current.get("refresh_due"):
            return {"status": "refresh-not-due", "scanner": current}
        root = private_directory(self.config["build_directory"]) / self.journal.run_id
        root.mkdir(mode=0o700)
        app_commit = self.manifest["source_commit"]
        # The operator checkout is pinned separately; this archive is deliberately
        # the deployed application commit, including its original Dockerfile.
        with source_snapshot(app_commit, root) as checkout:
            lock_hash = stage_api_snapshot(
                root / "api", app_commit, checkout, uv=self.config["uv_executable"]
            )
        inputs = {
            path.relative_to(root).as_posix(): digest(path)
            for path in root.rglob("*")
            if path.is_file()
        }
        publish_json(
            root / "build-inputs.json",
            {
                "app_source_commit": app_commit,
                "operator_source_commit": self.config["operator_source_commit"],
                "api_lock_sha256": lock_hash,
                "files": inputs,
            },
        )
        day = datetime.now(UTC).date().isoformat()
        tag = (
            "sallimbook-ops-api:cvd-"
            + self.project.removeprefix("sallimbook-")
            + "-"
            + self.journal.run_id
        )
        self.docker(
            "build",
            "--platform",
            "linux/amd64",
            "--build-arg",
            "SALLIMBOOK_CVD_REFRESH=" + day,
            "--iidfile",
            str(root / "image-id"),
            "--tag",
            tag,
            str(root / "api"),
            timeout=2700,
        )
        image_id = self.image(tag)
        if (root / "image-id").read_text().strip() != image_id:
            raise AutomationError("CANDIDATE_IMAGE_ID")
        image = tag + "@" + image_id
        self.worker("image-check", image=image, timeout=60)
        candidate_scanner = self.candidate_scanner(image)
        candidate = {**self.manifest, "api_image": image}
        directory = root / "deployment"
        write_config(candidate, directory)
        old_apk = Path(self.binding["directory"]) / "downloads/SallimBook.apk"
        if old_apk.exists():
            destination = directory / "downloads/SallimBook.apk"
            shutil.copyfile(old_apk, destination)
            destination.chmod(0o644)
        binding = {
            "directory": str(directory),
            "sha256": digest(directory / "deployment.json"),
            "manifest": candidate,
            "source_run": self.journal.run_id,
        }
        self.preflight(binding)
        self.journal.phase(
            "candidate-verified",
            directory=str(directory),
            sha256=binding["sha256"],
            image=image,
            scanner=candidate_scanner,
        )
        self.journal.phase(
            "promotion-started",
            previous_directory=self.binding["directory"],
            previous_sha256=self.binding["sha256"],
        )
        try:
            self.compose(
                "up",
                "--detach",
                "--no-deps",
                "--wait",
                "--wait-timeout",
                "240",
                "scanner",
                "api",
                binding=binding,
                timeout=300,
            )
            previous_manifest = self.manifest
            self.manifest = candidate
            try:
                self.services()
                fresh = self.scanner()
                if not fresh.get("fresh") or fresh.get("refresh_due"):
                    raise AutomationError("PROMOTED_SCANNER_STALE")
            finally:
                self.manifest = previous_manifest
            atomic_json(
                Path(self.config["state_directory"]) / "active-deployment.json",
                {
                    "format": 1,
                    "project": self.project,
                    "directory": str(directory),
                    "sha256": binding["sha256"],
                    "source_run": self.journal.run_id,
                },
            )
        except Exception:
            pointer = Path(self.config["state_directory"]) / "active-deployment.json"
            # The atomic rename may have completed even if its final fsync did
            # not. Preserve the healthy new containers and reconcile that commit
            # point explicitly; do not roll back services behind a new pointer.
            if pointer.exists() and read_json(pointer).get("source_run") == self.journal.run_id:
                self.journal.phase("needs-recovery", reason="promotion-commit")
                raise AutomationError("PROMOTION_COMMIT_UNCERTAIN") from None
            try:
                self.compose(
                    "up",
                    "--detach",
                    "--no-deps",
                    "--wait",
                    "--wait-timeout",
                    "240",
                    "scanner",
                    "api",
                    timeout=300,
                )
                self.services()
                self.journal.phase("promotion-rolled-back")
            except Exception:
                self.journal.phase("needs-recovery", reason="promotion-rollback")
                raise AutomationError("PROMOTION_ROLLBACK_FAILED") from None
            raise
        return {
            "status": "scanner-refresh-promoted",
            "api_image": image,
            "app_source_commit": app_commit,
            "web_and_apk_unchanged": True,
            "build_receipt_sha256": digest(root / "build-inputs.json"),
        }

    def recover(self, pending):
        for directory, started in pending:
            run_id = started["run_id"]
            if started["operator_source_commit"] != self.config["operator_source_commit"]:
                raise AutomationError("RECOVERY_OPERATOR_CHANGED")
            if started["config_sha256"] != self.journal.config_sha256:
                raise AutomationError("RECOVERY_CONFIG_CHANGED")
            resources = [read_json(path) for path in sorted(directory.glob("resource-*.json"))]
            for item in resources:
                if item["kind"] == "container":
                    self.remove_container(item["name"], run_id=run_id)
            for item in resources:
                if item["kind"] == "network":
                    self._remove_owned("network", item["name"], run_id)
            # Failed restore volumes and directories remain quarantined. Never
            # guess that a resource is disposable from its name alone.
            if (directory / "promotion-started.json").exists():
                if self.binding["source_run"] == run_id:
                    self.services()
                else:
                    self.preflight()
                    self.compose(
                        "up",
                        "--detach",
                        "--no-deps",
                        "--wait",
                        "--wait-timeout",
                        "240",
                        "scanner",
                        "api",
                        timeout=300,
                    )
                    self.services()
            if started["task"] == "backup":
                result = self.worker(
                    "backup-result", run_id=run_id, mounts=[self.backup_mount()], timeout=600
                )
                if result.get("status") == "backup-verified":
                    self.register_backup(result["backup"])
                    self.acknowledge_backup(result["backup"], run_id=run_id)
                elif result.get("status") != "backup-result-absent":
                    raise AutomationError("BACKUP_RECOVERY_FAILED")
                # An absent marker is not success evidence. Interrupted partial
                # artifacts stay untouched; a fresh backup gets a new UUID.
            publish_json(
                directory / "recovered.json",
                {
                    "format": 1,
                    "status": "interrupted-run-reconciled",
                    "run_id": run_id,
                    "recovered_at": datetime.now(UTC).isoformat(),
                    "restore_volumes_preserved": True,
                },
            )
