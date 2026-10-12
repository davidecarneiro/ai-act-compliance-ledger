# Credit-scoring case (WP4). Protocol: ../../protocols/wp4_credit_case.md
#
#   setup   install the pinned dependencies
#   tests   pytest suite of the case (runs the case once in a temporary folder)
#   run     the case with seed 42 under the committed policy.json
#   pilot   seed 7; refuses to overwrite policy.json (the policy is fixed)
#   stability  seed-stability addendum: partition seeds 0-499 (post hoc, exploratory)
#   answerability  WP5 matrix Q1-Q14 in configurations A, B, C, D (protocols/wp5_answerability.md)
#   tamper  attacks T1-T9 on the case output in configurations A, B0, B, B+ (protocols/tamper_detection.md)

PYTHON ?= python3

.PHONY: setup tests run pilot stability tamper answerability

setup:
	$(PYTHON) -m pip install --break-system-packages -r requirements.txt

tests:
	$(PYTHON) -m pytest tests/ -v

run:
	$(PYTHON) credit_case.py run

pilot:
	$(PYTHON) credit_case.py pilot

stability:
	$(PYTHON) seed_stability.py

tamper:
	$(PYTHON) tamper_experiment.py

answerability:
	$(PYTHON) answerability.py
