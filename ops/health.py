"""Container readiness: the same private scanner policy used for every upload."""

import argparse
import os
import urllib.request


def scanner_ready(path):
    from sallimbook.documents.validation import check_scanner_availability

    check_scanner_availability(path)


def check(mode):
    if mode not in {"scanner", "api"}:
        raise ValueError("Unknown container readiness mode")
    scanner_ready(os.environ.get("SALLIMBOOK_DOCUMENT_SCANNER_SOCKET", "/run/scanner/clamd.sock"))
    if mode == "api":
        with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/ready", timeout=2) as response:
            if response.status != 200:
                raise RuntimeError("API database readiness failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("scanner", "api"))
    try:
        check(parser.parse_args().mode)
    except Exception:
        raise SystemExit("Container readiness check failed") from None
