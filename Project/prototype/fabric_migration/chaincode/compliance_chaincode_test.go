package main

// Tests against real records from the Python issuer: the Art. 73 incident run,
// the current canonical ledger and the boundary-matrix ledger. Ten tests, no
// Fabric network; one builds the contract with contractapi.NewChaincode, as the
// executable does at start-up. A missing fixture fails instead of skipping.
// MVCC serialisation of the head pointer needs a real peer and is not exercised.

import (
	"crypto/ecdsa"
	"crypto/ed25519"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"math/big"
	"os"
	"strings"
	"testing"

	"github.com/golang/protobuf/proto"
	"github.com/hyperledger/fabric-chaincode-go/shimtest"
	"github.com/hyperledger/fabric-contract-api-go/contractapi"
	"github.com/hyperledger/fabric-protos-go/msp"
)

// setCreator stamps the MockStub with a Fabric identity of the given MSP, so the
// chaincode's cid.GetMSPID/GetID work in-process (an ephemeral self-signed cert).
func setCreator(t *testing.T, stub *shimtest.MockStub, mspID string) {
	t.Helper()
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: "tester", OrganizationalUnit: []string{"client"}},
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &priv.PublicKey, priv)
	if err != nil {
		t.Fatal(err)
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	sid, err := proto.Marshal(&msp.SerializedIdentity{Mspid: mspID, IdBytes: certPEM})
	if err != nil {
		t.Fatal(err)
	}
	stub.Creator = sid
}

// newCtx wires a fresh contract + mock stub + transaction context, with the issuer
// key registered by an admin identity, ready for SubmitEvidence.
func newCtxWithIssuer(t *testing.T) (*ComplianceContract, *contractapi.TransactionContext, *shimtest.MockStub) {
	cc := new(ComplianceContract)
	stub := shimtest.NewMockStub("compliance", nil)
	ctx := new(contractapi.TransactionContext)
	ctx.SetStub(stub)
	setCreator(t, stub, registryAdminMSP)
	stub.MockTransactionStart("reg")
	if err := cc.RegisterIssuer(ctx, rawPubKeyHex); err != nil {
		t.Fatalf("RegisterIssuer: %v", err)
	}
	stub.MockTransactionEnd("reg")
	return cc, ctx, stub
}

// The incident ledger sits in a different place in the author's vault and in the
// delivered Project/ folder; both are tried, in that order of likelihood.
var incidentLedgerCandidates = []string{
	"../../../experiments/runs/incident_run/ledger.json",       // Project/
	"../../../../06_dados/experiments/incident_run/ledger.json", // vault
}

func readIncidentLedger(t *testing.T) []byte {
	t.Helper()
	for _, p := range incidentLedgerCandidates {
		if data, err := os.ReadFile(p); err == nil {
			return data
		}
	}
	t.Fatalf("incident ledger not found; tried %v", incidentLedgerCandidates)
	return nil
}

// Demo Ed25519 public key (raw, hex), exported from compliance_ledger_sim/keys.py.
// It is the counterpart of issuer_pubkey_fingerprint = sha256(this key).
const rawPubKeyHex = "0964e33a68f667c0ac2dc0fbd0cf40695ba568bcab4015dcc5cdafa211562a3c"

func loadLedger(t *testing.T) []EvidenceRecord {
	t.Helper()
	data := readIncidentLedger(t)
	var recs []EvidenceRecord
	if err := json.Unmarshal(data, &recs); err != nil {
		t.Fatalf("unmarshal ledger: %v", err)
	}
	if len(recs) == 0 {
		t.Fatal("incident ledger is empty")
	}
	return recs
}

func TestRecordHashInterop(t *testing.T) {
	for _, rec := range loadLedger(t) {
		body := stripDerived(rec)
		b, err := canonicalJSON(body)
		if err != nil {
			t.Fatalf("canonicalJSON: %v", err)
		}
		if got := sha256Hex(b); got != rec.RecordHash {
			t.Errorf("record %s: record_hash Go=%s != stored=%s",
				rec.EvidenceID, got, rec.RecordHash)
		}
	}
}

func TestChainHashInterop(t *testing.T) {
	previous := genesisHash
	for _, rec := range loadLedger(t) {
		body := stripDerived(rec)
		b, _ := canonicalJSON(body)
		recordHash := sha256Hex(b)
		expectedChain := sha256Hex([]byte(previous + recordHash))
		if expectedChain != rec.ChainHash {
			t.Errorf("record %s: chain_hash Go=%s != stored=%s",
				rec.EvidenceID, expectedChain, rec.ChainHash)
		}
		if rec.ParentHash != previous {
			t.Errorf("record %s: parent_hash=%s != anterior=%s",
				rec.EvidenceID, rec.ParentHash, previous)
		}
		previous = rec.ChainHash
	}
}

