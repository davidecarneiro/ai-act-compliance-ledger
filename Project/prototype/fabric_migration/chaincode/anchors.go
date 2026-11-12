package main

// Batch anchoring (WP7). Instead of submitting every record, the issuer chains
// records locally and, every N records, submits one signed statement: the
// RFC 9162 Merkle root over the batch's record_hash values, the batch's place
// in the stream (first_seq, last_seq) and the chain_hash of its last record
// (compliance_ledger_sim/batch_anchor.py builds and signs it).
//
// AnchorBatch accepts a statement only if it is signed by a registered issuer
// and follows the previous batch of the same stream; the submitting Fabric
// identity is stamped next to it. VerifyInclusion checks that a record (body,
// hashes and issuer signature) is in an anchored batch at the position its
// proof claims. Per-record submission (SubmitEvidence) is unchanged and is the
// N = 1 mode of the measurements.
//
// Several streams can share a channel (one per measurement configuration);
// each keeps its own head.

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/gowebpki/jcs"
	"github.com/hyperledger/fabric-chaincode-go/pkg/cid"
	"github.com/hyperledger/fabric-contract-api-go/contractapi"
)

const (
	anchorType = "evidence-batch-anchor"
	anchorTree = "rfc9162-sha256"
	// Keys sort before "ev", outside the evidence range VerifyChain scans, and
	// do not start with "_" (reserved by CouchDB).
	anchorPrefix     = "anc~"     // anc~<stream>~<first_seq, 12 digits>
	anchorHeadPrefix = "anchead~" // anchead~<stream>
)

type anchorStatement struct {
	Type                    string `json:"type"`
	Stream                  string `json:"stream"`
	FirstSeq                uint64 `json:"first_seq"`
	LastSeq                 uint64 `json:"last_seq"`
	Size                    uint64 `json:"size"`
	MerkleRoot              string `json:"merkle_root"`
	HeadChainHash           string `json:"head_chain_hash"`
	IssuerPubkeyFingerprint string `json:"issuer_pubkey_fingerprint"`
	Tree                    string `json:"tree"`
	AnchoredAt              string `json:"anchored_at"`
}

type signedAnchor struct {
	Statement json.RawMessage `json:"statement"`
	Signature string          `json:"signature"`
}

// storedAnchor is what AnchorBatch writes: the statement as signed, its
// signature, and the provenance the chaincode adds.
type storedAnchor struct {
	Statement    json.RawMessage `json:"statement"`
	Signature    string          `json:"signature"`
	SubmitterMSP string          `json:"submitter_msp"`
	SubmitterID  string          `json:"submitter_id"`
	TxID         string          `json:"tx_id"`
}

type anchorHeadState struct {
	LastSeq       uint64 `json:"last_seq"`
	HeadChainHash string `json:"head_chain_hash"`
	Batches       uint64 `json:"batches"`
}

type inclusionProof struct {
	Stream    string   `json:"stream"`
	FirstSeq  uint64   `json:"first_seq"`
	LeafIndex uint64   `json:"leaf_index"`
	TreeSize  uint64   `json:"tree_size"`
	Path      []string `json:"path"`
}

func anchorKey(stream string, firstSeq uint64) string {
	return fmt.Sprintf("%s%s~%012d", anchorPrefix, stream, firstSeq)
}

func isHex64(s string) bool {
	if len(s) != 64 {
		return false
	}
	_, err := hex.DecodeString(s)
	return err == nil && strings.ToLower(s) == s
}

func validStream(s string) bool {
	if s == "" || len(s) > 64 {
		return false
	}
	for _, r := range s {
		if r < 0x21 || r > 0x7e || r == '~' {
			return false
		}
	}
	return true
}

