// canonical_interop.go — standalone proof that Go can replicate simulator
// canonical_json BYTE FOR BYTE, the condition for record_hash and chain_hash to
// be interoperable between the chaincode and the Oracle.
//
// Runs without a Fabric network and without external dependencies:
//
//   go run canonical_interop.go <file-with-the-python-bytes>
//
// The file holds the output of simulator.canonical_json(payload) (UTF-8 bytes,
// already ASCII because of ensure_ascii). The program reparses that payload,
// recomputes the canonical form in Go and prints whether it is identical, plus
// the SHA-256. It reads from a file, not from argv, so the shell cannot mangle
// backslashes.
//
// Finding documented in MIGRATION_LOG.md: Python uses
// json.dumps(sort_keys=True, separators=(",",":")) with ensure_ascii=True, so
//   * HTML characters (< > &) stay LITERAL
//   * non-ASCII characters are escaped to \uXXXX (lower case)
// Go's json.Marshal does the OPPOSITE on both axes. This file corrects both.
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
)

// canonicalJSON replicates simulator.canonical_json: sorted keys, compact
// separators, literal HTML, non-ASCII escaped to \uXXXX (ensure_ascii).
func canonicalJSON(v interface{}) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false) // axis 1: do NOT escape < > & (as Python does)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	compact := bytes.TrimRight(buf.Bytes(), "\n")
	return asciiEscape(compact), nil // axis 2: escape non-ASCII (as Python does)
}

// asciiEscape converts every non-ASCII rune to \uXXXX (with surrogate pairs for
// the astral plane), mirroring ensure_ascii=True in Python's json.dumps.
// It is byte-safe because, in JSON, non-ASCII characters occur only inside string
// literals; the whole structure is ASCII.
func asciiEscape(b []byte) []byte {
	var out bytes.Buffer
	for _, r := range string(b) {
		switch {
		case r < 0x7f: // 0x7F (DEL) is ASCII but Python ensure_ascii escapes it too
			out.WriteRune(r)
		case r <= 0xFFFF:
			fmt.Fprintf(&out, "\\u%04x", r)
		default:
			r -= 0x10000
			hi := 0xD800 + (r >> 10)
			lo := 0xDC00 + (r & 0x3FF)
			fmt.Fprintf(&out, "\\u%04x\\u%04x", hi, lo)
		}
	}
	return out.Bytes()
}

func sha256Hex(b []byte) string {
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}

func main() {
	if len(os.Args) < 2 {
		fmt.Println("usage: go run canonical_interop.go <file-with-the-python-bytes>")
		os.Exit(2)
	}
	pyBytes, err0 := os.ReadFile(os.Args[1])
	if err0 != nil {
		fmt.Printf("error reading file: %v\n", err0)
		os.Exit(1)
	}

	// Reparse Python's payload into a map and re-serialise it in Go.
	var payload map[string]interface{}
	if err := json.Unmarshal(pyBytes, &payload); err != nil {
		fmt.Printf("error parsing the Python JSON: %v\n", err)
		os.Exit(1)
	}
	goBytes, err := canonicalJSON(payload)
	if err != nil {
		fmt.Printf("error serialising in Go: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("python : %s\n", pyBytes)
	fmt.Printf("go     : %s\n", goBytes)
	identico := bytes.Equal(pyBytes, goBytes)
	fmt.Printf("identical bytes : %v\n", identico)
	fmt.Printf("sha256 python  : %s\n", sha256Hex(pyBytes))
	fmt.Printf("sha256 go      : %s\n", sha256Hex(goBytes))
	fmt.Printf("hash coincide  : %v\n", sha256Hex(pyBytes) == sha256Hex(goBytes))
	if !identico {
		os.Exit(1)
	}
}
