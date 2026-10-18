"""Share only testcase outcomes from one private, disposable instrumentation run."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# Only the test-owned fixed stage can cross the diagnostic boundary. Never copy
# raw exception text, stack traces, view snapshots, credentials or dynamic labels.
ONBOARDING_CLASS = "io.github.jihoon22lee.sallimbook.AndroidCloudOnboardingTest"
ONBOARDING_METHOD = "firstStartCancelInvalidInputThenRealSessionAndHome"
ONBOARDING_STAGES = frozenset(
    {
        "FIXTURE_ORIGIN",
        "EMPTY_SESSION",
        "MAIN_LAUNCH",
        "PREDICATE_ASSET",
        "SIGNED_OUT_HOME",
        "ANONYMOUS_REJECTED",
        "SETUP_AVAILABLE",
        "OPEN_CANCEL_FORM",
        "CANCEL_FORM",
        "CANCELLED_SESSION_EMPTY",
        "OPEN_SETUP_FORM",
        "SUBMIT_EMPTY",
        "INVALID_INPUT",
        "INVALID_SESSION_EMPTY",
        "FILL_NAME",
        "FILL_PASSWORD",
        "FILL_CONFIRMATION",
        "SUBMIT_VALID",
        "SESSION_AND_MAIN",
        "BRIDGE_READY",
        "AUTHENTICATED_HOME",
        "FINISH_MAIN",
    }
)


def failure_stage(classname, method, problem):
    if (
        classname != ONBOARDING_CLASS
        or method != ONBOARDING_METHOD
        or problem.tag not in {"failure", "error"}
    ):
        return None
    # Already-sanitized intermediate XML is checked again by the workflow.
    stage = problem.get("stage")
    if stage in ONBOARDING_STAGES:
        return stage
    # Android's XmlTestRunListener may put the exception only in element text.
    # The native test removes its stack: accept one exact line, never parse a trace.
    marker = r"(?:java\.lang\.AssertionError: )?SALLIMBOOK_CLOUD_STAGE: ([A-Z_]+)"
    candidates = [
        problem.get("message", ""),
        (problem.text or "").removesuffix("\n").removesuffix("\r"),
    ]
    for message in candidates:
        match = re.fullmatch(marker, message)
        if match and match[1] in ONBOARDING_STAGES:
            return match[1]
    return None


def save_instrumentation(label, expected, source, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    suite = ET.Element("testsuite", name=label)
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    seen = set()
    for file in sorted(Path(source).rglob("TEST-*.xml")):
        for original in ET.parse(file).getroot().iter("testcase"):
            name, classname = original.get("name", ""), original.get("classname", "")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,199}", name) or not re.fullmatch(
                r"io\.github\.jihoon22lee\.sallimbook\.[A-Za-z0-9_.]{1,200}", classname
            ):
                raise RuntimeError("Unexpected instrumentation testcase identity")
            identity = (classname, name)
            if identity in seen:
                raise RuntimeError("Duplicate instrumentation testcase identity")
            seen.add(identity)
            attributes = {"name": name, "classname": classname}
            elapsed = original.get("time", "")
            if re.fullmatch(r"[0-9]{1,8}(?:\.[0-9]{1,9})?", elapsed):
                attributes["time"] = elapsed
            case = ET.SubElement(suite, "testcase", attributes)
            counts["tests"] += 1
            for tag, counter in (
                ("failure", "failures"),
                ("error", "errors"),
                ("skipped", "skipped"),
            ):
                if original.find(tag) is not None:
                    counts[counter] += 1
                    reason = "Device runner reported " + tag + "; raw diagnostics withheld"
                    if tag == "skipped" and name.startswith("ownerFlagCannot"):
                        reason = (
                            "Requires API 33+, enrolled strong biometric and "
                            "clean synthetic Keystore namespace"
                        )
                    node = ET.SubElement(case, tag, message=reason)
                    stage = failure_stage(classname, name, original.find(tag))
                    if stage is not None:
                        node.set("stage", stage)
    for name, count in counts.items():
        suite.set(name, str(count))
    target = destination / f"{label}.xml"
    with target.open("xb") as stream:
        ET.ElementTree(suite).write(stream, encoding="utf-8", xml_declaration=True)
    print(json.dumps({"suite": label, **counts}), flush=True)
    if counts["tests"] != expected or counts["failures"] or counts["errors"]:
        raise RuntimeError("Instrumentation count or outcome failed; inspect sanitized XML")
    if label == "onboarding" and counts["skipped"]:
        raise RuntimeError("Onboarding was skipped, not passed")
    return counts
