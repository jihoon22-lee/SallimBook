"""Test-only bridge to the pinned real document tools in a disposable container.

No production parser limits change. Restricted worker processes speak a private Unix
socket instead of starting Go's Docker CLI under the 768MiB address-space limit.
Only fixed OCR/render argv and bounded stdin/stdout cross this broker; never filenames,
HTTP, caller commands, environment overrides, parser bypasses, or plaintext disk spools.
"""

import json
import os
import re
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sallimbook.core.errors import DomainError
from sallimbook.documents._validation_worker import ProcessFailure, bounded_process
from sallimbook.documents.validation import check_scanner_availability
from test_document_tools import IMAGE, tool_lock

MAX_PIPE = 48_001_024
WRAPPER = '''#!{python}
import json, socket, struct, sys
MAX = 48001024
def receive(sock, count):
    result = bytearray()
    while len(result) < count:
        block = sock.recv(min(65536, count-len(result)))
        if not block: raise RuntimeError()
        result.extend(block)
    return bytes(result)
try:
    header = json.dumps(["{tool}", *sys.argv[1:]], separators=(",", ":")).encode()
    if len(header) > 512: raise RuntimeError()
    data = sys.stdin.buffer.read(MAX+1)
    if len(data) > MAX: raise RuntimeError()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(9)
        sock.connect({socket!r})
        sock.sendall(struct.pack("!II",len(header),len(data))+header+data)
        size = struct.unpack("!I", receive(sock,4))[0]
        if size > MAX: raise RuntimeError()
        sys.stdout.buffer.write(receive(sock,size))
except BaseException:
    sys.exit(1)
'''


def receive(connection, count):
    result = bytearray()
    while len(result) < count:
        block = connection.recv(min(65536, count - len(result)))
        if not block:
            raise ValueError
        result.extend(block)
    return bytes(result)


def allowed(arguments):
    if arguments == ["tesseract", "--list-langs"]:
        return "/usr/bin/tesseract", 8192
    if arguments == [
        "tesseract", "stdin", "stdout", "-l", "eng+kor", "--psm", "11", "--dpi", "200", "tsv"
    ]:
        return "/usr/bin/tesseract", 2 * 1024 * 1024
    if (
        len(arguments) == 9
        and arguments[0:2] == ["pdftoppm", "-f"]
        and re.fullmatch(r"(?:[1-9]|1[0-9]|20)", arguments[2])
        and arguments[3:5] == ["-l", arguments[2]]
        and arguments[5:] == ["-r", "200", "-singlefile", "-"]
    ):
        return "/usr/bin/pdftoppm", MAX_PIPE
    raise ValueError


@contextmanager
def document_runtime():
    with tool_lock(), tempfile.TemporaryDirectory(prefix="sb-doc-tools-") as directory:
        private = Path(directory)
        private.chmod(0o700)
        socket_dir = private / "sockets"
        socket_dir.mkdir(mode=0o700)
        spool = socket_dir / "spool"
        spool.mkdir(mode=0o700)
        image = subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE], text=True
        ).strip()
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise RuntimeError("Pinned test tool image unavailable")
        container = None
        broker = None
        thread = None
        try:
            uid, gid = os.getuid(), os.getgid()
            container = subprocess.check_output([
                "docker", "run", "--detach", "--name", "sallimbook-document-https-" + uuid4().hex,
                "--label", "io.sallimbook.purpose=document-https-test", "--network", "none",
                "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--user", f"{uid}:{gid}", "--memory", "4g", "--memory-swap", "4g", "--cpus", "2",
                "--pids-limit", "64", "--ulimit", "core=0", "--mount",
                f"type=bind,src={socket_dir},dst=/run/sallimbook",
                "--tmpfs", f"/run/sallimbook/spool:rw,noexec,nosuid,nodev,size=96m,mode=0700,uid={uid},gid={gid}",
                image, "/usr/local/sbin/clamd", "--config-file=/etc/sallimbook/clamd.conf",
            ], text=True, stderr=subprocess.DEVNULL).strip()
            if not re.fullmatch(r"[a-f0-9]{64}", container):
                raise RuntimeError("Private test container unavailable")
            deadline = time.monotonic() + 60
            scanner_socket = socket_dir / "clamd.sock"
            while time.monotonic() < deadline:
                try:
                    check_scanner_availability(str(scanner_socket))
                    break
                except DomainError:
                    time.sleep(0.2)
            else:
                raise RuntimeError("Real document scanner did not become ready")
            info = scanner_socket.stat()
            if info.st_uid != uid or info.st_mode & 0o777 != 0o600:
                raise RuntimeError("Private scanner permissions changed")

            class Handler(socketserver.BaseRequestHandler):
                def handle(self):
                    try:
                        self.request.settimeout(10)
                        header_size, data_size = struct.unpack("!II", receive(self.request, 8))
                        if not 1 <= header_size <= 512 or data_size > MAX_PIPE:
                            return
                        arguments = json.loads(receive(self.request, header_size))
                        if not isinstance(arguments, list) or any(not isinstance(x, str) for x in arguments):
                            return
                        binary, maximum = allowed(arguments)
                        data = receive(self.request, data_size)
                        output = bounded_process(
                            ["/usr/bin/docker", "exec", "-i", "-e", "OMP_THREAD_LIMIT=1", container, binary, *arguments[1:]],
                            data, timeout=8, output_limit=maximum, new_session=True,
                        )
                        self.request.sendall(struct.pack("!I", len(output)) + output)
                    except (OSError, ValueError, TypeError, struct.error, ProcessFailure):
                        # Input, OCR text, command errors, and private paths are never logged.
                        return

            broker_socket = private / "broker.sock"
            broker = socketserver.UnixStreamServer(str(broker_socket), Handler)
            broker_socket.chmod(0o600)
            thread = threading.Thread(target=broker.serve_forever, daemon=True)
            thread.start()
            wrappers = {}
            for tool in ("tesseract", "pdftoppm"):
                wrapper = private / tool
                wrapper.write_text(WRAPPER.format(python=sys.executable, tool=tool, socket=str(broker_socket)))
                wrapper.chmod(0o700)
                wrappers[tool] = wrapper
            yield { "document_scanner_socket": scanner_socket, "document_tesseract_path": wrappers["tesseract"], "document_pdftoppm_path": wrappers["pdftoppm"] }
        finally:
            if broker:
                broker.shutdown()
                broker.server_close()
            if thread:
                thread.join(timeout=2)
            if container:
                subprocess.run(["docker", "rm", "--force", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
