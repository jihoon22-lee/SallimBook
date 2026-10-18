"""Share only testcase outcomes from one private, disposable instrumentation run."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


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
                    ET.SubElement(case, tag, message=reason)
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
