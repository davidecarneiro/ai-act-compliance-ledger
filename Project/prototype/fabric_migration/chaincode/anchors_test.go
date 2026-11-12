package main

// Batch anchoring (WP7) tests: Merkle parity with Python on shared vectors,
// and AnchorBatch / VerifyInclusion on the Python-issued version 2 ledger
// anchored by the Python issuer in batches of 5 (gen_testdata_anchors.py).
// A missing fixture fails instead of skipping.

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"testing"

	"github.com/gowebpki/jcs"
	"github.com/hyperledger/fabric-chaincode-go/shimtest"
	"github.com/hyperledger/fabric-contract-api-go/contractapi"
)

type merkleTree struct {
	Set     string     `json:"set"`
	Entries []string   `json:"entries"`
	Root    string     `json:"root"`
	Paths   [][]string `json:"paths"`
}

func mustHex(t *testing.T, s string) []byte {
	t.Helper()
	b, err := hex.DecodeString(s)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// Go computes the same roots and inclusion paths as Python and accepts every
// path; the CT reference roots (RFC 6962 test data, sizes 1-8) are among them.
func TestMerkleVectorsMatchPython(t *testing.T) {
	data, err := os.ReadFile("testdata_merkle_vectors.json")
	if err != nil {
		t.Fatalf("fixture: %v", err)
	}
	var v struct {
		Trees []merkleTree `json:"trees"`
	}
	if err := json.Unmarshal(data, &v); err != nil {
		t.Fatal(err)
	}
	ctRoot8 := "5dc9da79a70659a9ad559cb701ded9a2ab9d823aad2f4960cfe370eff4604328"
	checked := 0
	for _, tree := range v.Trees {
		entries := make([][]byte, len(tree.Entries))
		for i, e := range tree.Entries {
			entries[i] = mustHex(t, e)
		}
		root := merkleRoot(entries)
		if hex.EncodeToString(root) != tree.Root {
			t.Fatalf("%s n=%d: root differs from Python", tree.Set, len(entries))
		}
		if tree.Set == "ct" && len(entries) == 8 && tree.Root != ctRoot8 {
			t.Fatalf("CT reference root of 8 leaves differs")
		}
		size := uint64(len(entries))
		for i := range entries {
			goPath := merkleInclusionPath(i, entries)
			if len(goPath) != len(tree.Paths[i]) {
				t.Fatalf("%s n=%d i=%d: path length differs", tree.Set, size, i)
			}
			path := make([][]byte, len(goPath))
			for k := range goPath {
				if hex.EncodeToString(goPath[k]) != tree.Paths[i][k] {
					t.Fatalf("%s n=%d i=%d: path differs from Python", tree.Set, size, i)
				}
				path[k] = mustHex(t, tree.Paths[i][k])
			}
			if !merkleVerifyInclusion(entries[i], uint64(i), size, path, root) {
				t.Fatalf("%s n=%d i=%d: valid path rejected", tree.Set, size, i)
			}
			// The same path for another leaf, another position or another
			// tree size must fail.
			if size > 1 {
				other := (i + 1) % len(entries)
				if merkleVerifyInclusion(entries[other], uint64(i), size, path, root) {
					t.Fatalf("%s n=%d i=%d: path accepted for another entry", tree.Set, size, i)
				}
				if merkleVerifyInclusion(entries[i], uint64(other), size, path, root) {
					t.Fatalf("%s n=%d i=%d: path accepted at another position", tree.Set, size, i)
				}
			}
			// A path does not by itself fix the tree size (in RFC 9162 the
			// same path can verify for a neighbouring size). The size is bound
			// by the signed anchor statement, and VerifyInclusion requires the
			// proof's tree_size to equal it.
			checked++
		}
	}
	if checked < 500 {
		t.Fatalf("only %d paths checked", checked)
	}
}

type anchorFixture struct {
	Ledger  string            `json:"ledger"`
	N       int               `json:"n"`
	Stream  string            `json:"stream"`
	Anchors []json.RawMessage `json:"anchors"`
	Proofs  []json.RawMessage `json:"proofs"`
}

func loadAnchorFixture(t *testing.T) (anchorFixture, []json.RawMessage) {
	t.Helper()
	data, err := os.ReadFile("testdata_anchors_v2.json")
	if err != nil {
		t.Fatalf("fixture: %v", err)
	}
	var f anchorFixture
	if err := json.Unmarshal(data, &f); err != nil {
		t.Fatal(err)
	}
	return f, readRawRecords(t, f.Ledger)
}

func submitAnchor(t *testing.T, cc *ComplianceContract, ctx *contractapi.TransactionContext,
	stub *shimtest.MockStub, txid string, anchor string) error {
	t.Helper()
	stub.MockTransactionStart(txid)
	defer stub.MockTransactionEnd(txid)
	return cc.AnchorBatch(ctx, anchor)
}

func inclusion(t *testing.T, cc *ComplianceContract, ctx *contractapi.TransactionContext,
	record, proof string) inclusionResult {
	t.Helper()
	out, err := cc.VerifyInclusion(ctx, record, proof)
	if err != nil {
		t.Fatalf("VerifyInclusion: %v", err)
	}
	var r inclusionResult
	if err := json.Unmarshal([]byte(out), &r); err != nil {
		t.Fatal(err)
	}
	return r
}

// The Python issuer's anchors are accepted in order, and every record of the
// ledger is proven included at its own position, with the submitting
// organisation stamped on the anchor.
func TestAnchorBatchAndVerifyInclusion(t *testing.T) {
	f, records := loadAnchorFixture(t)
	cc, ctx, stub := newCtxWithIssuer(t)
	for i, a := range f.Anchors {
		if err := submitAnchor(t, cc, ctx, stub, fmt.Sprintf("a%d", i), string(a)); err != nil {
			t.Fatalf("anchor %d: %v", i, err)
		}
	}
	for i, rec := range records {
		r := inclusion(t, cc, ctx, string(rec), string(f.Proofs[i]))
		if !r.Included || r.Seq != uint64(i+1) || r.SubmitterMSP != registryAdminMSP {
			t.Fatalf("record %d: %+v", i+1, r)
		}
	}
	out, err := cc.GetAnchors(ctx, f.Stream)
	if err != nil {
		t.Fatal(err)
	}
	var got struct {
		Head    anchorHeadState   `json:"head"`
		Anchors []json.RawMessage `json:"anchors"`
	}
	if err := json.Unmarshal([]byte(out), &got); err != nil {
		t.Fatal(err)
	}
	if got.Head.LastSeq != uint64(len(records)) || len(got.Anchors) != len(f.Anchors) {
		t.Fatalf("head %+v, %d anchors", got.Head, len(got.Anchors))
	}
}

// Anchors that are replayed, skip a batch, were altered after signing, or
// name an unregistered issuer are refused.
func TestAnchorBatchRejects(t *testing.T) {
	f, _ := loadAnchorFixture(t)
	cc, ctx, stub := newCtxWithIssuer(t)
	if err := submitAnchor(t, cc, ctx, stub, "skip", string(f.Anchors[1])); err == nil ||
		!strings.Contains(err.Error(), "does not follow") {
		t.Fatalf("skipped batch accepted: %v", err)
	}
	if err := submitAnchor(t, cc, ctx, stub, "first", string(f.Anchors[0])); err != nil {
		t.Fatal(err)
	}
	if err := submitAnchor(t, cc, ctx, stub, "replay", string(f.Anchors[0])); err == nil {
		t.Fatal("replayed anchor accepted")
	}
	// The next batch with its root changed after signing.
	var sa signedAnchor
	if err := json.Unmarshal(f.Anchors[1], &sa); err != nil {
		t.Fatal(err)
	}
	var st map[string]any
	if err := json.Unmarshal(sa.Statement, &st); err != nil {
		t.Fatal(err)
	}
	st["merkle_root"] = strings.Repeat("0", 64)
	sa.Statement, _ = json.Marshal(st)
	tampered, _ := json.Marshal(sa)
	if err := submitAnchor(t, cc, ctx, stub, "tampered", string(tampered)); err == nil ||
		!strings.Contains(err.Error(), "signature") {
		t.Fatalf("altered anchor accepted: %v", err)
	}
	// The untouched batch is still accepted after the refusals.
	if err := submitAnchor(t, cc, ctx, stub, "second", string(f.Anchors[1])); err != nil {
		t.Fatalf("next batch refused: %v", err)
	}
}

// Statements signed by a registered key but malformed are refused by their
// structure, before anything is stored; an unregistered key is refused.
func TestAnchorStatementStructure(t *testing.T) {
	cc, ctx, stub := newCtxWithIssuer(t)
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	stub.MockTransactionStart("reg2")
	if err := cc.RegisterIssuer(ctx, hex.EncodeToString(pub)); err != nil {
		t.Fatal(err)
	}
	stub.MockTransactionEnd("reg2")
	fp := sha256Hex(pub)
	sign := func(statement map[string]any) string {
		raw, _ := json.Marshal(statement)
		canon, err := jcs.Transform(raw)
		if err != nil {
			t.Fatal(err)
		}
		b, _ := json.Marshal(map[string]any{
			"statement": json.RawMessage(raw),
			"signature": base64.StdEncoding.EncodeToString(ed25519.Sign(priv, canon)),
		})
		return string(b)
	}
	good := func() map[string]any {
		return map[string]any{
			"type": anchorType, "stream": "s1", "first_seq": 1, "last_seq": 3, "size": 3,
			"merkle_root": strings.Repeat("a", 64), "head_chain_hash": strings.Repeat("b", 64),
			"issuer_pubkey_fingerprint": fp, "tree": anchorTree, "anchored_at": "2026-11-12T00:00:00Z",
		}
	}
	cases := map[string]func(map[string]any){
		"size":       func(s map[string]any) { s["size"] = 4 },
		"order":      func(s map[string]any) { s["last_seq"] = 0 },
		"type":       func(s map[string]any) { s["type"] = "other" },
		"tree":       func(s map[string]any) { s["tree"] = "rfc6962" },
		"stream":     func(s map[string]any) { s["stream"] = "a~b" },
		"root":       func(s map[string]any) { s["merkle_root"] = "XYZ" },
		"extra":      func(s map[string]any) { s["note"] = "unsigned meaning" },
		"unknown-fp": func(s map[string]any) { s["issuer_pubkey_fingerprint"] = strings.Repeat("c", 64) },
	}
	for name, mutate := range cases {
		s := good()
		mutate(s)
		if err := submitAnchor(t, cc, ctx, stub, name, sign(s)); err == nil {
			t.Fatalf("%s: malformed anchor accepted", name)
		}
	}
	if err := submitAnchor(t, cc, ctx, stub, "good", sign(good())); err != nil {
		t.Fatalf("well-formed anchor refused: %v", err)
	}
}

// A record altered after anchoring, a proof for another position or batch,
// and a batch that was never anchored are each reported as not included.
func TestVerifyInclusionRejects(t *testing.T) {
	f, records := loadAnchorFixture(t)
	cc, ctx, stub := newCtxWithIssuer(t)
	for i, a := range f.Anchors[:3] { // batch 4 (record 16) is left unanchored
		if err := submitAnchor(t, cc, ctx, stub, fmt.Sprintf("a%d", i), string(a)); err != nil {
			t.Fatal(err)
		}
	}
	rec7 := string(records[6])
	if r := inclusion(t, cc, ctx, rec7, string(f.Proofs[6])); !r.Included {
		t.Fatalf("record 7 not included: %+v", r)
	}
	altered := strings.Replace(rec7, `"decision": "`, `"decision": "x`, 1)
	if altered == rec7 {
		altered = strings.Replace(rec7, `"decision":"`, `"decision":"x`, 1)
	}
	if r := inclusion(t, cc, ctx, altered, string(f.Proofs[6])); r.Included {
		t.Fatal("altered record reported as included")
	}
	if r := inclusion(t, cc, ctx, rec7, string(f.Proofs[7])); r.Included {
		t.Fatal("proof of another position accepted")
	}
	if r := inclusion(t, cc, ctx, rec7, string(f.Proofs[1])); r.Included {
		t.Fatal("proof of another batch accepted")
	}
	r := inclusion(t, cc, ctx, string(records[15]), string(f.Proofs[15]))
	if r.Included || r.Reason != "no anchor for this batch" {
		t.Fatalf("unanchored record: %+v", r)
	}
}
