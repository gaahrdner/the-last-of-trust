FROM ubuntu:22.04

# Install dependencies for OpenBMC qemu
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    qemu-system-x86 \
    qemu-utils \
    python3 \
    python3-pip \
    wget \
    curl \
    sudo \
    cpio \
    libssl-dev \
    libffi-dev \
    locales \
    python3-dev \
    iputils-ping \
    net-tools \
    iproute2 \
    socat \
    lksctp-tools \
    ipmitool \
    && rm -rf /var/lib/apt/lists/*

# Set up locale
RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8

# Create directory for OpenBMC
RUN mkdir -p /var/lib/openbmc /build /logs /firmware

# Create non-root user for building OpenBMC (optional)
RUN useradd -m -s /bin/bash openbmc && \
    echo "openbmc ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/openbmc

# Add helper scripts
COPY scripts/start_openbmc.sh /build/
COPY scripts/start_redfish.sh /build/
RUN chmod +x /build/start_openbmc.sh /build/start_redfish.sh

# Set working directory
WORKDIR /build

# Default command
ENTRYPOINT ["/build/start_openbmc.sh"]