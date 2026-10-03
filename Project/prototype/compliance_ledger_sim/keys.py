"""Persistent Ed25519 signing keys for the simulator.

Keys are stored separately from ledger records, under keys/. This directory
layout is not an access-control boundary. The delivered private key is for
demonstration only. Production key custody requires separate controls.

Ed25519 produces deterministic signatures for the same key and message.
Fabric transaction identities and the evidence issuer key have separate roles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


@dataclass(frozen=True)
class IssuerKey:
    """Bundle the issuer identifier with its private/public key pair."""

    issuer_id: str
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey

    def sign(self, payload: bytes) -> bytes:
        return self.private_key.sign(payload)

    def verify(self, payload: bytes, signature: bytes) -> bool:
        try:
            self.public_key.verify(signature, payload)
        except Exception:  # cryptography raises InvalidSignature
            return False
        return True


def load_or_create_key(
    issuer_id: str = "compliance-oracle-v1",
    keys_dir: Path | None = None,
) -> IssuerKey:
    """Return the persistent issuer key, creating it on first call."""

    keys_dir = keys_dir or Path(__file__).parent / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)

    private_path = keys_dir / f"{issuer_id}.ed25519.pem"
    public_path = keys_dir / f"{issuer_id}.ed25519.pub.pem"

    if not private_path.exists():
        private_key = Ed25519PrivateKey.generate()
        private_path.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        public_path.write_bytes(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
    else:
        private_key = serialization.load_pem_private_key(
            private_path.read_bytes(),
            password=None,
        )
        if not isinstance(private_key, Ed25519PrivateKey):
            raise TypeError("Issuer key is not Ed25519")

    return IssuerKey(
        issuer_id=issuer_id,
        private_key=private_key,
        public_key=private_key.public_key(),
    )


def public_key_fingerprint(key: IssuerKey) -> str:
    """Return the SHA-256 fingerprint stored in issuer_pubkey_fingerprint."""

    import hashlib

    raw = key.public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()
