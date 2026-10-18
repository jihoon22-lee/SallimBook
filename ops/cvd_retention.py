"""Conservative retention of completed, exclusively owned CVD generations."""

import json
import os
import re
import shutil
import stat
from pathlib import Path
from uuid import UUID

from ops.automation import AutomationError, deployment_binding, read_json, validate_rendered
from ops.backup import OperationError, digest, private_directory, publish_json

MAX_GENERATIONS = 6
BUILD_MIN_FREE = 2 * 1024**3
PREFIX = "io.sallimbook.automation."
RECEIPT = "cvd-generation.json"
IMAGE_FORMAT = (
    '{"id":{{json .Id}},"tags":{{json .RepoTags}},'
    '"digests":{{json .RepoDigests}},"labels":{{json .Config.Labels}}}'
)


def inventory(root):
    """Hash only regular, single-link operator files; never traverse a symlink."""
    private_directory(root)
    if root.is_mount():
        raise AutomationError("CVD_TREE_IDENTITY")
    device = root.stat().st_dev
    result = {}
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            path = Path(directory) / name
            info = path.lstat()
            if (
                info.st_uid != os.geteuid()
                or info.st_dev != device
                or info.st_mode & 0o022
                or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)
                or path.is_mount()
            ):
                raise AutomationError("CVD_TREE_IDENTITY")
            relative = path.relative_to(root).as_posix()
            if relative == RECEIPT:
                continue
            result[relative] = {
                "mode": stat.S_IMODE(info.st_mode),
                "sha256": digest(path) if stat.S_ISREG(info.st_mode) else None,
            }
    return result


