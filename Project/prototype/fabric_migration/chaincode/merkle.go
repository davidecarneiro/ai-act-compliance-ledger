package main

// Merkle tree hash and inclusion proofs of RFC 9162, section 2.1, the same
// definitions as compliance_ledger_sim/merkle.py (WP7, batch anchoring).
// Leaf hash SHA-256(0x00 || entry); interior node SHA-256(0x01 || left ||
// right); a tree of n entries splits at the largest power of two below n.
// An entry is the 32 raw bytes of a record's record_hash.

import "crypto/sha256"

func merkleLeafHash(entry []byte) []byte {
	h := sha256.New()
	h.Write([]byte{0x00})
	h.Write(entry)
	return h.Sum(nil)
}

func merkleNodeHash(left, right []byte) []byte {
	h := sha256.New()
	h.Write([]byte{0x01})
	h.Write(left)
	h.Write(right)
	return h.Sum(nil)
}

// largestPowerOfTwoBelow returns the largest power of two strictly smaller
// than n (n > 1).
func largestPowerOfTwoBelow(n int) int {
	k := 1
	for k<<1 < n {
		k <<= 1
	}
	return k
}

// merkleRoot is MTH(D[n]) of RFC 9162, section 2.1.1. The chaincode does not
// need it (the issuer computes roots); it is here for the parity tests.
func merkleRoot(entries [][]byte) []byte {
	switch len(entries) {
	case 0:
		h := sha256.Sum256(nil)
		return h[:]
	case 1:
		return merkleLeafHash(entries[0])
	}
	k := largestPowerOfTwoBelow(len(entries))
	return merkleNodeHash(merkleRoot(entries[:k]), merkleRoot(entries[k:]))
}

// merkleInclusionPath is PATH(m, D[n]) of RFC 9162, section 2.1.3.1, for the
// parity tests.
func merkleInclusionPath(index int, entries [][]byte) [][]byte {
	n := len(entries)
	if n <= 1 {
		return nil
	}
	k := largestPowerOfTwoBelow(n)
	if index < k {
		return append(merkleInclusionPath(index, entries[:k]), merkleRoot(entries[k:]))
	}
	return append(merkleInclusionPath(index-k, entries[k:]), merkleRoot(entries[:k]))
}

// merkleVerifyInclusion is the verification algorithm of RFC 9162,
// section 2.1.3.2.
func merkleVerifyInclusion(entry []byte, index, size uint64, path [][]byte, root []byte) bool {
	if index >= size {
		return false
	}
	fn, sn := index, size-1
	r := merkleLeafHash(entry)
	for _, p := range path {
		if sn == 0 {
			return false
		}
		if fn&1 == 1 || fn == sn {
			r = merkleNodeHash(p, r)
			if fn&1 == 0 {
				for fn&1 == 0 && fn != 0 {
					fn >>= 1
					sn >>= 1
				}
			}
		} else {
			r = merkleNodeHash(r, p)
		}
		fn >>= 1
		sn >>= 1
	}
	return sn == 0 && string(r) == string(root)
}
