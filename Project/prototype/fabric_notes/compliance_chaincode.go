// HISTORICAL IMPLEMENTATION: retained for comparison with the migration.
// This version predates issuer registration, sequence keys and canonicalisation fixes.
// It is not the deployable evidence contract. Use fabric_migration/chaincode instead.

package main

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"

	"github.com/hyperledger/fabric-contract-api-go/contractapi"
)

const genesisHash = "0000000000000000000000000000000000000000000000000000000000000000"

// Canonical hashing uses alphabetically ordered JSON map keys.
type EvidenceRecord struct {
	EvidenceID            string   `json:"evidence_id"`
	ScenarioID            string   `json:"scenario_id"`
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
	RecordHash            string   `json:"record_hash,omitempty"`
	IssuerSignatureBase64 string   `json:"issuer_signature,omitempty"`
	ChainHash             string   `json:"chain_hash,omitempty"`
}

type ComplianceContract struct {
	contractapi.Contract
}

// SubmitEvidence ingests a record produced by the off-chain Compliance Policy
// Engine, validates the chain anchors, and persists it to the channel ledger.
func (c *ComplianceContract) SubmitEvidence(
	ctx contractapi.TransactionContextInterface,
	recordJSON string,
) error {
	var rec EvidenceRecord
	if err := json.Unmarshal([]byte(recordJSON), &rec); err != nil {
		return fmt.Errorf("invalid record: %w", err)
	}

	// Recompute parent_hash from the most recent record on this channel.
	expectedParent, err := c.lastChainHash(ctx)
	if err != nil {
		return err
	}
	if rec.ParentHash != expectedParent {
		return fmt.Errorf(
			"parent_hash mismatch: got %s, expected %s",
			rec.ParentHash, expectedParent,
		)
	}

	// Verify Ed25519 signature over the canonical body.
	body := stripDerived(rec)
	bodyBytes, err := canonicalJSON(body)
	if err != nil {
		return err
	}
	pubkey, err := hex.DecodeString(rec.IssuerPubkeyFprint)
	if err != nil || len(pubkey) != ed25519.PublicKeySize {
		return fmt.Errorf("invalid issuer public key fingerprint")
	}
	sig, err := base64.StdEncoding.DecodeString(rec.IssuerSignatureBase64)
	if err != nil {
		return fmt.Errorf("invalid signature encoding: %w", err)
	}
	if !ed25519.Verify(pubkey, bodyBytes, sig) {
		return fmt.Errorf("issuer signature verification failed")
	}

	// Recompute record_hash and chain_hash; reject if mismatched.
	recordHash := sha256Hex(bodyBytes)
	if recordHash != rec.RecordHash {
		return fmt.Errorf("record_hash mismatch")
	}
	expectedChain := sha256Hex([]byte(rec.ParentHash + recordHash))
	if expectedChain != rec.ChainHash {
		return fmt.Errorf("chain_hash mismatch")
	}

	// Persist by composite key (channel + evidence_id) for fast retrieval.
	return ctx.GetStub().PutState(rec.EvidenceID, []byte(recordJSON))
}

// VerifyChain walks the entire ledger from genesis and returns the first
// inconsistency found, or nil if the chain is intact.
func (c *ComplianceContract) VerifyChain(
	ctx contractapi.TransactionContextInterface,
) (string, error) {
	iter, err := ctx.GetStub().GetStateByRange("", "")
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
		if rec.ParentHash != previous {
			return fmt.Sprintf("parent_hash mismatch at %s", rec.EvidenceID), nil
		}
		previous = rec.ChainHash
		count++
	}
	return fmt.Sprintf("chain valid: %d records", count), nil
}

// QueryByRequirement returns all evidence records that cite a given AI Act
// article (e.g. "Art.15", "Art.78") in their requirements_covered field.
func (c *ComplianceContract) QueryByRequirement(
	ctx contractapi.TransactionContextInterface,
	article string,
) ([]*EvidenceRecord, error) {
	iter, err := ctx.GetStub().GetStateByRange("", "")
	if err != nil {
		return nil, err
	}
	defer iter.Close()

	var results []*EvidenceRecord
	for iter.HasNext() {
		kv, err := iter.Next()
		if err != nil {
			return nil, err
		}
		var rec EvidenceRecord
		if err := json.Unmarshal(kv.Value, &rec); err != nil {
			continue
		}
		for _, r := range rec.RequirementsCovered {
			if r == article {
				results = append(results, &rec)
				break
			}
		}
	}
	return results, nil
}

// GetEvidence returns a single record by evidence_id.
func (c *ComplianceContract) GetEvidence(
	ctx contractapi.TransactionContextInterface,
	evidenceID string,
) (*EvidenceRecord, error) {
	raw, err := ctx.GetStub().GetState(evidenceID)
	if err != nil || raw == nil {
		return nil, fmt.Errorf("evidence %s not found", evidenceID)
	}
	var rec EvidenceRecord
	if err := json.Unmarshal(raw, &rec); err != nil {
		return nil, err
	}
	return &rec, nil
}

// ----- helpers -----------------------------------------------------------

func (c *ComplianceContract) lastChainHash(
	ctx contractapi.TransactionContextInterface,
) (string, error) {
	iter, err := ctx.GetStub().GetStateByRange("", "")
	if err != nil {
		return "", err
	}
	defer iter.Close()

	last := genesisHash
	for iter.HasNext() {
		kv, err := iter.Next()
		if err != nil {
			return "", err
		}
		var rec EvidenceRecord
		if err := json.Unmarshal(kv.Value, &rec); err != nil {
			continue
		}
		last = rec.ChainHash
	}
	return last, nil
}

func stripDerived(rec EvidenceRecord) EvidenceRecord {
	rec.RecordHash = ""
	rec.IssuerSignatureBase64 = ""
	rec.ChainHash = ""
	return rec
}

func canonicalJSON(v interface{}) ([]byte, error) {
	// json.Marshal sorts struct fields by tag order; we mirror Python's
	// sort_keys=True by serialising via a sorted map.
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	var m map[string]interface{}
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, err
	}
	return json.Marshal(m) // Go json.Marshal on map sorts keys alphabetically
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
	if err := cc.Start(); err != nil {
		panic(err)
	}
}
