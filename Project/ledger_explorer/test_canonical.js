// Checks the Explorer's canonical forms against the issuer's (no browser needed).
//
//   node test_canonical.js
//
// The functions are taken from LEDGER_EXPLORER.html itself, so the test runs
// the code the page runs: the version 1 form (canonicalJSON) on the
// dissertation's ledgers, and RFC 8785 (jcs) on the RFC 8785 vectors that
// Python produced for Go and on version 2 ledgers. Every record must
// recompute to its record_hash.
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');

const ROOT = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(__dirname, 'LEDGER_EXPLORER.html'), 'utf8');

// The source of a top-level declaration: from `function name(` or
// `const name =` at the start of a line to the next top-level line (the page
// declares its functions at column 0).
function extract(name) {
  const m = new RegExp(`\\n(?:async )?function ${name}\\(|\\nconst ${name} =`).exec(html);
  if (!m) throw new Error(`${name} not found in the page`);
  const rest = html.slice(m.index + 1);
  const next = /\n(?:async function |function |const |let |var |class |\/\*|\/\/|<\/script>)/.exec(rest.slice(1));
  return rest.slice(0, next ? next.index + 1 : rest.length) + '\n';
}

const names = ['FLOAT_TAG', 'isTaggedFloat', 'pyFloatRepr', 'encStr', 'canonicalJSON', 'jcs',
  'schemaVersionOf', 'canonicalBody', 'reqsOf', 'DERIVED', 'recordBody',
  'parseJSONPreservingFloats'];
const ctx = { L: (en) => en };
vm.createContext(ctx);
vm.runInContext(names.map(extract).join('\n') +
  '\nthis.api = {canonicalBody, jcs, reqsOf, recordBody, parseJSONPreservingFloats};', ctx);
const { canonicalBody, jcs, reqsOf, recordBody, parseJSONPreservingFloats } = ctx.api;

const sha = (s) => crypto.createHash('sha256').update(Buffer.from(s, 'utf8')).digest('hex');
let failures = 0;
function check(label, ok) { if (!ok) { failures++; console.log('FAIL', label); } }

// 1. RFC 8785 vectors written by Python's rfc8785 for the Go tests.
const vectors = JSON.parse(fs.readFileSync(path.join(ROOT,
  'prototype/fabric_migration/chaincode/testdata_jcs_vectors.json'), 'utf8'));
for (const v of vectors) {
  const got = Buffer.from(jcs(parseJSONPreservingFloats(v.input)), 'utf8').toString('base64');
  check(`JCS vector ${v.label}`, got === v.expected_b64);
}

// 2. Ledgers: every record recomputes to its record_hash.
function records(file) {
  const text = fs.readFileSync(path.join(ROOT, file), 'utf8');
  if (file.endsWith('.jsonl')) return text.split('\n').filter((l) => l.trim()).map(parseJSONPreservingFloats);
  return parseJSONPreservingFloats(text);
}
function newest(dir, prefix) {
  const full = path.join(ROOT, dir);
  const hits = fs.readdirSync(full).filter((n) => n.startsWith(prefix)).sort();
  return hits.length ? path.join(dir, hits[hits.length - 1]) : null;
}
const ledgers = [
  ['prototype/compliance_ledger_sim/ledger.json', 1],
  ['experiments/runs/incident_run/ledger.json', 1],
  ['prototype/fabric_migration/chaincode/testdata_ledger_v2.json', 2],
  ['prototype/fabric_migration/chaincode/testdata_v2_extra_fields.json', 2],
];
const wp9 = newest('experiments/article/wp9', 'run_');
if (wp9) for (const r of ['scenarios', 'incident', 'multiflow_muvu']) ledgers.push([`${wp9}/${r}/ledger.jsonl`, 2]);
const wp4 = newest('experiments/article/wp4', 'run_');
if (wp4) ledgers.push([`${wp4}/ledger.jsonl`, 2]);

for (const [file, version] of ledgers) {
  const recs = records(file);
  let ok = 0;
  for (const r of recs) {
    if (sha(canonicalBody(recordBody(r))) === r.record_hash) ok++;
  }
  check(`${file}: ${ok}/${recs.length} records recompute`, ok === recs.length);
  check(`${file}: version ${version}`, recs.every((r) => (r.schema_version === 2 ? 2 : 1) === version));
  check(`${file}: provisions read`, recs.every((r) => reqsOf(r).length > 0));
  console.log(`${file}: ${ok}/${recs.length} records recompute (version ${version})`);
}
console.log(`${vectors.length} RFC 8785 vectors checked`);
if (failures) { console.log(`${failures} failure(s)`); process.exit(1); }
console.log('all checks passed');
