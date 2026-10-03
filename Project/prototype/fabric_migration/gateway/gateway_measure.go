// gateway_measure.go — latency measurement through the Fabric Gateway SDK.
//
// Unlike 02_submit_and_measure.py (which forks the 'peer' CLI on every call and
// includes about 74 ms of start-up plus TLS/gRPC), this client keeps one
// persistent gRPC connection, so the CLI start-up is not in the timings. They
// still include the client, the transport, the Gateway and the peer.
//
// Submit   -> endorsement (2 orgs, via gateway and discovery), ordering, commit.
// Evaluate -> a read-only VerifyChain call executed on one peer through the
// Gateway. No ordering and no commit; it is not the endorsement of a write.
//
//	go run gateway_measure.go records.json pubkey.txt
package main

import (
	"crypto/x509"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/hyperledger/fabric-gateway/pkg/client"
	"github.com/hyperledger/fabric-gateway/pkg/identity"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
)

const (
	mspID        = "Org1MSP"
	peerEndpoint = "dns:///localhost:7051"
	gatewayPeer  = "peer0.org1.example.com"
	channelName  = "compliancechannel"
	ccName       = "compliance"
)

// FABRIC_CRYPTO_PATH points to the test network's Org1 crypto material when
// fabric-samples is not under ~/fabric-workspace.
var (
	cryptoPath = env("FABRIC_CRYPTO_PATH", filepath.Join(os.Getenv("HOME"),
		"fabric-workspace/fabric-samples/test-network/organizations/peerOrganizations/org1.example.com"))
	certPath    = cryptoPath + "/users/User1@org1.example.com/msp/signcerts"
	keyPath     = cryptoPath + "/users/User1@org1.example.com/msp/keystore"
	tlsCertPath = cryptoPath + "/peers/peer0.org1.example.com/tls/ca.crt"
)

func env(nome, omissao string) string {
	if v := os.Getenv(nome); v != "" {
		return v
	}
	return omissao
}

// The output goes next to the records file that was read. EXPERIMENTS_DIR
// overrides it, the same variable the Python side honours; inside it the run
// lives at fabric_run/ in the author's vault and at runs/fabric_run/ in the
// delivered Project/ folder, and whichever exists is used.
func outputPath(recordsFile string) string {
	if d := os.Getenv("EXPERIMENTS_DIR"); d != "" {
		for _, sub := range []string{"runs/fabric_run", "fabric_run"} {
			if st, err := os.Stat(filepath.Join(d, sub)); err == nil && st.IsDir() {
				return filepath.Join(d, sub, "fabric_latency_gateway.json")
			}
		}
		return filepath.Join(d, "fabric_run", "fabric_latency_gateway.json")
	}
	return filepath.Join(filepath.Dir(recordsFile), "fabric_latency_gateway.json")
}