func TestSignatureRequiresRawKeyNotFingerprint(t *testing.T) {
	rec := loadLedger(t)[0]
	body := stripDerived(rec)
	b, _ := canonicalJSON(body)
	sig, err := base64.StdEncoding.DecodeString(rec.IssuerSignatureBase64)
	if err != nil {
		t.Fatalf("sig base64: %v", err)
	}

	fp, _ := hex.DecodeString(rec.IssuerPubkeyFprint) // 32 bytes, but this is the sha256, not the key
	if ed25519.Verify(fp, b, sig) {
		t.Error("verification with the fingerprint passed, which is unexpected (bug #2 would no longer exist)")
	}

	pub, _ := hex.DecodeString(rawPubKeyHex)
	if !ed25519.Verify(pub, b, sig) {
		t.Error("verification with the raw public key failed: canonical interop broken or wrong key")
	}

	// And the raw key binds to the record's fingerprint through sha256 (the chaincode fix).
	if sha256Hex(pub) != rec.IssuerPubkeyFprint {
		t.Errorf("sha256(key) %s != record fingerprint %s", sha256Hex(pub), rec.IssuerPubkeyFprint)
	}
}

// End to end: submits the three real records to the whole chaincode through a mock stub
// (no Fabric network), confirms that SubmitEvidence accepts them all (with bugs #1, #2
// and #3 fixed), that VerifyChain reports an intact chain, and that a tampered record is
// rejected. It proves the chaincode's LOGIC, not merely that it compiles.
func TestSubmitEvidenceEndToEnd(t *testing.T) {
	data := readIncidentLedger(t)
	var raw []json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	cc, ctx, stub := newCtxWithIssuer(t)

	for i, r := range raw {
		txid := fmt.Sprintf("tx%d", i)
		stub.MockTransactionStart(txid)
		if err := cc.SubmitEvidence(ctx, string(r)); err != nil {
			t.Fatalf("SubmitEvidence #%d rejected (acceptance expected): %v", i, err)
		}
		stub.MockTransactionEnd(txid)
	}

	msg, err := cc.VerifyChain(ctx)
	if err != nil {
		t.Fatalf("VerifyChain: %v", err)
	}
	want := fmt.Sprintf("chain valid: %d records", len(raw))
	if msg != want {
		t.Errorf("VerifyChain = %q, expected %q", msg, want)
	}

	// MSP binding: the stored record carries the submitter's Fabric identity.
	storedJSON, err := cc.GetEvidence(ctx, mustEvidenceID(raw[0]))
	if err != nil {
		t.Fatalf("GetEvidence: %v", err)
	}
	var stored EvidenceRecord
	if err := json.Unmarshal([]byte(storedJSON), &stored); err != nil {
		t.Fatalf("GetEvidence returned unreadable JSON: %v", err)
	}
	if stored.SubmitterMSP != registryAdminMSP {
		t.Errorf("submitter_msp=%q, expected %q", stored.SubmitterMSP, registryAdminMSP)
	}

	// Tampering: change the decision of the first record and try to submit it; rejected.
	var tampered map[string]interface{}
	json.Unmarshal(raw[0], &tampered)
	tampered["decision"] = "approved" // was escalated
	tb, _ := json.Marshal(tampered)
	stub.MockTransactionStart("tamper")
	if err := cc.SubmitEvidence(ctx, string(tb)); err == nil {
		t.Error("tampered record was ACCEPTED (rejection expected)")
	}
	stub.MockTransactionEnd("tamper")
}

func mustEvidenceID(r json.RawMessage) string {
	var m map[string]interface{}
	json.Unmarshal(r, &m)
	return m["evidence_id"].(string)
}

// RegisterIssuer is allowed only to identities of the authority organisation.
func TestRegisterIssuerGovernance(t *testing.T) {
	cc := new(ComplianceContract)
	stub := shimtest.NewMockStub("compliance", nil)
	ctx := new(contractapi.TransactionContext)
	ctx.SetStub(stub)

	setCreator(t, stub, "Org2MSP") // NOT the authority organisation
	stub.MockTransactionStart("r1")
	if err := cc.RegisterIssuer(ctx, rawPubKeyHex); err == nil {
		t.Error("Org2MSP managed to register an issuer (governance rejection expected)")
	}
	stub.MockTransactionEnd("r1")

	setCreator(t, stub, registryAdminMSP) // the registry authority
	stub.MockTransactionStart("r2")
	if err := cc.RegisterIssuer(ctx, rawPubKeyHex); err != nil {
		t.Errorf("%s could not register an issuer: %v", registryAdminMSP, err)
	}
	stub.MockTransactionEnd("r2")
}

