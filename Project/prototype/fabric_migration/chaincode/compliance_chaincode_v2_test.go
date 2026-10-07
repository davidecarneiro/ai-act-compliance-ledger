package main

// Schema version 2 (RFC 8785) tests. The fixtures come from the Python issuer
// (gen_testdata_v2.py); a missing fixture fails instead of skipping.

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"testing"

	"github.com/gowebpki/jcs"
)

func readRawRecords(t *testing.T, path string) []json.RawMessage {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("fixture %s: %v", path, err)
	}
	var raw []json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		t.Fatalf("fixture %s: %v", path, err)
	}
	if len(raw) == 0 {
		t.Fatalf("fixture %s is empty", path)
	}
	return raw
}

// Every record of the Python-issued version 2 chain recomputes to the stored
// record_hash and chain_hash in Go, and is selected as version 2.
func TestV2PythonLedgerVerifiesInGo(t *testing.T) {
	previous := genesisHash
	for i, r := range readRawRecords(t, "testdata_ledger_v2.json") {
		var rec EvidenceRecord
		if err := json.Unmarshal(r, &rec); err != nil {
			t.Fatal(err)
		}
		body, version, err := recordBodyBytes(r, rec)
		if err != nil {
			t.Fatalf("#%d: %v", i, err)
		}
		if version != schemaV2 {
			t.Fatalf("#%d: schema version %d, expected 2", i, version)
		}
		if got := sha256Hex(body); got != rec.RecordHash {
			t.Errorf("#%d (%s): record_hash Go=%s stored=%s", i, scenarioLabel(rec.ScenarioID), got, rec.RecordHash)
		}
		if rec.ParentHash != previous {
			t.Errorf("#%d: parent_hash does not link", i)
		}
		if want := sha256Hex([]byte(previous + rec.RecordHash)); want != rec.ChainHash {
			t.Errorf("#%d: chain_hash mismatch", i)
		}
		previous = rec.ChainHash
	}
}

// The same chain goes through SubmitEvidence and VerifyChain on the mock stub.
func TestV2SubmitAndVerifyChain(t *testing.T) {
	cc, ctx, stub := newCtxWithIssuer(t)
	raw := readRawRecords(t, "testdata_ledger_v2.json")
	for i, r := range raw {
		stub.MockTransactionStart(fmt.Sprintf("v2-%d", i))
		if err := cc.SubmitEvidence(ctx, string(r)); err != nil {
			t.Fatalf("SubmitEvidence #%d: %v", i, err)
		}
		stub.MockTransactionEnd(fmt.Sprintf("v2-%d", i))
	}
	msg, err := cc.VerifyChain(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if want := fmt.Sprintf("chain valid: %d records", len(raw)); msg != want {
		t.Fatalf("VerifyChain = %q, expected %q", msg, want)
	}
}

// Members the Go struct does not declare are signed, verified and stored as
// submitted. Under version 1 encoding/json would drop them and the hash would
// stop matching; under version 2 the body is the record's own members.
func TestV2KeepsMembersTheStructDoesNotDeclare(t *testing.T) {
	cc, ctx, stub := newCtxWithIssuer(t)
	raw := readRawRecords(t, "testdata_v2_extra_fields.json")
	for i, r := range raw {
		if !bytes.Contains(r, []byte(`"decision_inputs"`)) {
			t.Fatalf("fixture #%d lacks the undeclared member", i)
		}
		stub.MockTransactionStart(fmt.Sprintf("x-%d", i))
		if err := cc.SubmitEvidence(ctx, string(r)); err != nil {
			t.Fatalf("SubmitEvidence #%d: %v", i, err)
		}
		stub.MockTransactionEnd(fmt.Sprintf("x-%d", i))
	}
	if msg, _ := cc.VerifyChain(ctx); msg != "chain valid: 2 records" {
		t.Fatalf("VerifyChain = %q", msg)
	}
	var first struct {
		EvidenceID string `json:"evidence_id"`
	}
	_ = json.Unmarshal(raw[0], &first)
	stored, err := cc.GetEvidence(ctx, first.EvidenceID)
	if err != nil {
		t.Fatal(err)
	}
	for _, member := range []string{`"run_id":"run-0001"`, `"decision_inputs"`, `"submitter_msp":"Org1MSP"`} {
		if !strings.Contains(stored, member) {
			t.Errorf("stored record lacks %s", member)
		}
	}
}

// Changing the declared version, or tampering with an undeclared member, is
// rejected at submission.
func TestV2RejectsVersionAndMemberTamper(t *testing.T) {
	raw := readRawRecords(t, "testdata_v2_extra_fields.json")
	cases := map[string]func(map[string]interface{}){
		"version removed":       func(m map[string]interface{}) { delete(m, "schema_version") },
		"version as string":     func(m map[string]interface{}) { m["schema_version"] = "2" },
		"version 1 named":       func(m map[string]interface{}) { m["schema_version"] = 1 },
		"version 3":             func(m map[string]interface{}) { m["schema_version"] = 3 },
		"undeclared member set": func(m map[string]interface{}) { m["run_id"] = "run-9999" },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			cc, ctx, stub := newCtxWithIssuer(t)
			var m map[string]interface{}
			dec := json.NewDecoder(bytes.NewReader(raw[0]))
			dec.UseNumber()
			if err := dec.Decode(&m); err != nil {
				t.Fatal(err)
			}
			mutate(m)
			b, _ := json.Marshal(m)
			stub.MockTransactionStart("t")
			if err := cc.SubmitEvidence(ctx, string(b)); err == nil {
				t.Errorf("tampered record accepted (%s)", name)
			}
			stub.MockTransactionEnd("t")
		})
	}
}

// A record carrying a duplicate member name is refused: JCS has no form for
// it, and the map round trip would otherwise keep only the last occurrence.
func TestV2RejectsDuplicateMembers(t *testing.T) {
	raw := readRawRecords(t, "testdata_ledger_v2.json")
	dup := append([]byte(`{"decision":"rejected",`), raw[0][1:]...)
	if _, err := canonicalJCS(dup); err == nil {
		t.Fatal("duplicate member accepted")
	}
}

// Go's RFC 8785 implementation reproduces Python's bytes for the same JSON
// value. INTEROP_JCS_VECTORS, when set, points at vectors produced live by
// test_interop.py; otherwise the committed fixture is used.
func TestJCSVectorsMatchPython(t *testing.T) {
	path := os.Getenv("INTEROP_JCS_VECTORS")
	if path == "" {
		path = "testdata_jcs_vectors.json"
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("vectors %s: %v", path, err)
	}
	var vectors []struct {
		Label       string `json:"label"`
		Input       string `json:"input"`
		ExpectedB64 string `json:"expected_b64"`
		SHA256      string `json:"sha256"`
	}
	if err := json.Unmarshal(data, &vectors); err != nil {
		t.Fatal(err)
	}
	if len(vectors) == 0 {
		t.Fatal("no vectors")
	}
	for _, v := range vectors {
		want, err := base64.StdEncoding.DecodeString(v.ExpectedB64)
		if err != nil {
			t.Fatalf("%s: %v", v.Label, err)
		}
		got, err := jcs.Transform([]byte(v.Input))
		if err != nil {
			t.Errorf("JCS-VECTOR FAIL %s: %v", v.Label, err)
			continue
		}
		if !bytes.Equal(got, want) || sha256Hex(got) != v.SHA256 {
			t.Errorf("JCS-VECTOR FAIL %s:\n go:     %s\n python: %s", v.Label, got, want)
			continue
		}
		t.Logf("JCS-VECTOR OK %s %s", v.Label, v.SHA256)
	}
}
