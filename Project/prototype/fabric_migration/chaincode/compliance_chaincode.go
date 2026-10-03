// Fabric evidence contract: registry-based issuer verification and ordered records.
// The demonstration deployment uses AND(Org1MSP.peer, Org2MSP.peer) endorsement;
// the peers' validation step enforces it at commit, not this code.
// This file contains the current implementation; fabric_notes holds historical code.
//
// GetEvidence and QueryByRequirement return the stored JSON, not the struct:
// contractapi.NewChaincode rejects pointer fields such as ScenarioID in returned
// types, and the stored bytes keep scenario_id null exactly as it was signed.

package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"

	"github.com/hyperledger/fabric-chaincode-go/pkg/cid"
	"github.com/hyperledger/fabric-chaincode-go/shim"
	"github.com/hyperledger/fabric-contract-api-go/contractapi"
)

const (
	genesisHash = "0000000000000000000000000000000000000000000000000000000000000000"
	// headKey holds the chain head ({seq, chain_hash}) as a single O(1) state
	// entry. Reading AND writing it in every SubmitEvidence makes Fabric's MVCC
	// reject concurrent submissions (read-conflict on the same key), enforcing
	// serial ordering in the chaincode rather than relying on the client.
	// NOTE: must NOT start with "_" — CouchDB reserves leading-underscore keys
	// (surfaced only when running on CouchDB; LevelDB/MockStub allowed "__head__").
	// It also sits outside the ["ev","ew") evidence range, so range scans skip it.
	headKey = "meta~head"
	// issuerPrefix keys the registry of authorised issuer public keys. The
	// verification key comes from this trusted on-chain registry, not from the
	// submitter, so a caller cannot supply an arbitrary key for a fingerprint.
	issuerPrefix = "issuer~"
	// evLow/evHigh bound the range of evidence records (keys "ev%012d"), so range
	// scans skip the head pointer and the issuer registry.
	evLow  = "ev"
	evHigh = "ew"
	// registryAdminMSP is the organisation acting as the compliance authority:
	// only its identities may register issuer keys (governance).
	registryAdminMSP = "Org1MSP"
)

type chainHeadState struct {
	Seq       int    `json:"seq"`
	ChainHash string `json:"chain_hash"`
}

// Canonical hashing uses alphabetically ordered JSON map keys, so field order
// here does not matter. Every signed field must be declared, though:
// encoding/json drops unknown fields on Unmarshal without an error.
type EvidenceRecord struct {
	EvidenceID            string   `json:"evidence_id"`
	// Pointer, not string: the issuer writes JSON null when no scenario is
	// named, and a plain string would silently decode null as "" and then
	// re-encode it as "", changing the signed body. A pointer round-trips
	// null as null and an empty string as an empty string.
	ScenarioID            *string  `json:"scenario_id"`
	EventType             string   `json:"event_type"`
	ArtifactID            string   `json:"artifact_id"`
	ArtifactType          string   `json:"artifact_type"`
	PipelineStage         string   `json:"pipeline_stage"`
	Timestamp             string   `json:"timestamp"`
	Decision              string   `json:"decision"`
	Reason                string   `json:"reason"`
	ArtifactHash          string   `json:"artifact_hash"`
	RequirementsCovered   []string `json:"requirements_covered"`
	IssuerID              string   `json:"issuer_id"`
	IssuerPubkeyFprint    string   `json:"issuer_pubkey_fingerprint"`
	SigAlg                string   `json:"sig_alg"`
	HashAlg               string   `json:"hash_alg"`
	ParentHash            string   `json:"parent_hash"`
	// Added with the 23-field evidence model (September 2026). Metrics is kept
	// as RawMessage so the issuer's exact number literals survive: Python emits
	// 0.0 where Go's float64 would emit 0, and that one byte breaks the hash.
	// omitempty keeps records written before these fields existed verifiable:
	// they were signed without them, so emitting null would change their body.
	Metrics               json.RawMessage `json:"metrics,omitempty"`
	PolicyID              string   `json:"policy_id,omitempty"`
	PolicyHash            string   `json:"policy_hash,omitempty"`
	RuleID                string   `json:"rule_id,omitempty"`
	RecordHash            string   `json:"record_hash,omitempty"`
	IssuerSignatureBase64 string   `json:"issuer_signature,omitempty"`
	ChainHash             string   `json:"chain_hash,omitempty"`
	// SubmitterMSP/SubmitterID are stamped by the chaincode from the submitting
	// Fabric identity (MSP binding). They are provenance ADDED on-chain, NOT part
	// of the issuer-signed body, so stripDerived removes them before any hash.
	SubmitterMSP string `json:"submitter_msp,omitempty"`
	SubmitterID  string `json:"submitter_id,omitempty"`
}

