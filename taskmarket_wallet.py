#!/usr/bin/env python3
"""Create a zero-spend Base/EVM Taskmarket wallet and CMS-encrypt its secrets.

Only the public address, encrypted payload metadata, and ciphertext are written
outside an ephemeral temporary directory. Task-specific EIP-191 signatures are
encrypted because Taskmarket submission signatures are not bound to artifacts.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIELD = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GENERATOR = (
    55066263022277343669578718895168534326250603453777594175500187360389116729240,
    32670510020758816978083085130507043184471273380659243275938904335757337482424,
)
MASK64 = (1 << 64) - 1
TASK_ID = re.compile(r"^0x[0-9a-fA-F]{64}$")
ROTATION = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)
ROUND_CONSTANTS = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
    0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)
Point = tuple[int, int] | None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rotate_left(value: int, count: int) -> int:
    count %= 64
    if count == 0:
        return value & MASK64
    return ((value << count) | (value >> (64 - count))) & MASK64


def keccak_f1600(state: list[int]) -> list[int]:
    lanes = list(state)
    for constant in ROUND_CONSTANTS:
        columns = [
            lanes[x] ^ lanes[x + 5] ^ lanes[x + 10] ^ lanes[x + 15] ^ lanes[x + 20]
            for x in range(5)
        ]
        deltas = [
            columns[(x - 1) % 5] ^ rotate_left(columns[(x + 1) % 5], 1)
            for x in range(5)
        ]
        for x in range(5):
            for y in range(5):
                lanes[x + 5 * y] ^= deltas[x]

        permuted = [0] * 25
        for x in range(5):
            for y in range(5):
                permuted[y + 5 * ((2 * x + 3 * y) % 5)] = rotate_left(
                    lanes[x + 5 * y], ROTATION[x][y]
                )

        for x in range(5):
            for y in range(5):
                lanes[x + 5 * y] = (
                    permuted[x + 5 * y]
                    ^ ((~permuted[(x + 1) % 5 + 5 * y]) & permuted[(x + 2) % 5 + 5 * y])
                ) & MASK64
        lanes[0] ^= constant
    return lanes


def keccak256(data: bytes) -> bytes:
    rate = 136
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != rate - 1:
        padded.append(0)
    padded.append(0x80)

    state = [0] * 25
    for offset in range(0, len(padded), rate):
        block = padded[offset:offset + rate]
        for lane in range(rate // 8):
            state[lane] ^= int.from_bytes(block[lane * 8:lane * 8 + 8], "little")
        state = keccak_f1600(state)

    output = bytearray()
    while len(output) < 32:
        for lane in range(rate // 8):
            output.extend(state[lane].to_bytes(8, "little"))
            if len(output) >= 32:
                break
        if len(output) < 32:
            state = keccak_f1600(state)
    return bytes(output[:32])


def inverse(value: int, modulus: int) -> int:
    return pow(value % modulus, -1, modulus)


def point_add(left: Point, right: Point) -> Point:
    if left is None:
        return right
    if right is None:
        return left
    x1, y1 = left
    x2, y2 = right
    if x1 == x2 and (y1 + y2) % FIELD == 0:
        return None
    if left == right:
        if y1 == 0:
            return None
        slope = (3 * x1 * x1) * inverse(2 * y1, FIELD) % FIELD
    else:
        slope = (y2 - y1) * inverse(x2 - x1, FIELD) % FIELD
    x3 = (slope * slope - x1 - x2) % FIELD
    y3 = (slope * (x1 - x3) - y1) % FIELD
    return x3, y3


def point_negate(point: Point) -> Point:
    return None if point is None else (point[0], (-point[1]) % FIELD)


def scalar_multiply(scalar: int, point: Point = GENERATOR) -> Point:
    scalar %= ORDER
    if scalar == 0 or point is None:
        return None
    result: Point = None
    addend = point
    while scalar:
        if scalar & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        scalar >>= 1
    return result


def public_key_bytes(point: Point) -> bytes:
    if point is None:
        raise ValueError("point at infinity has no public-key encoding")
    return point[0].to_bytes(32, "big") + point[1].to_bytes(32, "big")


def checksum_address(point: Point) -> str:
    raw = keccak256(public_key_bytes(point))[-20:].hex()
    digest = keccak256(raw.encode("ascii")).hex()
    checksummed = "".join(
        char.upper() if char in "abcdef" and int(digest[index], 16) >= 8 else char
        for index, char in enumerate(raw)
    )
    return "0x" + checksummed


def deterministic_nonce(private_key: int, digest_integer: int, extra: bytes) -> int:
    key_bytes = private_key.to_bytes(32, "big")
    digest_bytes = digest_integer.to_bytes(32, "big")
    value = b"\x01" * 32
    key = b"\x00" * 32
    key = hmac.new(key, value + b"\x00" + key_bytes + digest_bytes + extra, hashlib.sha256).digest()
    value = hmac.new(key, value, hashlib.sha256).digest()
    key = hmac.new(key, value + b"\x01" + key_bytes + digest_bytes + extra, hashlib.sha256).digest()
    value = hmac.new(key, value, hashlib.sha256).digest()
    while True:
        value = hmac.new(key, value, hashlib.sha256).digest()
        candidate = int.from_bytes(value, "big")
        if 1 <= candidate < ORDER:
            return candidate
        key = hmac.new(key, value + b"\x00", hashlib.sha256).digest()
        value = hmac.new(key, value, hashlib.sha256).digest()


def recover_public_key(digest_integer: int, r: int, s: int, recovery_id: int) -> Point:
    x = r + (recovery_id // 2) * ORDER
    if x >= FIELD:
        return None
    alpha = (pow(x, 3, FIELD) + 7) % FIELD
    beta = pow(alpha, (FIELD + 1) // 4, FIELD)
    y = beta if beta % 2 == recovery_id % 2 else FIELD - beta
    ephemeral = (x, y)
    if scalar_multiply(ORDER, ephemeral) is not None:
        return None
    return scalar_multiply(
        inverse(r, ORDER),
        point_add(scalar_multiply(s, ephemeral), point_negate(scalar_multiply(digest_integer))),
    )


def sign_digest(private_key: int, digest: bytes) -> bytes:
    digest_integer = int.from_bytes(digest, "big")
    expected_public_key = scalar_multiply(private_key)
    for counter in range(256):
        nonce = deterministic_nonce(private_key, digest_integer, counter.to_bytes(4, "big"))
        ephemeral = scalar_multiply(nonce)
        if ephemeral is None:
            continue
        r = ephemeral[0] % ORDER
        if r == 0:
            continue
        s = inverse(nonce, ORDER) * (digest_integer + r * private_key) % ORDER
        if s == 0:
            continue
        if s > ORDER // 2:
            s = ORDER - s
        for recovery_id in range(2):
            if recover_public_key(digest_integer, r, s, recovery_id) == expected_public_key:
                return r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([27 + recovery_id])
    raise RuntimeError("could not create a canonical recoverable signature")


def personal_sign_digest(message: str) -> bytes:
    encoded = message.encode("utf-8")
    prefix = b"\x19Ethereum Signed Message:\n" + str(len(encoded)).encode("ascii")
    return keccak256(prefix + encoded)


def self_test() -> None:
    assert keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert keccak256(b"abc").hex() == "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"
    assert scalar_multiply(ORDER) is None
    assert checksum_address(scalar_multiply(1)) == "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"
    message = "taskmarket:submit:0x" + "00" * 32
    signature = sign_digest(1, personal_sign_digest(message))
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:64], "big")
    assert recover_public_key(
        int.from_bytes(personal_sign_digest(message), "big"), r, s, signature[64] - 27
    ) == scalar_multiply(1)


def certificate_der_sha256(certificate: Path) -> str:
    result = subprocess.run(
        ["openssl", "x509", "-in", str(certificate), "-outform", "DER"],
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def write_json_atomic(path: Path, value: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def generate(task_ids: list[str], certificate: Path, public_output: Path, encrypted_output: Path, force: bool) -> dict[str, Any]:
    if not certificate.is_file():
        raise RuntimeError(f"certificate not found: {certificate}")
    for task_id in task_ids:
        if not TASK_ID.fullmatch(task_id):
            raise RuntimeError(f"invalid Taskmarket task ID: {task_id}")
    if not task_ids:
        raise RuntimeError("at least one --task-id is required")
    if not force and (public_output.exists() or encrypted_output.exists()):
        raise RuntimeError("refusing to overwrite wallet output without --force")

    generated_at = utc_now()
    private_key = secrets.randbelow(ORDER - 1) + 1
    public_key = scalar_multiply(private_key)
    address = checksum_address(public_key)
    signed_messages: list[dict[str, str]] = []
    for task_id in task_ids:
        message = f"taskmarket:submit:{task_id}"
        signature = sign_digest(private_key, personal_sign_digest(message))
        r = int.from_bytes(signature[:32], "big")
        s = int.from_bytes(signature[32:64], "big")
        if recover_public_key(
            int.from_bytes(personal_sign_digest(message), "big"), r, s, signature[64] - 27
        ) != public_key:
            raise RuntimeError("local signature recovery failed")
        signed_messages.append({"task_id": task_id, "message": message, "signature": "0x" + signature.hex()})

    private_payload = {
        "schema_version": "taskmarket-evm-wallet-secret-v1",
        "generated_at": generated_at,
        "network": "base",
        "chain_id": 8453,
        "worker_address": address,
        "private_key": "0x" + private_key.to_bytes(32, "big").hex(),
        "preauthorized_signatures": signed_messages,
        "purpose": "Zero-spend Taskmarket bounty submissions only.",
    }

    with tempfile.TemporaryDirectory(prefix="taskmarket-wallet-") as directory:
        private_path = Path(directory) / "wallet-secret.json"
        private_path.write_text(json.dumps(private_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(private_path, 0o600)
        cms_path = Path(directory) / "private-wallet.cms"
        subprocess.run(
            [
                "openssl", "cms", "-encrypt", "-binary", "-aes-256-cbc",
                "-outform", "DER", "-in", str(private_path), "-out", str(cms_path),
                str(certificate),
            ],
            check=True,
            capture_output=True,
        )
        ciphertext = cms_path.read_bytes()

    encoded_ciphertext = base64.b64encode(ciphertext).decode("ascii")
    encrypted_output.parent.mkdir(parents=True, exist_ok=True)
    temporary_ciphertext = encrypted_output.with_suffix(encrypted_output.suffix + ".tmp")
    temporary_ciphertext.write_text(
        "\n".join(encoded_ciphertext[index:index + 76] for index in range(0, len(encoded_ciphertext), 76)) + "\n",
        encoding="ascii",
    )
    os.chmod(temporary_ciphertext, 0o600)
    os.replace(temporary_ciphertext, encrypted_output)

    public_value = {
        "schema_version": "taskmarket-evm-wallet-public-v1",
        "generated_at": generated_at,
        "network": "base",
        "chain_id": 8453,
        "worker_address": address,
        "address_hash": hashlib.sha256(address.lower().encode()).hexdigest()[:16],
        "signature_scheme": "EIP-191 personal_sign",
        "prepared_task_ids": task_ids,
        "prepared_message_count": len(task_ids),
        "public_signatures_exposed": False,
        "encryption": {
            "format": "CMS EnvelopedData DER, AES-256-CBC, base64 encoded",
            "encrypted_file": str(encrypted_output),
            "encrypted_sha256": hashlib.sha256(ciphertext).hexdigest(),
            "recipient_certificate": str(certificate),
            "recipient_certificate_der_sha256": certificate_der_sha256(certificate),
        },
        "writes_performed": [],
        "expenses_usdc": 0,
        "verified_income_usdc": 0,
        "safety_notes": [
            "The encrypted payload contains the private key and task-specific signatures.",
            "Plaintext signatures are not published because they are not artifact-bound.",
            "No payment transaction is signed and the wallet is created with zero funds.",
        ],
    }
    write_json_atomic(public_output, public_value)
    return public_value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--certificate", type=Path, default=Path("crypto/superteam-state-public.crt"))
    parser.add_argument("--public-output", type=Path, default=Path("taskmarket-output/wallet-public.json"))
    parser.add_argument("--encrypted-output", type=Path, default=Path("taskmarket-output/private-wallet.cms.b64"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    self_test()
    if arguments.self_test and not arguments.task_id:
        print(json.dumps({"ok": True, "self_test": True}))
        return 0
    public_value = generate(
        arguments.task_id,
        arguments.certificate,
        arguments.public_output,
        arguments.encrypted_output,
        arguments.force,
    )
    print(json.dumps({
        "ok": True,
        "worker_address": public_value["worker_address"],
        "prepared_message_count": public_value["prepared_message_count"],
        "encrypted_sha256": public_value["encryption"]["encrypted_sha256"],
        "private_material_printed": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
