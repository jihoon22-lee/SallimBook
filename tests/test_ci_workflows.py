"""Static contracts of the GitHub workflows; nothing is run and nothing is fetched."""

import re
import unittest
from pathlib import Path

from scripts.android_cloud_results import EXPECTED_INSTRUMENTATION

ROOT = Path(__file__).resolve().parents[1]
CI = (ROOT / ".github/workflows/ci.yml").read_text()
INSTRUMENTATION = (ROOT / ".github/workflows/android-instrumentation.yml").read_text()


def job(source, name):
    """The text of one top-level job."""
    body = source.split("\njobs:\n", 1)[1]
    sections = re.split(r"^  ([a-z0-9-]+):\n", body, flags=re.MULTILINE)
    jobs = dict(zip(sections[1::2], sections[2::2], strict=True))
    return jobs[name]


class MainBranchRuns(unittest.TestCase):
    def test_a_push_to_main_is_never_cancelled_or_replaced_by_a_newer_push(self):
        group = re.search(r"^concurrency:\n  group: (.+)\n  cancel-in-progress: (.+)$", CI, re.M)
        self.assertIsNotNone(group)
        expression, cancel = group.groups()
        self.assertEqual(cancel, "${{ github.event_name == 'pull_request' }}")
        # Pull requests share a group per number, so a newer commit supersedes the old run.
        self.assertIn("github.event.pull_request.number", expression)
        # Every other event gets a group of its own: a queued group keeps only one pending
        # run, which would drop a main push when two more arrive.
        self.assertIn("|| github.sha }}", expression)
        self.assertNotIn("github.ref", expression)


class AndroidInstrumentationRuns(unittest.TestCase):
    def test_runs_queue_in_one_group_and_never_cancel_a_running_job(self):
        group = re.search(
            r"^    concurrency:\n      group: (.+)\n      cancel-in-progress: (.+)$",
            job(INSTRUMENTATION, "api36"),
            re.M,
        )
        self.assertIsNotNone(group)
        self.assertEqual(group.group(1), "sallimbook-android-instrumentation")
        self.assertEqual(group.group(2), "false")
        # A draft pull request skips the job, so it must not hold the group at workflow level.
        self.assertNotRegex(INSTRUMENTATION, re.compile(r"^concurrency:", re.M))

    def test_expected_counts_have_a_single_source(self):
        self.assertEqual(set(EXPECTED_INSTRUMENTATION), {"existing", "onboarding"})
        for count in EXPECTED_INSTRUMENTATION.values():
            self.assertTrue(type(count) is int and count > 0)
        # The evidence step reads the shared table instead of repeating the numbers.
        self.assertIn("EXPECTED_INSTRUMENTATION", INSTRUMENTATION)
        self.assertNotRegex(INSTRUMENTATION, r"\('existing',\s*\d+\)|\('onboarding',\s*\d+\)")
        runner = (ROOT / "scripts/test_android_cloud.py").read_text()
        self.assertIn('EXPECTED_INSTRUMENTATION["existing"]', runner)
        self.assertIn('EXPECTED_INSTRUMENTATION["onboarding"]', runner)
        self.assertNotRegex(runner, r'instrument\(\s*"(existing|onboarding)",\s*\d+')
        # The documentation names the source instead of carrying its own copy.
        document = (ROOT / "docs/testing/android-ci.md").read_text()
        self.assertIn("EXPECTED_INSTRUMENTATION", document)
        results = document.split("## 결과의 의미와 공개 artifact", 1)[1].split("\n## ", 1)[0]
        self.assertNotRegex(results, r"existing\.xml`? ?\d+건|tests=\d+")


class OperationsChecks(unittest.TestCase):
    def test_operations_tools_are_linted_with_the_api_settings(self):
        lint = job(CI, "api-unit")
        self.assertIn(
            "ruff check --config services/api/pyproject.toml ops tests/operations", lint
        )

    def test_install_script_scan_runs_on_the_installed_tree(self):
        text = job(CI, "types-contract")
        self.assertLess(
            text.index("pnpm install --frozen-lockfile"),
            text.index("scripts/check_install_scripts.py"),
        )

    def test_operations_images_are_built_but_never_pushed(self):
        text = job(CI, "ops-images")
        self.assertIn("python -m ops.build_context", text)
        self.assertEqual(len(re.findall(r"docker build ", text)), 2)
        self.assertIn("ops.test_deployment --web-image", text)
        for forbidden in ("docker push", "docker login", "--push", "docker/login-action",
                          "docker/build-push-action", "secrets."):
            self.assertNotIn(forbidden, text)

    def test_the_clamav_image_is_built_only_for_changed_inputs_without_a_final_wait(self):
        text = job(CI, "ops-images")
        build = text.split("- name: Build the API image\n", 1)[1].split("\n      - ", 1)[0]
        self.assertIn("if: steps.api-inputs.outputs.changed == 'true'", build)
        gate = text.split("id: api-inputs\n", 1)[1].split("\n      - ", 1)[0]
        for path in ("services/api", "ops/Dockerfile.api", "ops/build_context.py",
                     "infra/documents", ".github/workflows/ci.yml"):
            self.assertIn(path, gate)
        # Pushes to main and manual runs always build the image.
        self.assertIn('"$GITHUB_EVENT_NAME" != pull_request', gate)
        self.assertIn('if [ "$attempt" -lt 3 ]; then sleep 60; fi', build)
        self.assertIn("fetch-depth: 2", text)

    def test_migration_row_job_runs_exactly_the_migration_tests_and_checks_they_ran(self):
        text = job(CI, "api-migration-rows")
        nodes = re.findall(r'"(services/api/tests/[^"]+::[^"]+)"', text)
        self.assertEqual(len(nodes), 3)
        for node in nodes:
            path, *rest = node.split("::")
            source = (ROOT / path).read_text()
            self.assertRegex(source, rf"def {rest[-1]}\(")
        # A skipped database test must not read as a pass.
        self.assertIn("skipped", text)
        self.assertIn("alembic -c services/api/alembic.ini check", text)
        self.assertIn("postgres:18.6-bookworm@sha256:", text)


if __name__ == "__main__":
    unittest.main()
