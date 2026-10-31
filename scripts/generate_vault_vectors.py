"""Reproduce public synthetic interoperability vectors, never production keys.

Fixed keys/nonces/passwords below are intentionally public test data. This is not
an application encryption implementation or a production key generation tool.
"""

import base64
import json
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parents[1]
RECOVERY_INFO = b"SallimBook/vault/recovery-kek/v1"


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def prefix(purpose: str) -> bytes:
    return f"SallimBook/vault/{purpose}/v1".encode("ascii") + b"\0"


def generate() -> dict:
    household = UUID("00000000-0000-4000-8000-000000000001")
    card = UUID("00000000-0000-4000-8000-000000000002")
    hvk = bytes(range(32))
    key_version = 7
    key_bytes = key_version.to_bytes(8, "big")
    # Stripe's public sandbox card; never send it to a live payment endpoint.
    pan = "4242424242424242"
    payload = b"SBV1" + bytes([len(pan)]) + pan.encode("ascii").ljust(19, b"\0")
    payload += (2032).to_bytes(2, "big") + bytes([12])
    assert len(payload) == 27
    card_aad = (
        prefix("card")
        + household.bytes
        + card.bytes
        + key_bytes
        + (1).to_bytes(4, "big")
    )
    card_nonce = bytes(range(12))
    member_vectors = []
    for index, password in enumerate(
        (" synthetic-vault-암호-e\u0301-🔐 ", "synthetic-member-two-password")
    ):
        member = UUID(f"00000000-0000-4000-8000-{index + 3:012d}")
        salt = bytes(range(32 + index * 16, 48 + index * 16))
        nonce = bytes(range(16 + index * 16, 28 + index * 16))
        generation = index + 2
        iterations = 600_000
        kek = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations
        ).derive(password.encode("utf-8"))
        aad = (
            prefix("member")
            + household.bytes
            + member.bytes
            + key_bytes
            + generation.to_bytes(8, "big")
            + iterations.to_bytes(4, "big")
            + salt
        )
        member_vectors.append(
            {
                "member_id": str(member),
                "password": password,
                "password_utf8_hex": password.encode("utf-8").hex(),
                "generation": generation,
                "iterations": iterations,
                "salt": b64(salt),
                "nonce": b64(nonce),
                "aad_hex": aad.hex(),
                "derived_kek_hex": kek.hex(),
                "wrapped_hvk": b64(AESGCM(kek).encrypt(nonce, hvk, aad)),
            }
        )
    recovery_code = bytes(range(64, 96))
    recovery_salt = bytes(range(96, 112))
    recovery_nonce = bytes(range(48, 60))
    recovery_generation = 3
    recovery_kek = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=recovery_salt, info=RECOVERY_INFO
    ).derive(recovery_code)
    recovery_aad = (
        prefix("recovery")
        + household.bytes
        + key_bytes
        + recovery_generation.to_bytes(8, "big")
        + recovery_salt
    )
    check_nonce = bytes(range(64, 76))
    check_aad = prefix("key-check") + household.bytes + key_bytes
    check_plaintext = b"SallimBook vault key check v1"
    return {
        "schema_version": 1,
        "warning": "PUBLIC SYNTHETIC TEST DATA ONLY. Fixed keys and nonces MUST NEVER be used in the app.",
        "sources": [
            "https://docs.stripe.com/testing",
            "https://www.w3.org/TR/2017/REC-WebCryptoAPI-20170126/",
            "https://cryptography.io/en/50.0.0/hazmat/primitives/key-derivation-functions/",
        ],
        "household_id": str(household),
        "key_version": key_version,
        "hvk_hex": hvk.hex(),
        "card": {
            "card_id": str(card),
            "pan": pan,
            "expiry_year": 2032,
            "expiry_month": 12,
            "payload_hex": payload.hex(),
            "nonce": b64(card_nonce),
            "aad_hex": card_aad.hex(),
            "ciphertext": b64(AESGCM(hvk).encrypt(card_nonce, payload, card_aad)),
        },
        "members": member_vectors,
        "recovery": {
            "code": b64(recovery_code),
            "generation": recovery_generation,
            "salt": b64(recovery_salt),
            "nonce": b64(recovery_nonce),
            "hkdf_info_utf8": RECOVERY_INFO.decode("ascii"),
            "derived_kek_hex": recovery_kek.hex(),
            "aad_hex": recovery_aad.hex(),
            "wrapped_hvk": b64(
                AESGCM(recovery_kek).encrypt(recovery_nonce, hvk, recovery_aad)
            ),
        },
        "key_check": {
            "plaintext_ascii": check_plaintext.decode("ascii"),
            "nonce": b64(check_nonce),
            "aad_hex": check_aad.hex(),
            "ciphertext": b64(
                AESGCM(hvk).encrypt(check_nonce, check_plaintext, check_aad)
            ),
        },
    }


def generate_v2() -> dict:
    v1 = generate()
    key = bytes.fromhex(v1["hvk_hex"])
    rows = []
    for index, code in enumerate(("", "007", "0009")):
        plain = bytearray.fromhex(v1["card"]["payload_hex"])
        plain[3] = ord("2")
        plain += bytes([len(code)]) + code.encode("ascii").ljust(4, b"\0")
        aad = bytes.fromhex(v1["card"]["aad_hex"])[:-4] + (2).to_bytes(4, "big")
        nonce = bytes(range(128 + index * 12, 140 + index * 12))
        rows.append({"cvc": code, "payload_hex": plain.hex(), "aad_hex": aad.hex(),
                     "nonce": b64(nonce), "ciphertext": b64(AESGCM(key).encrypt(nonce, bytes(plain), aad))})
    return {"notice": "Public synthetic test data only", "household_id": v1["household_id"],
            "card_id": v1["card"]["card_id"], "key_version": v1["key_version"],
            "hvk_hex": v1["hvk_hex"], "pan": v1["card"]["pan"],
            "expiry_year": v1["card"]["expiry_year"], "expiry_month": v1["card"]["expiry_month"], "cards": rows}


if __name__ == "__main__":
    path = ROOT / "packages/test-fixtures/vault-v1.json"
    path.write_text(
        json.dumps(generate(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (ROOT / "packages/test-fixtures/vault-v2.json").write_text(json.dumps(generate_v2(), indent=2) + "\n", encoding="utf-8")
    print("Reproduced public synthetic vault interoperability vectors.")