// parseStatement decodes a statement strictly: unknown members are refused,
// so what is checked is everything that was signed.
func parseStatement(raw json.RawMessage) (anchorStatement, error) {
	var s anchorStatement
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&s); err != nil {
		return s, fmt.Errorf("invalid anchor statement: %w", err)
	}
	switch {
	case s.Type != anchorType:
		return s, fmt.Errorf("anchor statement type must be %q", anchorType)
	case s.Tree != anchorTree:
		return s, fmt.Errorf("anchor tree must be %q", anchorTree)
	case !validStream(s.Stream):
		return s, fmt.Errorf("invalid stream name")
	case s.FirstSeq < 1 || s.LastSeq < s.FirstSeq || s.Size != s.LastSeq-s.FirstSeq+1:
		return s, fmt.Errorf("inconsistent first_seq, last_seq and size")
	case !isHex64(s.MerkleRoot) || !isHex64(s.HeadChainHash) || !isHex64(s.IssuerPubkeyFingerprint):
		return s, fmt.Errorf("merkle_root, head_chain_hash and issuer_pubkey_fingerprint must be 64 lowercase hex digits")
	}
	return s, nil
}

func getAnchorHead(ctx contractapi.TransactionContextInterface, stream string) (anchorHeadState, error) {
	raw, err := ctx.GetStub().GetState(anchorHeadPrefix + stream)
	if err != nil || raw == nil {
		return anchorHeadState{}, err
	}
	var h anchorHeadState
	err = json.Unmarshal(raw, &h)
	return h, err
}

// AnchorBatch records one signed batch anchor. It fails (and the transaction
// is not committed) if the statement is malformed, its issuer is not
// registered, its signature does not verify, or it does not follow the
// previous batch of its stream. Reading and writing the stream head serialises
// concurrent anchors of a stream through MVCC, as the evidence head does.
func (c *ComplianceContract) AnchorBatch(
	ctx contractapi.TransactionContextInterface,
	anchorJSON string,
) error {
	var sa signedAnchor
	if err := json.Unmarshal([]byte(anchorJSON), &sa); err != nil {
		return fmt.Errorf("invalid anchor: %w", err)
	}
	s, err := parseStatement(sa.Statement)
	if err != nil {
		return err
	}
	pubkey, err := registeredIssuer(ctx, s.IssuerPubkeyFingerprint)
	if err != nil {
		return err
	}
	canonical, err := jcs.Transform(sa.Statement)
	if err != nil {
		return fmt.Errorf("anchor statement has no canonical form: %w", err)
	}
	sig, err := base64.StdEncoding.DecodeString(sa.Signature)
	if err != nil || !ed25519.Verify(pubkey, canonical, sig) {
		return fmt.Errorf("anchor signature verification failed")
	}
	head, err := getAnchorHead(ctx, s.Stream)
	if err != nil {
		return err
	}
	if s.FirstSeq != head.LastSeq+1 {
		return fmt.Errorf("batch [%d, %d] does not follow the last anchored record %d of stream %s",
			s.FirstSeq, s.LastSeq, head.LastSeq, s.Stream)
	}
	stored := storedAnchor{Statement: sa.Statement, Signature: sa.Signature, TxID: ctx.GetStub().GetTxID()}
	if v, e := cid.GetMSPID(ctx.GetStub()); e == nil {
		stored.SubmitterMSP = v
	}
	if v, e := cid.GetID(ctx.GetStub()); e == nil {
		stored.SubmitterID = v
	}
	value, err := json.Marshal(stored)
	if err != nil {
		return err
	}
	if err := ctx.GetStub().PutState(anchorKey(s.Stream, s.FirstSeq), value); err != nil {
		return err
	}
	next, err := json.Marshal(anchorHeadState{LastSeq: s.LastSeq, HeadChainHash: s.HeadChainHash,
		Batches: head.Batches + 1})
	if err != nil {
		return err
	}
	return ctx.GetStub().PutState(anchorHeadPrefix+s.Stream, next)
}

type inclusionResult struct {
	Included     bool   `json:"included"`
	Reason       string `json:"reason,omitempty"`
	Stream       string `json:"stream,omitempty"`
	Seq          uint64 `json:"seq,omitempty"`
	MerkleRoot   string `json:"merkle_root,omitempty"`
	AnchoredAt   string `json:"anchored_at,omitempty"`
	SubmitterMSP string `json:"submitter_msp,omitempty"`
	TxID         string `json:"tx_id,omitempty"`
}

func inclusionJSON(r inclusionResult) (string, error) {
	b, err := json.Marshal(r)
	return string(b), err
}