type ComplianceContract struct {
	contractapi.Contract
}

// RegisterIssuer records an authorised issuer Ed25519 public key in the on-chain
// registry, keyed by its SHA-256 fingerprint. Governance: only identities of the
// compliance-authority organisation (registryAdminMSP) may register issuers.
func (c *ComplianceContract) RegisterIssuer(
	ctx contractapi.TransactionContextInterface,
	pubKeyHex string,
) error {
	mspID, err := cid.GetMSPID(ctx.GetStub())
	if err != nil {
		return fmt.Errorf("cannot read caller identity: %w", err)
	}
	if mspID != registryAdminMSP {
		return fmt.Errorf("only %s may register issuers (caller: %s)", registryAdminMSP, mspID)
	}
	pubkey, err := hex.DecodeString(pubKeyHex)
	if err != nil || len(pubkey) != ed25519.PublicKeySize {
		return fmt.Errorf("invalid issuer public key")
	}
	return ctx.GetStub().PutState(issuerPrefix+sha256Hex(pubkey), []byte(pubKeyHex))
}

// registeredIssuer returns the authorised public key for a fingerprint, or an
// error if the issuer is not registered.
func registeredIssuer(ctx contractapi.TransactionContextInterface, fingerprint string) ([]byte, error) {
	raw, err := ctx.GetStub().GetState(issuerPrefix + fingerprint)
	if err != nil {
		return nil, err
	}
	if raw == nil {
		return nil, fmt.Errorf("issuer %s is not registered", fingerprint)
	}
	pubkey, err := hex.DecodeString(string(raw))
	if err != nil || len(pubkey) != ed25519.PublicKeySize {
		return nil, fmt.Errorf("corrupt issuer registry entry")
	}
	return pubkey, nil
}

// SubmitEvidence ingests a record produced by the off-chain Compliance Policy
// Engine, validates it against the trusted issuer registry and the chain head,
// stamps the submitting Fabric identity, and persists it.
//
// The verification key is fetched from the on-chain registry by the record's
// issuer_pubkey_fingerprint — NOT supplied by the caller — so a caller cannot
// present an arbitrary key. Ordering and the sequence number come from the O(1)
// head pointer (headKey); reading and writing it serialises concurrent submits
// via Fabric MVCC.
func (c *ComplianceContract) SubmitEvidence(
	ctx contractapi.TransactionContextInterface,
	recordJSON string,
) error {
	var rec EvidenceRecord
	if err := json.Unmarshal([]byte(recordJSON), &rec); err != nil {
		return fmt.Errorf("invalid record: %w", err)
	}

	// Verify the Ed25519 signature with the REGISTERED issuer key for this
	// fingerprint (rejects unregistered issuers and forged keys).
	pubkey, err := registeredIssuer(ctx, rec.IssuerPubkeyFprint)
	if err != nil {
		return err
	}
	body := stripDerived(rec)
	bodyBytes, err := canonicalJSON(body)
	if err != nil {
		return err
	}
	sig, err := base64.StdEncoding.DecodeString(rec.IssuerSignatureBase64)
	if err != nil {
		return fmt.Errorf("invalid signature encoding: %w", err)
	}
	if !ed25519.Verify(pubkey, bodyBytes, sig) {
		return fmt.Errorf("issuer signature verification failed")
	}

	// Recompute record_hash and chain_hash from the body; reject if mismatched.
	recordHash := sha256Hex(bodyBytes)
	if recordHash != rec.RecordHash {
		return fmt.Errorf("record_hash mismatch")
	}

	// O(1) head pointer: parent must equal the current head; read+write of headKey
	// gives MVCC serialisation of concurrent submits.
	head, err := getHead(ctx)
	if err != nil {
		return err
	}
	if rec.ParentHash != head.ChainHash {
		return fmt.Errorf("parent_hash mismatch: got %s, expected %s", rec.ParentHash, head.ChainHash)
	}
	if sha256Hex([]byte(rec.ParentHash+recordHash)) != rec.ChainHash {
		return fmt.Errorf("chain_hash mismatch")
	}

	// MSP binding: stamp the submitting Fabric identity as on-chain provenance.
	if mspID, e := cid.GetMSPID(ctx.GetStub()); e == nil {
		rec.SubmitterMSP = mspID
	}
	if id, e := cid.GetID(ctx.GetStub()); e == nil {
		rec.SubmitterID = id
	}
	stored, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	if err := ctx.GetStub().PutState(fmt.Sprintf("ev%012d", head.Seq), stored); err != nil {
		return err
	}

	newHead, err := json.Marshal(chainHeadState{Seq: head.Seq + 1, ChainHash: rec.ChainHash})
	if err != nil {
		return err
	}
	return ctx.GetStub().PutState(headKey, newHead)
}

