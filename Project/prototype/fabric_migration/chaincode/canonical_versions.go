package main

// Versioned canonical form, mirroring compliance_ledger_sim/canonical.py.
//
//   - Schema version 1 (no schema_version field): the form the dissertation
//     shipped, rebuilt from the typed EvidenceRecord by canonicalJSON. Kept
//     byte for byte so the published ledgers keep verifying.
//   - Schema version 2: RFC 8785 (JCS), computed over the record's own JSON
//     members, not over the struct. A field the struct does not declare is
//     therefore still part of the hashed body, and it is stored as submitted:
//     encoding/json can no longer drop a signed field in silence (the defect
//     the version 1 comment on EvidenceRecord warns about).

import (
	"bytes"
	"encoding/json"
	"fmt"

	"github.com/gowebpki/jcs"
)

const (
	schemaV1 = 1
	schemaV2 = 2
)

// derivedKeys are computed from the canonical body; onChainKeys are stamped by
// this chaincode at submission. Neither is part of the issuer-signed body.
var (
	derivedKeys = []string{"record_hash", "issuer_signature", "chain_hash"}
	onChainKeys = []string{"submitter_msp", "submitter_id"}
)

// schemaVersionOf reads the version a record was written under. As in Python,
// an absent field means version 1, an explicit 1 is malformed (version 1
// records never carried the field) and only the JSON integer 2 selects JCS.
func schemaVersionOf(raw []byte) (int, error) {
	var members map[string]json.RawMessage
	if err := json.Unmarshal(raw, &members); err != nil {
		return 0, fmt.Errorf("record is not a JSON object: %w", err)
	}
	v, ok := members["schema_version"]
	if !ok {
		return schemaV1, nil
	}
	switch string(bytes.TrimSpace(v)) {
	case "2":
		return schemaV2, nil
	case "1":
		return 0, fmt.Errorf("schema_version 1 is implicit; a record that names it is malformed")
	default:
		return 0, fmt.Errorf("unsupported schema_version %s", string(v))
	}
}

// canonicalJCS returns the RFC 8785 form of a record's signed body: every
// member except the derived and on-chain ones.
func canonicalJCS(raw []byte) ([]byte, error) {
	// Transform the whole record first. It refuses duplicate member names,
	// invalid UTF-8, lone surrogates and malformed numbers, so none of those
	// can be hidden by the map round trip below (which keeps the last of two
	// duplicate names).
	if _, err := jcs.Transform(raw); err != nil {
		return nil, fmt.Errorf("record has no RFC 8785 form: %w", err)
	}
	var members map[string]json.RawMessage
	if err := json.Unmarshal(raw, &members); err != nil {
		return nil, err
	}
	for _, k := range derivedKeys {
		delete(members, k)
	}
	for _, k := range onChainKeys {
		delete(members, k)
	}
	body, err := json.Marshal(members)
	if err != nil {
		return nil, err
	}
	// json.Marshal may escape HTML characters or reorder members; JCS parses
	// the text again and emits the one canonical form, so neither matters.
	return jcs.Transform(body)
}

// recordBodyBytes returns the canonical bytes the issuer signed, in the form of
// the record's schema version. raw is the record's JSON as submitted or stored;
// rec is the same record decoded into the typed struct (used by version 1).
func recordBodyBytes(raw []byte, rec EvidenceRecord) ([]byte, int, error) {
	version, err := schemaVersionOf(raw)
	if err != nil {
		return nil, 0, err
	}
	switch version {
	case schemaV1:
		b, err := canonicalJSON(stripDerived(rec))
		return b, version, err
	case schemaV2:
		b, err := canonicalJCS(raw)
		return b, version, err
	}
	return nil, 0, fmt.Errorf("unsupported schema_version %d", version)
}

// storedForm is what SubmitEvidence persists: the record with the submitting
// identity stamped on it. Version 1 keeps the struct round trip it always had;
// version 2 keeps every submitted member and only sets the on-chain ones.
func storedForm(raw []byte, rec EvidenceRecord, version int, mspID, id string) ([]byte, error) {
	if version == schemaV1 {
		rec.SubmitterMSP = mspID
		rec.SubmitterID = id
		return json.Marshal(rec)
	}
	var members map[string]json.RawMessage
	if err := json.Unmarshal(raw, &members); err != nil {
		return nil, err
	}
	for _, kv := range [][2]string{{"submitter_msp", mspID}, {"submitter_id", id}} {
		delete(members, kv[0])
		if kv[1] == "" {
			continue
		}
		v, err := json.Marshal(kv[1])
		if err != nil {
			return nil, err
		}
		members[kv[0]] = v
	}
	return json.Marshal(members)
}