// SubmitEvidence rejects records from an unregistered issuer (the key comes from the
// on-chain registry, not from the submitter).
func TestSubmitRejectsUnregisteredIssuer(t *testing.T) {
	data := readIncidentLedger(t)
	var raw []json.RawMessage
	json.Unmarshal(data, &raw)

	cc := new(ComplianceContract)
	stub := shimtest.NewMockStub("compliance", nil)
	ctx := new(contractapi.TransactionContext)
	ctx.SetStub(stub)
	setCreator(t, stub, registryAdminMSP)
	// Does NOT register the issuer.
	stub.MockTransactionStart("s")
	if err := cc.SubmitEvidence(ctx, string(raw[0])); err == nil {
		t.Error("accepted a record from an unregistered issuer (rejection expected)")
	}
	stub.MockTransactionEnd("s")
}

// Proves that the HARDENED VerifyChain catches tampering of a record ALREADY on the
// ledger, not only at submission: it corrupts the decision of a stored record and
// confirms that VerifyChain reports a record_hash mismatch, which is the simulator's
// content-integrity guarantee, now on-chain as well.
func TestVerifyChainCatchesStoredTamper(t *testing.T) {
	data := readIncidentLedger(t)
	var raw []json.RawMessage
	json.Unmarshal(data, &raw)

	cc, ctx, stub := newCtxWithIssuer(t)
	for i, r := range raw {
		stub.MockTransactionStart(fmt.Sprintf("tx%d", i))
		if err := cc.SubmitEvidence(ctx, string(r)); err != nil {
			t.Fatalf("SubmitEvidence #%d: %v", i, err)
		}
		stub.MockTransactionEnd(fmt.Sprintf("tx%d", i))
	}

	// Corrupt the first record directly in the state (under its sequence key).
	var rec map[string]interface{}
	json.Unmarshal(raw[0], &rec)
	rec["decision"] = "approved" // record_hash no longer matches
	tb, _ := json.Marshal(rec)
	stub.MockTransactionStart("corrupt")
	stub.PutState("ev000000000000", tb)
	stub.MockTransactionEnd("corrupt")

	msg, err := cc.VerifyChain(ctx)
	if err != nil {
		t.Fatalf("VerifyChain: %v", err)
	}
	if !strings.Contains(msg, "record_hash mismatch") {
		t.Errorf("VerifyChain did not detect content tampering: %q", msg)
	}

	// Removing the last record leaves a shorter chain that is consistent on its
	// own; only the head pointer shows that something is missing.
	cc, ctx, stub = newCtxWithIssuer(t)
	for i, r := range raw {
		stub.MockTransactionStart(fmt.Sprintf("ty%d", i))
		if err := cc.SubmitEvidence(ctx, string(r)); err != nil {
			t.Fatalf("SubmitEvidence #%d: %v", i, err)
		}
		stub.MockTransactionEnd(fmt.Sprintf("ty%d", i))
	}
	stub.MockTransactionStart("truncate")
	stub.DelState(fmt.Sprintf("ev%012d", len(raw)-1))
	stub.MockTransactionEnd("truncate")
	msg, err = cc.VerifyChain(ctx)
	if err != nil {
		t.Fatalf("VerifyChain: %v", err)
	}
	if !strings.Contains(msg, "missing from the end") {
		t.Errorf("VerifyChain did not detect a truncated chain: %q", msg)
	}
}

// TestCurrentPythonLedgerVerifiesInGo pins the Python↔Go serialisation contract.
//
// The evidence model grew from 19 to 23 fields in September 2026 (metrics,
// policy_id, policy_hash, rule_id). The Go struct was not updated, so
// encoding/json silently dropped the four unknown fields and every record
// recomputed to a different hash: the migration verified a format the
// simulator no longer wrote. Two distinct defects had to be fixed, and this
// test fails if either regresses.
//
//  1. the four fields must exist on the struct, or they vanish on Unmarshal;
//  2. canonicalJSON must keep number literals, because Python writes 0.0
//     where a float64 round-trip writes 0 — one byte, and the hash diverges.
//     Record #5 (audit_query) carries demographic_parity_diff = 0.0 and is
//     the case that catches it.
func TestCurrentPythonLedgerVerifiesInGo(t *testing.T) {
	raw, err := os.ReadFile("testdata_ledger_atual.json")
	if err != nil {
		t.Fatalf("fixture absent: %v", err)
	}
	var ledger []EvidenceRecord
	if err := json.Unmarshal(raw, &ledger); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(ledger) == 0 {
		t.Fatal("empty fixture")
	}
	for i, rec := range ledger {
		signed := rec.RecordHash
		rec.RecordHash, rec.IssuerSignatureBase64, rec.ChainHash = "", "", ""
		body, err := canonicalJSON(rec)
		if err != nil {
			t.Fatalf("record %d: canonicalJSON: %v", i, err)
		}
		sum := sha256.Sum256(body)
		if got := hex.EncodeToString(sum[:]); got != signed {
			t.Errorf("record %d (%s): Go recomputed %s, Python signed %s",
				i, scenarioLabel(rec.ScenarioID), got[:16], signed[:16])
		}
	}
}