// VerifyChain walks the ledger from genesis and returns the first inconsistency,
// or "chain valid: N records" if intact. For each record it recomputes record_hash
// and chain_hash and verifies the Ed25519 issuer signature against the key held in
// the on-chain issuer registry. The simulator runs the same integrity checks; what
// the registry adds is governed authorisation of issuers. Tamper of any body field
// is caught by the recomputed record_hash; an unregistered or wrong-key issuer is
// caught by the signature check.
func (c *ComplianceContract) VerifyChain(
	ctx contractapi.TransactionContextInterface,
) (string, error) {
	iter, err := ctx.GetStub().GetStateByRange(evLow, evHigh)
	if err != nil {
		return "", err
	}
	defer iter.Close()

	previous := genesisHash
	count := 0
	for iter.HasNext() {
		kv, err := iter.Next()
		if err != nil {
			return "", err
		}
		var rec EvidenceRecord
		if err := json.Unmarshal(kv.Value, &rec); err != nil {
			return "", err
		}
		bodyBytes, err := canonicalJSON(stripDerived(rec))
		if err != nil {
			return "", err
		}
		recordHash := sha256Hex(bodyBytes)
		if recordHash != rec.RecordHash {
			return fmt.Sprintf("record_hash mismatch at %s", rec.EvidenceID), nil
		}
		if rec.ParentHash != previous {
			return fmt.Sprintf("parent_hash mismatch at %s", rec.EvidenceID), nil
		}
		if sha256Hex([]byte(rec.ParentHash+recordHash)) != rec.ChainHash {
			return fmt.Sprintf("chain_hash mismatch at %s", rec.EvidenceID), nil
		}
		pubkey, err := registeredIssuer(ctx, rec.IssuerPubkeyFprint)
		if err != nil {
			return fmt.Sprintf("issuer not registered at %s", rec.EvidenceID), nil
		}
		sig, _ := base64.StdEncoding.DecodeString(rec.IssuerSignatureBase64)
		if !ed25519.Verify(pubkey, bodyBytes, sig) {
			return fmt.Sprintf("signature mismatch at %s", rec.EvidenceID), nil
		}
		previous = rec.ChainHash
		count++
	}
	// The walk only sees the records that are present. A record removed from
	// the end leaves a shorter chain that is still internally consistent, so
	// its end is compared with the head pointer SubmitEvidence maintains.
	head, err := getHead(ctx)
	if err != nil {
		return "", err
	}
	if head.Seq != count || head.ChainHash != previous {
		return fmt.Sprintf("chain ends after %d records but the head pointer records %d: "+
			"records are missing from the end", count, head.Seq), nil
	}
	return fmt.Sprintf("chain valid: %d records", count), nil
}

// QueryByRequirement returns all evidence records that cite a given AI Act
// article (e.g. "Art.15", "Art.78") in their requirements_covered field.
func (c *ComplianceContract) QueryByRequirement(
	ctx contractapi.TransactionContextInterface,
	article string,
) (string, error) {
	iter, err := ctx.GetStub().GetStateByRange(evLow, evHigh)
	if err != nil {
		return "", err
	}
	defer iter.Close()

	var results []json.RawMessage
	for iter.HasNext() {
		kv, err := iter.Next()
		if err != nil {
			return "", err
		}
		var rec EvidenceRecord
		if err := json.Unmarshal(kv.Value, &rec); err != nil {
			continue
		}
		for _, r := range rec.RequirementsCovered {
			if r == article {
				results = append(results, json.RawMessage(kv.Value))
				break
			}
		}
	}
	if len(results) == 0 {
		return "[]", nil
	}
	return "[" + string(bytes.Join(rawSlices(results), []byte(","))) + "]", nil
}

func rawSlices(rs []json.RawMessage) [][]byte {
	out := make([][]byte, len(rs))
	for i, r := range rs {
		out[i] = r
	}
	return out
}

