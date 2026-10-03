# MultiFlow observer and the shared compliance simulator.
FROM python:3.11-slim-bookworm
RUN pip install --no-cache-dir kafka-python==2.0.2 cryptography==42.0.5
# The simulator comes from the build context (see INTEGRATION_README.md). It is
# copied at the same folder depth as in the author's repository, so that the
# relative path simulator.py uses to find its experiments folder still resolves.
COPY compliance_ledger_sim /thesis/prototype/compliance_ledger_sim
COPY multiflow_bridge/bridge.py multiflow_bridge/verify_output.py /bridge/
WORKDIR /bridge
ENV ORACLE_PATH=/thesis/prototype/compliance_ledger_sim OUT_DIR=/out
CMD ["python3", "-u", "bridge.py"]
