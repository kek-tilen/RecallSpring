"""A software passkey for tests: makes real WebAuthn responses (ES256, attestation "none") that py_webauthn checks
exactly as it checks a browser's. Never used outside tests."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

UP, UV, BE, BS, AT = 0x01, 0x04, 0x08, 0x10, 0x40
WINDOWS_HELLO = "08987058-cadc-4b81-b6e1-30de50dcbe96"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SoftKey:
    def __init__(
        self, user_handle: bytes | None = None, *, aaguid: str = WINDOWS_HELLO, synced: bool = False, uv: bool = True
    ) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.user_handle = user_handle
        self.aaguid = bytes.fromhex(aaguid.replace("-", ""))
        self.synced = synced
        self.uv = uv
        self.count = 0

    def _flags(self, attested: bool) -> int:
        flags = UP | (UV if self.uv else 0) | (BE | BS if self.synced else 0)
        return flags | (AT if attested else 0)

    def _cose(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    @staticmethod
    def _client_data(kind: str, options: dict[str, Any], origin: str) -> bytes:
        return json.dumps({"type": kind, "challenge": options["challenge"], "origin": origin}).encode()

    def create(self, options: dict[str, Any], origin: str) -> dict[str, Any]:
        """navigator.credentials.create() for ``options`` (the JSON the server sent)."""
        self.user_handle = unb64url(options["user"]["id"])
        rp_hash = hashlib.sha256(options["rp"]["id"].encode()).digest()
        attested = self.aaguid + struct.pack(">H", len(self.credential_id)) + self.credential_id + self._cose()
        auth_data = rp_hash + bytes([self._flags(True)]) + struct.pack(">I", self.count) + attested
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(self._client_data("webauthn.create", options, origin)),
                "attestationObject": b64url(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def get(self, options: dict[str, Any], origin: str, rp_id: str | None = None) -> dict[str, Any]:
        """navigator.credentials.get() for ``options``; ``rp_id`` overrides the one the server asked for."""
        self.count += 1
        rp_hash = hashlib.sha256((rp_id or options["rpId"]).encode()).digest()
        auth_data = rp_hash + bytes([self._flags(False)]) + struct.pack(">I", self.count)
        client_data = self._client_data("webauthn.get", options, origin)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        response: dict[str, Any] = {
            "clientDataJSON": b64url(client_data),
            "authenticatorData": b64url(auth_data),
            "signature": b64url(signature),
        }
        if self.user_handle is not None:
            response["userHandle"] = b64url(self.user_handle)
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": response,
            "clientExtensionResults": {},
        }