// identityProvider records how the MSP identities were issued, read from the
// network that was actually used rather than written as a constant: the test
// network keeps organizations/fabric-ca/ only when it was brought up with -ca.
// FABRIC_IDENTITY_PROVIDER overrides the detection.
func identityProvider() string {
	if v := os.Getenv("FABRIC_IDENTITY_PROVIDER"); v != "" {
		return v
	}
	if _, err := os.Stat(filepath.Join(cryptoPath, "..", "..", "fabric-ca")); err == nil {
		return "Fabric CA (-ca)"
	}
	return "cryptogen (network brought up without -ca)"
}

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "usage: go run gateway_measure.go records.json pubkey.txt")
		os.Exit(2)
	}
	recordsPath := os.Args[1]
	pubkeyBytes, err := os.ReadFile(os.Args[2])
	panicErr(err)
	pubkey := strings.TrimSpace(string(pubkeyBytes))
	if len(pubkey) != 64 {
		panicErr(fmt.Errorf("%s must hold the raw Ed25519 public key as 64 hex characters", os.Args[2]))
	}

	var records []json.RawMessage
	data, err := os.ReadFile(recordsPath)
	panicErr(err)
	panicErr(json.Unmarshal(data, &records))
	if len(records) < 2 {
		panicErr(fmt.Errorf("%s has %d records; the first is a discarded warm-up, so at least 2 are needed",
			recordsPath, len(records)))
	}

	clientConn := newGrpcConnection()
	defer clientConn.Close()
	gw, err := client.Connect(newIdentity(), client.WithSign(newSign()),
		client.WithClientConnection(clientConn),
		client.WithEvaluateTimeout(30*time.Second),
		client.WithSubmitTimeout(30*time.Second),
		client.WithCommitStatusTimeout(60*time.Second))
	panicErr(err)
	defer gw.Close()

	contract := gw.GetNetwork(channelName).GetContract(ccName)

	// Governance: register the issuer key in the on-chain registry. Only the
	// authority organisation (Org1MSP, this client's User1@org1 identity) may do so.
	if _, err := contract.SubmitTransaction("RegisterIssuer", pubkey); err != nil {
		fmt.Printf("[warning] RegisterIssuer: %v (it may already be registered)\n", err)
	}

	// Submit, timed: endorsement by both orgs, ordering and commit. The first call is a warm-up.
	var submit []float64
	for i, rec := range records {
		t0 := time.Now()
		_, err := contract.SubmitTransaction("SubmitEvidence", string(rec))
		dt := float64(time.Since(t0).Microseconds()) / 1000.0
		panicErr(err)
		if i == 0 {
			fmt.Printf("[warm-up] submit #0 = %.1f ms (excluded)\n", dt)
			continue
		}
		submit = append(submit, dt)
	}

	// Evaluate VerifyChain, timed: read-only execution on the peer, no ordering.
	var eval []float64
	for i := 0; i < 20; i++ {
		t0 := time.Now()
		_, err := contract.EvaluateTransaction("VerifyChain")
		dt := float64(time.Since(t0).Microseconds()) / 1000.0
		panicErr(err)
		eval = append(eval, dt)
	}
	res, _ := contract.EvaluateTransaction("VerifyChain")

	out := map[string]any{
		"method":                     "Fabric Gateway SDK (Go, persistent gRPC connection), NO CLI overhead",
		"fabric_version":             "2.5.10",
		"endorsement_policy":         "AND('Org1MSP.peer','Org2MSP.peer')",
		"identity_provider":          identityProvider(),
		"orderer_batch_timeout_s":    2,
		"verify_chain":               string(res),
		"submit_commit_n":            len(submit),
		"submit_commit_ms_mean":      round(mean(submit)),
		"submit_commit_ms_median":    round(percentile(submit, 50)),
		"submit_commit_ms_p95":       round(percentile(submit, 95)),
		"submit_commit_ms_min":       round(minf(submit)),
		"evaluate_endorse_n":         len(eval),
		"evaluate_endorse_ms_mean":   round(mean(eval)),
		"evaluate_endorse_ms_median": round(percentile(eval, 50)),
		"evaluate_endorse_ms_p95":    round(percentile(eval, 95)),
		"evaluate_endorse_ms_min":    round(minf(eval)),
		"note": "Without the ~74 ms of CLI start-up: submit_commit still includes the orderer's " +
			"BatchTimeout=2s (time to durable evidence); evaluate_endorse is a read-only " +
			"VerifyChain call through the Gateway (client, transport and peer execution), without ordering. Do NOT compare against the " +
			"simulator's 3.79 ms: that April run was declared exploratory on 2026-09-14. The " +
			"citable local figure is the paired protocol (QI4).",
	}
	j, err := json.MarshalIndent(out, "", "  ")
	panicErr(err)
	fmt.Println(string(j))
	// A result that was measured but not written must not be reported as saved.
	outPath := outputPath(os.Args[1])
	panicErr(os.MkdirAll(filepath.Dir(outPath), 0o755))
	panicErr(os.WriteFile(outPath, j, 0o644))
	fmt.Printf("\nsaved to %s\n", outPath)
}

func newGrpcConnection() *grpc.ClientConn {
	pem, err := os.ReadFile(tlsCertPath)
	panicErr(err)
	pool := x509.NewCertPool()
	pool.AppendCertsFromPEM(pem)
	tc := credentials.NewClientTLSFromCert(pool, gatewayPeer)
	conn, err := grpc.NewClient(peerEndpoint, grpc.WithTransportCredentials(tc))
	panicErr(err)
	return conn
}

func newIdentity() *identity.X509Identity {
	pem, err := readFirstFile(certPath)
	panicErr(err)
	cert, err := identity.CertificateFromPEM(pem)
	panicErr(err)
	id, err := identity.NewX509Identity(mspID, cert)
	panicErr(err)
	return id
}

func newSign() identity.Sign {
	pem, err := readFirstFile(keyPath)
	panicErr(err)
	key, err := identity.PrivateKeyFromPEM(pem)
	panicErr(err)
	sign, err := identity.NewPrivateKeySign(key)
	panicErr(err)
	return sign
}

func readFirstFile(dir string) ([]byte, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	return os.ReadFile(filepath.Join(dir, entries[0].Name()))
}

func panicErr(err error) {
	if err != nil {
		panic(err)
	}
}

func mean(xs []float64) float64 {
	s := 0.0
	for _, x := range xs {
		s += x
	}
	return s / float64(len(xs))
}
func minf(xs []float64) float64 {
	m := xs[0]
	for _, x := range xs {
		if x < m {
			m = x
		}
	}
	return m
}
func percentile(xs []float64, p float64) float64 {
	s := append([]float64(nil), xs...)
	sort.Float64s(s)
	k := int(p / 100 * float64(len(s)-1))
	return s[k]
}
func round(x float64) float64 { return float64(int(x*100+0.5)) / 100 }
