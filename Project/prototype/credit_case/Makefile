# Credit-scoring case (WP4). Protocol: ../../protocols/wp4_credit_case.md
#
#   setup   install the pinned dependencies
#   tests   pytest suite of the case (runs the case once in a temporary folder)
#   run     the case with seed 42 under the committed policy.json
#   pilot   seed 7; refuses to overwrite policy.json (the policy is fixed)

PYTHON ?= python3

.PHONY: setup tests run pilot

setup:
	$(PYTHON) -m pip install --break-system-packages -r requirements.txt

tests:
	$(PYTHON) -m pytest tests/ -v

run:
	$(PYTHON) credit_case.py run

pilot:
	$(PYTHON) credit_case.py pilot