class Retention:
    def __init__(self, runtime):
        self.runtime = runtime
        self.config = runtime.config
        self.root = private_directory(self.config["build_directory"])
        self.reference_ids = {}

    def tag(self, run_id):
        return (
            "sallimbook-ops-api:cvd-"
            + self.runtime.project.removeprefix("sallimbook-")
            + "-"
            + run_id
        )

    def labels(self, run_id):
        return {
            PREFIX + "project": self.runtime.project,
            PREFIX + "run": run_id,
            PREFIX + "operator-source": self.config["operator_source_commit"],
            PREFIX + "kind": "cvd",
            "org.opencontainers.image.revision": self.runtime.manifest["source_commit"],
            "io.sallimbook.image-role": "api",
        }

    def seal(self, root, tag, image_id):
        if root.parent != self.root or tag != self.tag(root.name):
            raise AutomationError("CVD_RECEIPT_IDENTITY")
        publish_json(
            root / RECEIPT,
            {
                "format": 1,
                "run_id": root.name,
                "project": self.runtime.project,
                "operator_source_commit": self.config["operator_source_commit"],
                "app_source_commit": self.runtime.manifest["source_commit"],
                "tag": tag,
                "image_id": image_id,
                "files": inventory(root),
            },
        )

    def protected(self):
        current = deployment_binding(self.config)
        if current != self.runtime.binding:
            raise AutomationError("CVD_BINDING_CHANGED")
        bindings = [
            (self.config["deployment_directory"], self.config["deployment_sha256"]),
            (current["directory"], current["sha256"]),
        ]
        if current["source_run"]:
            run_id = current["source_run"]
            if str(UUID(run_id)) != run_id:
                raise AutomationError("CVD_PREVIOUS_IDENTITY")
            previous = read_json(
                Path(self.config["state_directory"]) / "runs" / run_id / "promotion-started.json"
            )
            bindings.append((previous["previous_directory"], previous["previous_sha256"]))
        paths, references = set(), set()
        for directory, sha256 in bindings:
            manifest = validate_rendered(directory, sha256, self.runtime.project)
            if {k: v for k, v in manifest.items() if k != "api_image"} != {
                k: v for k, v in self.runtime.manifest.items() if k != "api_image"
            }:
                raise AutomationError("CVD_PREVIOUS_IDENTITY")
            paths.add(Path(directory))
            # Resolve tags/digests too: a baseline alias may point at an owned ID.
            for role in ("api", "web"):
                references.add(self.resolve(manifest[role + "_image"]))
        return paths, references

    def resolve(self, reference):
        if reference not in self.reference_ids:
            self.reference_ids[reference] = json.loads(
                self.runtime.docker("image", "inspect", "--format", "{{json .Id}}", reference)
            )
        return self.reference_ids[reference]

    def receipt(self, root):
        value = read_json(root / RECEIPT, limit=2 * 1024 * 1024)
        expected = {
            "format": 1,
            "run_id": root.name,
            "project": self.runtime.project,
            "operator_source_commit": self.config["operator_source_commit"],
            "app_source_commit": self.runtime.manifest["source_commit"],
            "tag": self.tag(root.name),
            "image_id": value.get("image_id"),
            "files": inventory(root),
        }
        if value != expected or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["image_id"]):
            raise AutomationError("CVD_RECEIPT_IDENTITY")
        journal = Path(self.config["state_directory"]) / "runs" / root.name
        started, finished = (
            read_json(journal / "started.json"),
            read_json(journal / "finished.json"),
        )
        if any(
            row.get("run_id") != root.name
            or row.get("task") != "cvd-refresh"
            or row.get("operator_source_commit") != value["operator_source_commit"]
            for row in (started, finished)
        ) or (
            started.get("project") != self.runtime.project
            or finished.get("status") != "completed"
            or (journal / "needs-recovery.json").exists()
        ):
            raise AutomationError("CVD_RUN_INCOMPLETE")
        return value

    def exclusively_owned(self, value):
        image = json.loads(
            self.runtime.docker("image", "inspect", "--format", IMAGE_FORMAT, value["tag"])
        )
        if (
            image["id"] != value["image_id"]
            or image["tags"] != [value["tag"]]
            or any(
                (image["labels"] or {}).get(k) != v for k, v in self.labels(value["run_id"]).items()
            )
        ):
            return False
        # Include stopped containers and every project, not just this operator.
        return not self.runtime.docker(
            "container", "ls", "--all", "--filter", "ancestor=" + value["image_id"], "--quiet"
        ).strip()

    def prepare(self):
        paths, references = self.protected()
        roots = list(self.root.iterdir())
        # Every other saved manifest is a reference, including legacy artifacts.
        saved = {}
        for root in roots:
            manifest = root / "deployment/deployment.json"
            if any(path.is_symlink() for path in (root, manifest.parent, manifest)):
                continue
            if manifest.is_file():
                value = read_json(manifest, private=False)
                saved[root] = {self.resolve(value[role + "_image"]) for role in ("api", "web")}
        removed = []
        for root in roots:
            try:
                if str(UUID(root.name)) != root.name or root.is_symlink():
                    continue
                if any(path == root or path.is_relative_to(root) for path in paths):
                    continue
                value = self.receipt(root)
                if (
                    value["image_id"] in references
                    or any(
                        value["image_id"] in refs or value["tag"] in refs
                        for other, refs in saved.items()
                        if other != root
                    )
                    or not self.exclusively_owned(value)
                ):
                    continue
            except OperationError, OSError, ValueError, KeyError, TypeError:
                # Legacy, incomplete, modified or shared artifacts remain untouched.
                continue
            # Recheck mutable identities immediately before destructive operations.
            self.protected()
            if self.receipt(root) != value or not self.exclusively_owned(value):
                raise AutomationError("CVD_RETENTION_CHANGED")
            phase = "retention-" + root.name
            self.runtime.journal.phase(
                phase, tag=value["tag"], image_id=value["image_id"], directory=str(root)
            )
            self.runtime.docker("image", "rm", "--no-prune", value["tag"])
            # Never rm by ID or force. If untagging leaves the ID behind, keep
            # its files as recovery evidence; no guessed recursive cleanup.
            remaining = self.runtime.docker(
                "image", "ls", "--all", "--no-trunc", "--quiet"
            ).splitlines()
            if value["image_id"] in remaining:
                raise AutomationError("CVD_UNTAG_UNCERTAIN")
            if inventory(root) != value["files"] or not shutil.rmtree.avoids_symlink_attacks:
                raise AutomationError("CVD_RETENTION_CHANGED")
            shutil.rmtree(root)
            self.runtime.journal.phase(phase + "-done", status="owned-generation-removed")
            removed.append(root.name)
        # Unknown/legacy directories and orphan image tags consume the same cap.
        tags = self.runtime.docker(
            "image",
            "ls",
            "--filter",
            "label=" + PREFIX + "project=" + self.runtime.project,
            "--format",
            "{{.Repository}}:{{.Tag}}",
        ).splitlines()
        roots = list(self.root.iterdir())
        known_tags = {self.tag(root.name) for root in roots}
        count = len(roots) + len(set(tags) - known_tags)
        if count >= MAX_GENERATIONS:
            raise AutomationError("CVD_GENERATION_LIMIT")
        docker_free = self.runtime.worker("storage", timeout=60)["disk_free_bytes"]
        if min(shutil.disk_usage(self.root).free, docker_free) < BUILD_MIN_FREE:
            raise AutomationError("CVD_BUILD_SPACE_LOW")
        return {"removed_generations": removed, "retained_generations": count}
