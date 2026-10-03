# Simulator entry points. Dependencies specify minimum versions.
#
#   setup        pip install -r requirements.txt (--break-system-packages on
#                Debian hosts; elsewhere prefer: python3 -m venv .venv &&
#                .venv/bin/pip install -r requirements.txt)
#   tests        the pytest suite (98 tests)
#   verify       re-verify the published evidence in experiments/, writing nothing
#   baseline     run the Compliance Oracle once (regenerates ledger.json)
#   compare      Oracle and SQLite baseline side by side
#   sensitivity  45 policy-threshold combinations
#   oscal        OSCAL Assessment Results from the ledger
#   demo         tests + baseline + compare + sensitivity + oscal
#   docker-build / docker-run   the same demonstration in a container
#   clean        caches only; preserves the demonstration key and ledger.json
#   clean-state  also discards them (asks for confirmation)

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

.PHONY: setup tests verify baseline compare sensitivity oscal demo docker-build docker-run clean clean-state

setup:
	$(PIP) install --break-system-packages -r requirements.txt

tests:
	$(PYTHON) -m pytest tests/ -v

verify:
	$(PYTHON) verify_delivery.py

baseline:
	$(PYTHON) simulator.py

compare:
	$(PYTHON) compare_oracle_vs_baseline.py

sensitivity:
	$(PYTHON) sensitivity.py

oscal:
	$(PYTHON) -m oscal_exporter
	@echo "Both full and redacted (Art. 78) OSCAL documents written to ../../experiments/"

demo: tests baseline compare sensitivity oscal
	@echo ""
	@echo "Demo complete. Outputs are in ../../experiments/"

docker-build:
	docker build -t compliance-ledger-sim:latest .

docker-run:
	docker run --rm compliance-ledger-sim:latest

clean:
	rm -rf __pycache__ .pytest_cache tests/__pycache__
	rm -f baseline_log.sqlite baseline_log.sqlite-journal
	@echo "Caches removed. keys/ and ledger.json were kept: see clean-state."

clean-state: clean
	@echo "This discards the demonstration key and the canonical ledger."
	@echo "Every signature in experiments/ was made with that key, and a new one"
	@echo "has another fingerprint: the shipped evidence stops verifying."
	@printf "Type 'yes' to continue: " && read r && [ "$$r" = yes ]
	rm -f ledger.json
	rm -rf keys/
	@echo "State discarded. Re-run make baseline to regenerate from scratch."
