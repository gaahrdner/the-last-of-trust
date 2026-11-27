FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    qemu-system-x86 \
    qemu-system-arm \
    qemu-utils \
    ovmf \
    qemu-efi-aarch64 \
    swtpm \
    swtpm-tools \
    libtpms0 \
    cloud-image-utils \
    openssh-client \
    curl \
    wget \
    ca-certificates \
    python3 \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/lib/host /firmware /opt/tlot /logs

COPY scripts/setup_tpm.sh /opt/tlot/setup_tpm.sh
COPY scripts/start_host.sh /opt/tlot/start_host.sh
COPY scripts/tlot_agent.py /opt/tlot/tlot_agent.py
RUN chmod +x /opt/tlot/setup_tpm.sh /opt/tlot/start_host.sh /opt/tlot/tlot_agent.py

WORKDIR /opt/tlot

EXPOSE 22 8080 4444

HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=10 \
    CMD curl -sf http://127.0.0.1:8080/health || exit 1

ENTRYPOINT ["/opt/tlot/start_host.sh"]