// GetEvidence returns a single record by evidence_id. Records are keyed by
// sequence (see SubmitEvidence), so this scans the ordered range and matches on
// the evidence_id field rather than doing a direct GetState by key.
func (c *ComplianceContract) GetEvidence(
	ctx contractapi.TransactionContextInterface,
	evidenceID string,
) (string, error) {
	iter, err := ctx.GetStub().GetStateByRange(evLow, evHigh)
	if err != nil {
		return "", err
	}
	defer iter.Close()
	for iter.HasNext() {
		kv, err := iter.Next()
		if err != nil {
			return "", err
		}
		var rec EvidenceRecord
		if err := json.Unmarshal(kv.Value, &rec); err != nil {
			continue
		}
		if rec.EvidenceID == evidenceID {
			return string(kv.Value), nil
		}
	}
	return "", fmt.Errorf("evidence %s not found", evidenceID)
}

// ----- helpers -----------------------------------------------------------

// getHead reads the O(1) chain head pointer ({seq, chain_hash}). Before the first
// record it returns {0, genesisHash}. Reading it in SubmitEvidence and writing it
// back makes Fabric's MVCC reject concurrent submits (read-conflict on headKey),
// so chain ordering is enforced by the chaincode, not by the client.
func getHead(ctx contractapi.TransactionContextInterface) (chainHeadState, error) {
	raw, err := ctx.GetStub().GetState(headKey)
	if err != nil {
		return chainHeadState{}, err
	}
	if raw == nil {
		return chainHeadState{Seq: 0, ChainHash: genesisHash}, nil
	}
	var h chainHeadState
	if err := json.Unmarshal(raw, &h); err != nil {
		return chainHeadState{}, err
	}
	return h, nil
}

func stripDerived(rec EvidenceRecord) EvidenceRecord {
	rec.RecordHash = ""
	rec.IssuerSignatureBase64 = ""
	rec.ChainHash = ""
	// Submitter provenance is added on-chain, not part of the issuer-signed body.
	rec.SubmitterMSP = ""
	rec.SubmitterID = ""
	return rec
}

// canonicalJSON reproduces Python's json.dumps(sort_keys=True,
// separators=(",",":"), ensure_ascii=True) byte for byte on the evidence body:
// strings, string lists, null in scenario_id and the numbers inside metrics.
// HTML characters stay literal (SetEscapeHTML(false)), non-ASCII becomes \uXXXX
// (asciiEscape) and UseNumber keeps literals such as 0.0 unchanged. These bytes
// must match Python's before any hash is compared. It is not a general
// canonicaliser; arbitrary JSON would need RFC 8785 on both sides.
func canonicalJSON(v interface{}) ([]byte, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	var m map[string]interface{}
	// UseNumber keeps every number as its original literal. Without it a
	// round-trip through float64 rewrites 0.0 as 0 and the recomputed hash
	// diverges from the one the issuer signed.
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(&m); err != nil {
		return nil, err
	}
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false) // axis 1
	if err := enc.Encode(m); err != nil {
		return nil, err
	}
	compact := bytes.TrimRight(buf.Bytes(), "\n")
	return asciiEscape(compact), nil // axis 2
}

// asciiEscape converts every non-ASCII rune to \uXXXX (with surrogate pairs for
// the astral plane), mirroring Python's ensure_ascii=True. Safe byte-wise:
// non-ASCII only occurs inside JSON string literals; all structure is ASCII.
func asciiEscape(b []byte) []byte {
	var out bytes.Buffer
	for _, r := range string(b) {
		switch {
		case r < 0x7f:
			// Printable/structural ASCII stays literal. 0x00-0x1F never reach here
			// (the encoder already escaped them). 0x7F (DEL) is ASCII but Python's
			// ensure_ascii escapes it to backslash-u-007f, so it must be escaped too.
			out.WriteRune(r)
		case r <= 0xFFFF:
			fmt.Fprintf(&out, "\\u%04x", r)
		default:
			r -= 0x10000
			fmt.Fprintf(&out, "\\u%04x\\u%04x", 0xD800+(r>>10), 0xDC00+(r&0x3FF))
		}
	}
	return out.Bytes()
}

func sha256Hex(b []byte) string {
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}

func main() {
	cc, err := contractapi.NewChaincode(&ComplianceContract{})
	if err != nil {
		panic(err)
	}
	if addr := os.Getenv("CHAINCODE_SERVER_ADDRESS"); addr != "" {
		server := &shim.ChaincodeServer{
			CCID:     os.Getenv("CHAINCODE_ID"),
			Address:  addr,
			CC:       cc,
			TLSProps: shim.TLSProperties{Disabled: true},
		}
		if err := server.Start(); err != nil {
			panic(err)
		}
		return
	}
	if err := cc.Start(); err != nil {
		panic(err)
	}
}
