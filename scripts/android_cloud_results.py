"""Share only testcase outcomes from one private, disposable instrumentation run."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# Exact testcase count each instrumentation suite must report. The fixture runner and the
# workflow's evidence step both read this table; update it when a native test is added or
# removed, and nowhere else.
EXPECTED_INSTRUMENTATION = {"existing": 19, "onboarding": 1}

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
        "INITIAL_CURTAIN",
        "INITIAL_DOCUMENT",
        "ANONYMOUS_REJECTED",
        "SETUP_AVAILABLE",
        "OPEN_CANCEL_FORM",
        "CANCEL_FORM",
        "CANCEL_SCROLL",
        "CANCEL_CLICK",
        "CANCEL_RETURN",
        "SECOND_SETUP_AVAILABLE",
        "CANCELLED_SESSION_EMPTY",
        "OPEN_SETUP_FORM",
        "SUBMIT_EMPTY",
        "INVALID_INPUT",
        "INVALID_SESSION_EMPTY",
        "FILL_NAME",
        "NAME_PRESERVED",
        "FILL_PASSWORD",
        "PASSWORD_PRESERVED",
        "FILL_CONFIRMATION",
        "CONFIRMATION_PRESERVED",
        "PREPARE_VALID_SUBMIT",
        "PRESUBMIT_FIELDS",
        "PRESUBMIT_POLICY",
        "PRESUBMIT_READY",
        "SUBMIT_VALID",
        "SESSION_CREATED",
        "APP_UNLOCKED",
        "MAIN_RESUMED",
        "BRIDGE_READY",
        "AUTHENTICATED_HOME",
        "FINISH_MAIN",
    }
)


ONBOARDING_REASONS = frozenset(
    {
        "ASSERTION",
        "NO_MATCHING_VIEW",
        "AMBIGUOUS_VIEW",
        "NO_MATCHING_ROOT",
        "ROOT_NOT_FOCUSED",
        "DETACHED_VIEW",
        "SCROLL_CONSTRAINT",
        "ACTION_FAILED",
        "UI_NOT_IDLE",
        "INJECTION_REJECTED",
        "INTERRUPTED",
        "SCROLL_LIMIT",
        "SCROLL_NOT_SETTLED",
        "UNKNOWN",
    }
)


ONBOARDING_STATUSES = frozenset(
    {
        "NOT_CHECKED",
        "NOT_RECOGNIZED",
        "INPUT_INVALID",
        "REQUEST_PENDING",
        "RESULT_DISCARDED",
        "FOCUS_INTERRUPTED",
        "SETUP_UNAVAILABLE",
        "SETUP_COMPLETE",
        "INVALID_CONNECTION_CODE",
        "HOUSEHOLD_FULL",
        "REGISTRATION_OR_LOGIN_CONFLICT",
        "RATE_LIMITED",
        "REAUTHENTICATION_REQUIRED",
        "AUTH_FAILED",
        "REQUEST_INVALID",
        "NETWORK_UNAVAILABLE",
        "SESSION_EXPIRED",
        "KEY_INVALIDATED",
        "CANCELLED_OR_LOCKED",
        "AUTH_UNAVAILABLE",
    }
)


def failure_details(classname, method, problem):
    if (
        classname != ONBOARDING_CLASS
        or method != ONBOARDING_METHOD
        or problem.tag not in {"failure", "error"}
    ):
        return {}

    def validated(
        stage,
        reason=None,
        before=None,
        after=None,
        flow=None,
        status=None,
        tap=None,
        tap_status=None,
        home=None,
        care=None,
        native_care=None,
    ):
        if stage not in ONBOARDING_STAGES:
            return {}
        if all(
            value is None
            for value in (
                reason,
                before,
                after,
                flow,
                status,
                tap,
                tap_status,
                home,
                care,
                native_care,
            )
        ):
            return {"stage": stage}
        if reason not in ONBOARDING_REASONS or not all(
            isinstance(bits, str) and re.fullmatch(r"(?:[01]{4}|----)", bits)
            for bits in (before, after)
        ):
            return {}
        result = {"stage": stage, "reason": reason, "pre": before, "post": after}
        if (
            flow is None
            and status is None
            and tap is None
            and tap_status is None
            and home is None
            and care is None
            and native_care is None
        ):
            return result
        if (
            status not in ONBOARDING_STATUSES
            or not isinstance(flow, str)
            or not re.fullmatch(r"(?:[01]{3}|---)", flow)
        ):
            return {}
        result.update(flow=flow, status=status)
        if (
            tap is None
            and tap_status is None
            and home is None
            and care is None
            and native_care is None
        ):
            return result
        if (
            tap_status not in ONBOARDING_STATUSES
            or not isinstance(tap, str)
            or not re.fullmatch(r"(?:[01]{5}|-----)", tap)
        ):
            return {}
        result.update(tap=tap, tap_status=tap_status)
        if home is None and care is None and native_care is None:
            return result
        if not isinstance(home, str) or not re.fullmatch(r"(?:[01]{10}|----------)", home):
            return {}
        result["home"] = home
        if care is None and native_care is None:
            return result
        if care not in {
            "NOT_CHECKED",
            "NONE",
            "NETWORK",
            "FORBIDDEN",
            "VALIDATION",
            "NATIVE_UNAVAILABLE",
            "REQUEST_FAILED",
            "CONFLICT",
            "CANCELLED",
            "OTHER",
        }:
            return {}
        if native_care not in {
            "NOT_CHECKED",
            "OK",
            "NETWORK",
            "VALIDATION",
            "FORBIDDEN",
            "NATIVE_UNAVAILABLE",
            "CANCELLED",
            "LOCKED",
            "HTTP_ERROR",
            "OTHER",
            "TIMEOUT",
        }:
            return {}
        return {**result, "care": care, "native_care": native_care}

    # Already-sanitized intermediate XML is checked again by the workflow.
    if problem.get("stage") is not None:
        return validated(
            problem.get("stage"),
            problem.get("reason"),
            problem.get("pre"),
            problem.get("post"),
            problem.get("flow"),
            problem.get("status"),
            problem.get("tap"),
            problem.get("tap_status"),
            problem.get("home"),
            problem.get("care"),
            problem.get("native_care"),
        )
    # Android's XmlTestRunListener may put the exception only in element text.
    # The native test removes its stack: accept one exact line, never parse a trace.
    marker = (
        r"(?:java\.lang\.AssertionError: )?SALLIMBOOK_CLOUD_STAGE: ([A-Z_]+)"
        r"(?:; REASON: ([A-Z_]+); PRE: ([01-]{4}); POST: ([01-]{4}))?"
        r"(?:; FLOW: ([01-]{3}); STATUS: ([A-Z_]+))?"
        r"(?:; TAP: ([01-]{5}); TAP_STATUS: ([A-Z_]+))?"
        r"(?:; HOME: ([01-]{10}))?"
        r"(?:; CARE: ([A-Z_]+); NATIVE_CARE: ([A-Z_]+))?"
    )
    candidates = [
        problem.get("message", ""),
        (problem.text or "").removesuffix("\n").removesuffix("\r"),
    ]
    for message in candidates:
        match = re.fullmatch(marker, message)
        if match:
            return validated(*match.groups())
    return {}


def failure_stage(classname, method, problem):
    return failure_details(classname, method, problem).get("stage")


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
                    node.attrib.update(failure_details(classname, name, original.find(tag)))
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
