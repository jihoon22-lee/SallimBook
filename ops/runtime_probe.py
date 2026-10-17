"""Synthetic probe run only inside a disposable test API container."""

import hashlib
import io
import json
import os
import socket
import stat
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4


def main():
    from PIL import Image, ImageDraw, ImageFont
    from sallimbook.config import Settings
    from sallimbook.core.database import make_engine
    from sallimbook.identity import service
    from sallimbook.identity.schemas import InvitationAcceptance
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    settings = Settings(_env_file=None)
    url = settings.database_url.get_secret_value()
    parsed = make_url(url)
    if (
        settings.environment != "test"
        or os.environ.get("SALLIMBOOK_OPS_SYNTHETIC") != "1"
        or parsed.host != "db"
        or not parsed.database.startswith("sallimbook_ops_")
        or not parsed.database.endswith("_test")
        or os.geteuid() != 10001
    ):
        raise RuntimeError("Synthetic isolated runtime required")
    directory = settings.document_storage_directory
    assert (
        directory.stat().st_uid == 10001
        and stat.S_IMODE(directory.stat().st_mode) == 0o700
    )
    assert Path("/run/secrets/field-keyring.json").stat().st_uid == 10001
    assert Path("/proc/mounts").read_text().find(" /tmp tmpfs ") >= 0
    deadline = time.monotonic() + 90
    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as scanner:
                scanner.settimeout(2)
                scanner.connect(str(settings.document_scanner_socket))
                scanner.sendall(b"zPING\0")
                assert b"PONG" in scanner.recv(100)
                break
        except (OSError, AssertionError):
            if time.monotonic() >= deadline:
                raise RuntimeError("Synthetic scanner did not become ready") from None
            time.sleep(0.25)
    engine = make_engine(url)
    password = "Synthetic runtime password only 2026!"
    with Session(engine) as session:
        invitation = service.create_bootstrap_invitation(
            session, "Synthetic runtime household", "runtime_test"
        )
        session.commit()
        service.accept_invitation(
            session,
            InvitationAcceptance(
                token=invitation.token,
                password=password,
                display_name="Synthetic runtime owner",
            ),
            "synthetic-runtime",
        )
    engine.dispose()
    token = None

    def request(
        method, path, value=None, *, raw=None, version=None, authenticated=True
    ):
        headers = {"X-SallimBook-Native": "1", "Content-Type": "application/json"}
        if authenticated and token:
            headers["Authorization"] = "Bearer " + token
        if method in {"POST", "PUT"}:
            headers["Idempotency-Key"] = "synthetic-" + uuid4().hex
        if version is not None:
            headers["If-Match"] = '"' + str(version) + '"'
        data = json.dumps(value).encode() if value is not None else None
        if raw is not None:
            data = raw
            headers["Content-Type"] = "application/octet-stream"
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/v1" + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                content = response.read()
                return response.status, content, response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    assert request("GET", "/ready", authenticated=False)[0] == 200
    code, body, _ = request(
        "POST",
        "/auth/native/login",
        {
            "login_name": "runtime_test",
            "password": password,
            "device_label": "Synthetic runtime native",
        },
        authenticated=False,
    )
    assert code == 200
    token = json.loads(body)["access_token"]
    code, body, _ = request(
        "POST",
        "/assets",
        {
            "name": "Synthetic runtime asset",
            "kind": "asset",
            "category": "financial",
            "ownership_kind": "joint",
            "household_share": "1",
            "amount_basis": "owned",
            "started_on": "2025-01-01",
        },
    )
    assert code == 201
    asset_id = json.loads(body)["id"]
    image = Image.new("RGB", (1200, 700), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 52
    )
    for number, line in enumerate(
        [
            "합성 진료비 영수증",
            "합성 병원 검사 진료",
            "합성 환자 진료 날짜",
            "납부 금액 확인 문서",
        ]
    ):
        draw.text((40, 45 + 125 * number), line, font=font, fill="black")
    output = io.BytesIO()
    image.save(output, format="PNG", resolution=200)
    content = output.getvalue()
    code, body, _ = request(
        "POST",
        "/documents",
        {
            "original_name": "synthetic.png",
            "mime_type": "image/png",
            "size_bytes": len(content),
            "checksum_sha256": hashlib.sha256(content).hexdigest(),
            "contains_no_card_data": True,
            "target": {"kind": "asset", "id": asset_id},
        },
    )
    assert code == 201
    document = json.loads(body)
    code, body, _ = request(
        "PUT",
        f"/documents/{document['id']}/content",
        raw=content,
        version=document["version"],
    )
    if code != 200:
        # Only a schema-controlled error code, never response text or request data.
        raise RuntimeError(
            "Synthetic upload failed: " + json.loads(body)["error"]["code"]
        )
    code, returned, headers = request("GET", f"/documents/{document['id']}/download")
    assert (
        code == 200 and returned == content and headers["Cache-Control"] == "no-store"
    )
    assert (
        request("GET", f"/documents/{document['id']}/download", authenticated=False)[0]
        == 401
    )
    objects = list(directory.glob("*.sbdoc"))
    assert len(objects) == 1 and objects[0].read_bytes() != content
    assert (
        objects[0].stat().st_uid == 10001
        and stat.S_IMODE(objects[0].stat().st_mode) == 0o600
    )
    print(
        "PASS: API UID10001, private socket, tmpfs, native login, real Korean OCR/ClamAV upload, AEAD storage/download, anonymous denial"
    )


if __name__ == "__main__":
    main()
