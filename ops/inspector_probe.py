"""Synthetic isolation probe run only inside a disposable test inspector container."""

import os
import socket
import stat
from pathlib import Path


def empty_or_unreadable(path):
    try:
        return not any(Path(path).iterdir())
    except FileNotFoundError, PermissionError:
        return True


def main():
    assert (os.geteuid(), os.getegid()) == (10002, 10003)
    assert 10001 not in os.getgroups()
    # The shared API image contains empty mount-point directories; only mounts matter.
    mounts = {line.split()[4] for line in Path("/proc/self/mountinfo").read_text().splitlines()}
    assert "/run/inspector" in mounts
    for path in ("/run/secrets", "/srv/documents", "/run/scanner", "/run/operator"):
        assert path not in mounts and empty_or_unreadable(path), path
    assert not any(key.startswith("SALLIMBOOK_") for key in os.environ)
    assert sorted(os.listdir("/sys/class/net")) == ["lo"]
    for host, port in (("db", 5432), ("192.0.2.1", 80)):
        try:
            socket.create_connection((host, port), timeout=2).close()
        except OSError:
            continue
        raise AssertionError("Inspector reached a network endpoint")
    assert os.statvfs("/").f_flag & os.ST_RDONLY
    status = Path("/proc/self/status").read_text()
    assert "NoNewPrivs:\t1" in status and "CapEff:\t0000000000000000" in status
    directory = os.lstat("/run/inspector")
    assert (directory.st_uid, directory.st_gid, stat.S_IMODE(directory.st_mode)) == (
        10002,
        10003,
        0o750,
    )
    info = os.lstat("/run/inspector/inspector.sock")
    assert stat.S_ISSOCK(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o660
    assert (info.st_uid, info.st_gid) == (10002, 10003)
    print(
        "PASS: inspector UID10002/GID10003, no network/secrets/storage/scanner, "
        "read-only root, no capabilities, private socket"
    )


if __name__ == "__main__":
    main()
