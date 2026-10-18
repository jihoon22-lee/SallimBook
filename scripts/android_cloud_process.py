"""Bounded, redacted subprocesses for disposable Android acceptance tools only."""

import os
import signal
import subprocess
import time
from contextlib import contextmanager


class CloudCommandError(RuntimeError):
    """A fixed label only; never includes subprocess output or credential argv."""


def group_alive(process):
    process.poll()  # Reap our leader even when children are still cleaning up.
    try:
        os.killpg(process.pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_group(process, *, grace=10):
    """Give the whole owned group time to clean up, even if its leader exits first."""
    for signum, wait in ((signal.SIGINT, grace), (signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        if not group_alive(process):
            return
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + wait
        while group_alive(process) and time.monotonic() < deadline:
            time.sleep(0.05)
    if group_alive(process):
        raise CloudCommandError("Owned process group cleanup incomplete")


@contextmanager
def interrupt_cleanup():
    """Let SIGTERM use Python finally blocks; SIGKILL remains uncatchable."""
    previous = signal.getsignal(signal.SIGTERM)

    def interrupted(_number, _frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, interrupted)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def checked(command, *, label, timeout, env=None, capture=False, cwd=None):
    process = subprocess.Popen(
        [str(part) for part in command],
        env=env,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
        if process.returncode:
            raise CloudCommandError(label + " failed")
        if output is not None and len(output) > 2 * 1024 * 1024:
            raise CloudCommandError(label + " output limit exceeded")
        return output.decode("utf-8") if capture else ""
    except subprocess.TimeoutExpired:
        raise CloudCommandError(label + " timed out") from None
    finally:
        stop_group(process)