// scenarioLabel renders a scenario_id for test output, where nil means the
// issuer wrote JSON null rather than a name.
func scenarioLabel(s *string) string {
	if s == nil {
		return "<null>"
	}
	return *s
}

// TestBoundaryLedgerVerifiesInGo pins the input boundary, not just the happy
// path. testdata_fronteiras.json is produced by the Python issuer from the
// matrix in tests/test_fronteiras.py: scenario_id absent, null, empty and
// named; identity fields given as a list and as a number; rejections by
// threshold, by missing approval and by unserialisable metrics.
//
// Every one of those records is something the issuer accepts and signs, so
// every one of them has to be readable and reproducible here. Before the
// September 2026 fix, a null scenario_id decoded as "" and re-encoded as "",
// and a rejection carrying a numeric artifact_id did not decode at all: the
// canonical six records passed while four boundary records did not.
func TestBoundaryLedgerVerifiesInGo(t *testing.T) {
	raw, err := os.ReadFile("testdata_fronteiras.json")
	if err != nil {
		t.Fatalf("boundary ledger missing: %v", err)
	}
	var records []json.RawMessage
	if err := json.Unmarshal(raw, &records); err != nil {
		t.Fatalf("boundary ledger unreadable: %v", err)
	}
	if len(records) == 0 {
		t.Fatal("boundary ledger is empty")
	}
	for i, item := range records {
		var signed struct {
			RecordHash string `json:"record_hash"`
		}
		if err := json.Unmarshal(item, &signed); err != nil {
			t.Fatalf("record %d: %v", i, err)
		}
		var rec EvidenceRecord
		if err := json.Unmarshal(item, &rec); err != nil {
			t.Errorf("record %d (%s): does not decode into the contract: %v",
				i, scenarioLabel(rec.ScenarioID), err)
			continue
		}
		body, err := canonicalJSON(stripDerived(rec))
		if err != nil {
			t.Errorf("record %d: canonicalJSON: %v", i, err)
			continue
		}
		sum := sha256.Sum256(body)
		if got := hex.EncodeToString(sum[:]); got != signed.RecordHash {
			t.Errorf("record %d (%s): Go recomputed %s, Python signed %s",
				i, scenarioLabel(rec.ScenarioID), got[:16], signed.RecordHash[:16])
		}
	}
}

// The executable starts with contractapi.NewChaincode, which inspects every
// exported method and refuses types it cannot describe, such as a pointer field
// in a returned struct. The other tests call the methods directly and would not
// notice. This one goes through the same constructor, and checks that the
// queries hand back the stored bytes, a null scenario_id included.
func TestContractBootstraps(t *testing.T) {
	if _, err := contractapi.NewChaincode(&ComplianceContract{}); err != nil {
		t.Fatalf("contractapi.NewChaincode refused the contract: %v", err)
	}

	raw, err := os.ReadFile("testdata_fronteiras.json")
	if err != nil {
		t.Fatalf("boundary ledger missing: %v", err)
	}
	var records []json.RawMessage
	if err := json.Unmarshal(raw, &records); err != nil || len(records) == 0 {
		t.Fatalf("boundary ledger unreadable or empty: %v", err)
	}
	var nullIdx = -1
	for i, r := range records {
		var m map[string]interface{}
		json.Unmarshal(r, &m)
		if v, ok := m["scenario_id"]; ok && v == nil {
			nullIdx = i
			break
		}
	}
	if nullIdx < 0 {
		t.Fatal("boundary ledger has no record with scenario_id = null")
	}
	cc, ctx, stub := newCtxWithIssuer(t)
	for i, r := range records[:nullIdx+1] {
		stub.MockTransactionStart(fmt.Sprintf("b%d", i))
		if err := cc.SubmitEvidence(ctx, string(r)); err != nil {
			t.Fatalf("SubmitEvidence(boundary record %d): %v", i, err)
		}
		stub.MockTransactionEnd(fmt.Sprintf("b%d", i))
	}
	got, err := cc.GetEvidence(ctx, mustEvidenceID(records[nullIdx]))
	if err != nil {
		t.Fatalf("GetEvidence: %v", err)
	}
	var m map[string]interface{}
	if err := json.Unmarshal([]byte(got), &m); err != nil {
		t.Fatalf("GetEvidence returned unreadable JSON: %v", err)
	}
	if v, ok := m["scenario_id"]; !ok || v != nil {
		t.Errorf("scenario_id came back as %#v, expected null", v)
	}
	list, err := cc.QueryByRequirement(ctx, "no-such-article")
	if err != nil || list != "[]" {
		t.Errorf("QueryByRequirement(unknown) = %q, %v; expected \"[]\"", list, err)
	}
}
