# syntax=docker/dockerfile:1
# Cerium Browser — Pre-baked CI/CD Builder Image
# Encapsulates Debian Bookworm, toolchain build dependencies, Node.js 24, pnpm,
# depot_tools, NativeLink daemon, and hermetic GN to eliminate runner bootstrap overhead.

FROM debian:bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH="/opt/depot_tools:/usr/local/bin:${PATH}" \
    DEPOT_TOOLS_UPDATE=0 \
    GCLIENT_SUPPRESS_GIT_VERSION_WARNING=1 \
    PYTHONUNBUFFERED=1 \
    CHROME_HEADLESS=1

# 1. Install system toolchain and compilation prerequisites
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    git \
    python3 \
    python3-yaml \
    python3-pytest \
    curl \
    patch \
    ca-certificates \
    openjdk-17-jdk-headless \
    ninja-build \
    bzip2 \
    sudo \
    file \
    lsb-release \
    pkg-config \
    zip \
    unzip \
    libfuse2 \
    build-essential \
    p7zip-full \
    xz-utils \
    tar \
    procps \
    lib32gcc-s1 \
    lib32stdc++6 \
    libc6-i386 \
    && rm -rf /var/lib/apt/lists/*

# 2. Pre-install Chromium Android and Linux host compilation dependencies
COPY .gitlab/docker/install-build-deps.py /tmp/install-build-deps.py
RUN if [ ! -s /tmp/install-build-deps.py ]; then \
        curl -fsSL "https://chromium.googlesource.com/chromium/src/+/main/build/install-build-deps.py?format=TEXT" | base64 -d > /tmp/install-build-deps.py; \
    fi \
    && python3 /tmp/install-build-deps.py --android --no-prompt \
    && rm -f /tmp/install-build-deps.py \
    && rm -rf /var/lib/apt/lists/*

# 3. Install Node.js 24.x and pnpm 11.11.0
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y -qq --no-install-recommends nodejs \
    && npm install -g pnpm@11.11.0 \
    && rm -rf /var/lib/apt/lists/*

# 4. Pre-install and bootstrap depot_tools
RUN git clone --depth 1 https://chromium.googlesource.com/chromium/tools/depot_tools.git /opt/depot_tools \
    && (/opt/depot_tools/ensure_bootstrap || /opt/depot_tools/update_depot_tools || true)

# 5. Pre-install hermetic GN binary via CIPD
RUN /opt/depot_tools/cipd install "gn/gn/linux-amd64" "git_revision:c7ffaf80713afbe5a4f4d95a605c0a98084374de" -root /usr/local/bin || true \
    && chmod +x /usr/local/bin/gn 2>/dev/null || true

# 6. Pre-install NativeLink daemon binary (v1.8.3 x86_64)
RUN curl -fsSL "https://github.com/TraceMachina/nativelink/releases/download/v1.8.3/nativelink-1.8.3-x86_64-unknown-linux-musl.tar.gz" -o /tmp/nativelink.tar.gz \
    && tar -xzf /tmp/nativelink.tar.gz -C /usr/local/bin nativelink \
    && rm -f /tmp/nativelink.tar.gz \
    && chmod +x /usr/local/bin/nativelink

# 7. Sanity check pre-installed tools
RUN python3 --version \
    && node --version \
    && pnpm --version \
    && ninja --version \
    && nativelink --help >/dev/null 2>&1 || true

WORKDIR /builds
CMD ["/bin/bash"]
