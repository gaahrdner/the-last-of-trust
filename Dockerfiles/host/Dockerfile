FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    qemu-system-x86 \
    qemu-utils \
    curl \
    wget \
    git \
    build-essential \
    python3 \
    python3-pip \
    iasl \
    m4 \
    bison \
    flex \
    uuid-dev \
    libncurses-dev \
    libssl-dev \
    libelf-dev \
    net-tools \
    iputils-ping \
    swtpm \
    libtpms0 \
    tpm-tools \
    && rm -rf /var/lib/apt/lists/*

# Install security tools via pip (chipsec, etc can be added later)
RUN pip3 install --no-cache-dir chipsec || true

# Note: osquery and Falco require special repos and can be added post-deployment if needed

# Create directory structure
RUN mkdir -p /var/lib/host /firmware /build /logs

# Create a Debian disk image if it doesn't exist
COPY scripts/create_debian_image.sh /build/
COPY scripts/start_host.sh /build/
COPY scripts/setup_tpm.sh /build/
RUN chmod +x /build/create_debian_image.sh /build/start_host.sh /build/setup_tpm.sh

# Set working directory
WORKDIR /build

# Default start command
ENTRYPOINT ["/build/start_host.sh"]