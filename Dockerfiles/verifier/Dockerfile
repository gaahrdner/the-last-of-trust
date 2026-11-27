FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    tpm2-tools \
    python3 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/verifier /var/lib/verifier /logs

COPY verifier_server.py /opt/verifier/verifier_server.py
RUN chmod +x /opt/verifier/verifier_server.py

WORKDIR /opt/verifier

EXPOSE 8888

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=5 \
    CMD curl -sf http://127.0.0.1:8888/health || exit 1

ENTRYPOINT ["python3", "/opt/verifier/verifier_server.py"]
