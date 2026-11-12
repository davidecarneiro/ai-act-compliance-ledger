# WP9: one command that checks everything and regenerates the article's results
# and figures from scratch. The measurements of WP3 and WP7 are made on the
# measurement machine (protocols/RUNNING_MEASUREMENTS.md); the figures read the
# JSON they wrote.
#
#   make article      tests, then regenerate, then figures
#   make tests        every suite (Python under both schema versions, Go, Node)
#   make regenerate   v2 runs (WP9) and the credit-case experiments (WP4, WP5, tampering)
#   make figures      F4, F5 and F6 from the results JSON

PYTHON ?= python3

.PHONY: article tests regenerate figures

article: tests regenerate figures

tests:
	cd ../compliance_ledger_sim && $(PYTHON) -m pytest -q && EVIDENCE_SCHEMA_VERSION=1 $(PYTHON) -m pytest -q
	cd ../credit_case && $(PYTHON) -m pytest -q tests
	cd ../multiflow_bridge && $(PYTHON) -m pytest -q test_bridge.py && EVIDENCE_SCHEMA_VERSION=1 $(PYTHON) -m pytest -q test_bridge.py
	cd ../fabric_migration/wp7 && $(PYTHON) -m pytest -q
	cd ../fabric_migration/chaincode && go test -mod=vendor ./...
	cd ../fabric_migration/interop && $(PYTHON) test_interop.py
	cd ../../ledger_explorer && node test_canonical.js
	cd ../compliance_ledger_sim && $(PYTHON) verify_delivery.py && $(PYTHON) validate_oscal_schema.py --published --expect 18

regenerate:
	$(PYTHON) regenerate.py
	cd ../credit_case && $(PYTHON) credit_case.py run && $(PYTHON) seed_stability.py && $(PYTHON) tamper_experiment.py && $(PYTHON) answerability.py

figures:
	$(PYTHON) figures.py