// VerifyInclusion checks, without writing, that a record is in an anchored
// batch: its body recomputes to its record_hash, its chain_hash recomputes,
// its issuer is registered and signed it, the anchor was signed by the same
// issuer, and the proof leads from the record_hash at the claimed position to
// the anchored Merkle root. The result is a JSON object; a record that does
// not check out is a result ("included": false, with the reason), not an
// error.
func (c *ComplianceContract) VerifyInclusion(
	ctx contractapi.TransactionContextInterface,
	recordJSON string,
	proofJSON string,
) (string, error) {
	fail := func(reason string) (string, error) {
		return inclusionJSON(inclusionResult{Included: false, Reason: reason})
	}
	var rec EvidenceRecord
	if err := json.Unmarshal([]byte(recordJSON), &rec); err != nil {
		return fail("record is not valid JSON")
	}
	body, _, err := recordBodyBytes([]byte(recordJSON), rec)
	if err != nil {
		return fail("record has no canonical body: " + err.Error())
	}
	recordHash := sha256Hex(body)
	if recordHash != rec.RecordHash {
		return fail("record_hash does not match the body")
	}
	if sha256Hex([]byte(rec.ParentHash+recordHash)) != rec.ChainHash {
		return fail("chain_hash does not recompute")
	}
	pubkey, err := registeredIssuer(ctx, rec.IssuerPubkeyFprint)
	if err != nil {
		return fail("issuer not registered")
	}
	sig, err := base64.StdEncoding.DecodeString(rec.IssuerSignatureBase64)
	if err != nil || !ed25519.Verify(pubkey, body, sig) {
		return fail("issuer signature does not verify")
	}

	var proof inclusionProof
	if err := json.Unmarshal([]byte(proofJSON), &proof); err != nil {
		return fail("proof is not valid JSON")
	}
	if !validStream(proof.Stream) {
		return fail("invalid stream name in proof")
	}
	raw, err := ctx.GetStub().GetState(anchorKey(proof.Stream, proof.FirstSeq))
	if err != nil {
		return "", err
	}
	if raw == nil {
		return fail("no anchor for this batch")
	}
	var stored storedAnchor
	if err := json.Unmarshal(raw, &stored); err != nil {
		return "", err
	}
	s, err := parseStatement(stored.Statement)
	if err != nil {
		return "", err
	}
	if s.IssuerPubkeyFingerprint != rec.IssuerPubkeyFprint {
		return fail("anchor and record have different issuers")
	}
	if proof.TreeSize != s.Size {
		return fail("proof names a batch of another size")
	}
	entry, _ := hex.DecodeString(recordHash)
	root, _ := hex.DecodeString(s.MerkleRoot)
	path := make([][]byte, 0, len(proof.Path))
	for _, p := range proof.Path {
		if !isHex64(p) {
			return fail("proof path holds a value that is not a SHA-256 digest")
		}
		b, _ := hex.DecodeString(p)
		path = append(path, b)
	}
	if !merkleVerifyInclusion(entry, proof.LeafIndex, proof.TreeSize, path, root) {
		return fail("proof does not lead to the anchored root")
	}
	return inclusionJSON(inclusionResult{
		Included: true, Stream: s.Stream, Seq: s.FirstSeq + proof.LeafIndex,
		MerkleRoot: s.MerkleRoot, AnchoredAt: s.AnchoredAt,
		SubmitterMSP: stored.SubmitterMSP, TxID: stored.TxID,
	})
}

// GetAnchors returns the anchors of a stream in order, with the provenance the
// chaincode stamped, and the stream head, as a JSON object.
func (c *ComplianceContract) GetAnchors(
	ctx contractapi.TransactionContextInterface,
	stream string,
) (string, error) {
	if !validStream(stream) {
		return "", fmt.Errorf("invalid stream name")
	}
	iter, err := ctx.GetStub().GetStateByRange(anchorPrefix+stream+"~", anchorPrefix+stream+"~~")
	if err != nil {
		return "", err
	}
	defer iter.Close()
	anchors := []json.RawMessage{}
	for iter.HasNext() {
		kv, err := iter.Next()
		if err != nil {
			return "", err
		}
		anchors = append(anchors, json.RawMessage(kv.Value))
	}
	head, err := getAnchorHead(ctx, stream)
	if err != nil {
		return "", err
	}
	out, err := json.Marshal(map[string]any{"stream": stream, "head": head, "anchors": anchors})
	return string(out), err
}
