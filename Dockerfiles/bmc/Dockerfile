FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssl \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/bmc /var/lib/bmc /firmware /logs

COPY scripts/bmc_server.py /opt/bmc/bmc_server.py
RUN chmod +x /opt/bmc/bmc_server.py

WORKDIR /opt/bmc

EXPOSE 443

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=5 \
    CMD curl -skf https://127.0.0.1:443/redfish/v1 || exit 1

ENTRYPOINT ["python3", "/opt/bmc/bmc_server.py"]
