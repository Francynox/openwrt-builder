FROM ubuntu:26.04

ARG DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN --mount=type=cache,target=/var/cache/apt \
    --mount=type=cache,target=/var/lib/apt \
    apt-get update && apt-get install -y \
    build-essential \
    file \
    libncurses-dev \
    zlib1g-dev \
    gawk \
    git \
    gettext \
    libssl-dev \
    xsltproc \
    rsync \
    wget \
    unzip \
    python3 \
    python3-setuptools \
    locales \
    python3-yaml \
    zstd \
    qemu-utils

RUN locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

# Add /opt to PYTHONPATH so /opt/openwrt_builder is importable as package `openwrt_builder`
ENV PYTHONPATH=/opt

WORKDIR /app

USER ubuntu

CMD ["/bin/bash"]
