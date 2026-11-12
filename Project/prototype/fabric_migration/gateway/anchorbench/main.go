// anchorbench — WP7 measurement client (protocols/wp7_fabric_anchoring.md).
//
// One persistent Fabric Gateway connection (identity User1@org1), serial
// submission, wall-clock timing of each call. run_wp7.py prepares the inputs,
// calls this client once per step and assembles the results; the client only
// times calls and writes what it observed.
//
//	go run ./anchorbench register   -pubkey pubkey.txt -out out.json
//	go run ./anchorbench submit     -in records.jsonl -out out.json   (SubmitEvidence, N = 1)
//	go run ./anchorbench anchor     -in anchors.jsonl -out out.json   (AnchorBatch)
//	go run ./anchorbench inclusion  -in pairs.jsonl   -out out.json   (VerifyInclusion, evaluate)
//	go run ./anchorbench verifychain -repeat 20       -out out.json   (VerifyChain, evaluate)
//	go run ./anchorbench anchors    -stream NAME      -out out.json   (GetAnchors export)
//	go run ./anchorbench singleorg  -in anchor.json   -out out.json   (endorsed by Org1 only)
//
// The connection settings are those of gateway_measure.go; FABRIC_CRYPTO_PATH
// overrides the location of the test network's Org1 crypto material.
package main

import (
	"bufio"
	"crypto/x509"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
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

var cryptoPath = env("FABRIC_CRYPTO_PATH", filepath.Join(os.Getenv("HOME"),
	"fabric-workspace/fabric-samples/test-network/organizations/peerOrganizations/org1.example.com"))

func env(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}

// call is one timed operation.
type call struct {
	I       int     `json:"i"`
	StartNs int64   `json:"start_unix_ns"`
	EndNs   int64   `json:"end_unix_ns"`
	Ms      float64 `json:"ms"`
	OK      bool    `json:"ok"`
	Error   string  `json:"error,omitempty"`
	Code    string  `json:"code,omitempty"`
	Result  string  `json:"result,omitempty"`
}

type output struct {
	Command  string `json:"command"`
	Input    string `json:"input,omitempty"`
	Started  string `json:"started_at"`
	Finished string `json:"finished_at"`
	Calls    []call `json:"calls"`
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: anchorbench <register|submit|anchor|inclusion|verifychain|anchors|singleorg> [flags]")
		os.Exit(2)
	}
	cmd := os.Args[1]
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	in := fs.String("in", "", "input file (JSON lines, or one JSON object for singleorg)")
	out := fs.String("out", "", "output file (JSON)")
	pubkey := fs.String("pubkey", "", "file holding the issuer's raw Ed25519 public key, 64 hex digits")
	repeat := fs.Int("repeat", 20, "verifychain: number of calls")
	stream := fs.String("stream", "", "anchors: stream to export")
	keepResults := fs.Bool("keep-results", false, "keep every evaluate result, not only the first")
	if err := fs.Parse(os.Args[2:]); err != nil {
		os.Exit(2)
	}
	if *out == "" {
		fail(fmt.Errorf("-out is required"))
	}

	conn := newGrpcConnection()
	defer conn.Close()
	gw, err := client.Connect(newIdentity(), client.WithSign(newSign()),
		client.WithClientConnection(conn),
		client.WithEvaluateTimeout(60*time.Second),
		client.WithEndorseTimeout(60*time.Second),
		client.WithSubmitTimeout(60*time.Second),
		client.WithCommitStatusTimeout(120*time.Second))
	fail(err)
	defer gw.Close()
	contract := gw.GetNetwork(channelName).GetContract(ccName)

	res := output{Command: cmd, Input: *in, Started: time.Now().UTC().Format(time.RFC3339Nano)}
	switch cmd {
	case "register":
		raw, err := os.ReadFile(*pubkey)
		fail(err)
		key := strings.TrimSpace(string(raw))
		res.Calls = append(res.Calls, timed(0, func() (string, error) {
			_, err := contract.SubmitTransaction("RegisterIssuer", key)
			return "", err
		}))
	case "submit", "anchor":
		fn := map[string]string{"submit": "SubmitEvidence", "anchor": "AnchorBatch"}[cmd]
		for i, line := range readLines(*in) {
			res.Calls = append(res.Calls, timed(i, func() (string, error) {
				_, err := contract.SubmitTransaction(fn, line)
				return "", err
			}))
		}
	case "inclusion":
		for i, line := range readLines(*in) {
			var pair struct {
				Record json.RawMessage `json:"record"`
				Proof  json.RawMessage `json:"proof"`
			}
			fail(json.Unmarshal([]byte(line), &pair))
			c := timed(i, func() (string, error) {
				r, err := contract.EvaluateTransaction("VerifyInclusion", string(pair.Record), string(pair.Proof))
				return string(r), err
			})
			res.Calls = append(res.Calls, c)
		}
	case "verifychain":
		for i := 0; i < *repeat; i++ {
			res.Calls = append(res.Calls, timed(i, func() (string, error) {
				r, err := contract.EvaluateTransaction("VerifyChain")
				return string(r), err
			}))
		}
	case "anchors":
		res.Calls = append(res.Calls, timed(0, func() (string, error) {
			r, err := contract.EvaluateTransaction("GetAnchors", *stream)
			return string(r), err
		}))
		*keepResults = true
	case "singleorg":
		raw, err := os.ReadFile(*in)
		fail(err)
		res.Calls = append(res.Calls, timed(0, func() (string, error) {
			_, err := contract.Submit("AnchorBatch",
				client.WithArguments(strings.TrimSpace(string(raw))),
				client.WithEndorsingOrganizations("Org1MSP"))
			return "", err
		}))
	default:
		fail(fmt.Errorf("unknown command %q", cmd))
	}
	if !*keepResults {
		// Evaluate results repeat; keep the first of each kind and the failures.
		seen := map[string]bool{}
		for i := range res.Calls {
			r := res.Calls[i].Result
			if r != "" && seen[r] && res.Calls[i].OK && !strings.Contains(r, `"included":false`) {
				res.Calls[i].Result = ""
			}
			seen[r] = true
		}
	}
	res.Finished = time.Now().UTC().Format(time.RFC3339Nano)
	b, err := json.MarshalIndent(res, "", " ")
	fail(err)
	fail(os.MkdirAll(filepath.Dir(*out), 0o755))
	fail(os.WriteFile(*out, b, 0o644))
	okCount := 0
	for _, c := range res.Calls {
		if c.OK {
			okCount++
		}
	}
	fmt.Printf("%s: %d calls, %d ok -> %s\n", cmd, len(res.Calls), okCount, *out)
}

