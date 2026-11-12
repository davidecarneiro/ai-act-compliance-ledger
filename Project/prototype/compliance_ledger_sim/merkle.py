"""Merkle tree hash and inclusion proofs as specified in RFC 9162, section 2.1.

Used by batch anchoring (WP7): every N evidence records, the issuer anchors
the root of the tree over their ``record_hash`` values. The chaincode
(``fabric_migration/chaincode/merkle.go``) implements the same definitions;
``tests/test_batch_anchor.py`` and the Go tests compare both on shared
vectors.

* Leaf hash: SHA-256(0x00 || entry); interior node: SHA-256(0x01 || left ||
  right). The prefixes separate leaves from nodes (second-preimage
  resistance), as in Certificate Transparency.
* Tree of n entries: split at the largest power of two smaller than n.
* An entry is the 32 raw bytes of a record's ``record_hash``.
"""

from __future__ import annotations

import hashlib
from typing import List, Sequence


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def leaf_hash(entry: bytes) -> bytes:
    return _sha256(b"\x00" + entry)


def node_hash(left: bytes, right: bytes) -> bytes:
    return _sha256(b"\x01" + left + right)


def _split(n: int) -> int:
    """Largest power of two strictly smaller than n (n > 1)."""
    k = 1
    while k << 1 < n:
        k <<= 1
    return k


def root(entries: Sequence[bytes]) -> bytes:
    """MTH(D[n]) of RFC 9162, section 2.1.1."""
    n = len(entries)
    if n == 0:
        return _sha256(b"")
    if n == 1:
        return leaf_hash(entries[0])
    k = _split(n)
    return node_hash(root(entries[:k]), root(entries[k:]))


def inclusion_path(index: int, entries: Sequence[bytes]) -> List[bytes]:
    """PATH(m, D[n]) of RFC 9162, section 2.1.3.1."""
    n = len(entries)
    if not 0 <= index < n:
        raise IndexError(f"leaf index {index} outside a tree of {n}")
    if n == 1:
        return []
    k = _split(n)
    if index < k:
        return inclusion_path(index, entries[:k]) + [root(entries[k:])]
    return inclusion_path(index - k, entries[k:]) + [root(entries[:k])]


def verify_inclusion(entry: bytes, index: int, size: int, path: Sequence[bytes],
                     expected_root: bytes) -> bool:
    """The verification algorithm of RFC 9162, section 2.1.3.2."""
    if index >= size or index < 0:
        return False
    fn, sn = index, size - 1
    r = leaf_hash(entry)
    for p in path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = node_hash(p, r)
            if not fn & 1:
                while not fn & 1 and fn != 0:
                    fn >>= 1
                    sn >>= 1
        else:
            r = node_hash(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == expected_root