// timed runs f and records wall-clock start, end and outcome. For a submit,
// f returns after the commit status: endorsement, ordering, validation and
// commit are all inside the interval.
func timed(i int, f func() (string, error)) call {
	start := time.Now()
	result, err := f()
	end := time.Now()
	c := call{I: i, StartNs: start.UnixNano(), EndNs: end.UnixNano(),
		Ms: float64(end.Sub(start).Microseconds()) / 1000.0, OK: err == nil, Result: result}
	if err != nil {
		c.Error = err.Error()
		var commitErr *client.CommitError
		if errors.As(err, &commitErr) {
			c.Code = commitErr.Code.String()
		}
	}
	return c
}

func readLines(path string) []string {
	f, err := os.Open(path)
	fail(err)
	defer f.Close()
	var lines []string
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1024*1024), 64*1024*1024)
	for sc.Scan() {
		if s := strings.TrimSpace(sc.Text()); s != "" {
			lines = append(lines, s)
		}
	}
	fail(sc.Err())
	if len(lines) == 0 {
		fail(fmt.Errorf("%s is empty", path))
	}
	return lines
}

func newGrpcConnection() *grpc.ClientConn {
	pem, err := os.ReadFile(cryptoPath + "/peers/peer0.org1.example.com/tls/ca.crt")
	fail(err)
	pool := x509.NewCertPool()
	pool.AppendCertsFromPEM(pem)
	conn, err := grpc.NewClient(peerEndpoint,
		grpc.WithTransportCredentials(credentials.NewClientTLSFromCert(pool, gatewayPeer)))
	fail(err)
	return conn
}

func newIdentity() *identity.X509Identity {
	pem, err := readFirstFile(cryptoPath + "/users/User1@org1.example.com/msp/signcerts")
	fail(err)
	cert, err := identity.CertificateFromPEM(pem)
	fail(err)
	id, err := identity.NewX509Identity(mspID, cert)
	fail(err)
	return id
}

func newSign() identity.Sign {
	pem, err := readFirstFile(cryptoPath + "/users/User1@org1.example.com/msp/keystore")
	fail(err)
	key, err := identity.PrivateKeyFromPEM(pem)
	fail(err)
	sign, err := identity.NewPrivateKeySign(key)
	fail(err)
	return sign
}

func readFirstFile(dir string) ([]byte, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	if len(entries) == 0 {
		return nil, fmt.Errorf("%s is empty", dir)
	}
	return os.ReadFile(filepath.Join(dir, entries[0].Name()))
}

func fail(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "anchorbench:", err)
		os.Exit(1)
	}
}
