# ---- builder: patch + build wheels for Real-ESRGAN's broken-on-3.14 deps ----
# basicsr/gfpgan/facexlib read their version via exec()+locals()['__version__'],
# which raises KeyError on Python 3.13+ (PEP 667). Build patched wheels here so
# the final image / Cookbook never has to compile the broken sdists. See
# docker/build-realesrgan-wheels.sh for the full rationale.
FROM python:3.14-slim AS realesrgan-wheels
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY docker/build-realesrgan-wheels.sh /usr/local/bin/build-realesrgan-wheels.sh
RUN bash /usr/local/bin/build-realesrgan-wheels.sh /wheels

FROM python:3.14-slim

# System deps. tmux is required by Cookbook for background downloads/serves.
# openssh-client is required for Cookbook remote server tests, setup, probes,
# downloads, and serves from Docker installs.
# git/cmake are required when Cookbook builds llama.cpp on first llama.cpp
# launch inside Docker.
# nodejs/npm provide npx for the built-in Browser MCP server.
# chromium provides the actual browser binary used by that MCP server.
# fontconfig + Noto CJK provide real fallback glyphs for multilingual pages;
# Chromium otherwise renders Chinese/Japanese/Korean labels as empty boxes.
# iproute2/iputils-ping/net-tools/dnsutils/nmap give Docker-hosted agents the
# basic network inspection toolkit expected by local LAN/debugging tasks.
# gosu lets the entrypoint drop privileges cleanly so signals still reach
# uvicorn directly (no extra shell layer like `su`/`sudo` would add).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    curl \
    git \
    nodejs \
    npm \
    chromium \
    fontconfig \
    fonts-noto-cjk \
    tmux \
    openssh-client \
    iproute2 \
    iputils-ping \
    net-tools \
    dnsutils \
    nmap \
    gosu \
    libgl1 \
    libglib2.0-0t64 \
    libxcb1 \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Private browser automation wrapper used by the native `private_browser` tool.
# Chromium is installed above, so agent-browser can drive the existing browser
# binary without paying `npx` startup/install overhead on each tool call.
RUN npm install -g agent-browser@0.35.0 --omit=dev --loglevel=error

# libgl1/libglib2.0-0t64/libxcb1 are the shared libs opencv-python (cv2) loads
# for the Cookbook realesrgan install; the slim base omits them.
# libmagic1 backs python-magic, installed below rather than in requirements.txt
# because its import blocks or raises on hosts without libmagic.

# Docker CLI client only; the daemon stays on the host via the socket mount.
# Debian's docker.io ships no client binary on slim.
ARG DOCKER_CLI_VERSION=29.6.2
RUN ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in \
         amd64) DARCH=x86_64 ;; \
         arm64) DARCH=aarch64 ;; \
         *) echo "unsupported arch $ARCH"; exit 1 ;; \
       esac \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${DARCH}/docker-${DOCKER_CLI_VERSION}.tgz" \
       -o /tmp/docker.tgz \
    && tar -xzf /tmp/docker.tgz -C /tmp \
    && install -m 0755 /tmp/docker/docker /usr/local/bin/docker \
    && rm -rf /tmp/docker /tmp/docker.tgz

WORKDIR /app

# Install Python deps first (layer cache). Optional extras (PyMuPDF AGPL, etc.)
# are opt-in so the default image stays MIT-core; see requirements-optional.txt.
ARG INSTALL_OPTIONAL=false
COPY requirements.txt requirements-optional.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_OPTIONAL" = "true" ]; then pip install --no-cache-dir -r requirements-optional.txt; fi

# Content-based MIME sniffing in src/upload_handler.py; see the libmagic1 note above.
RUN pip install --no-cache-dir python-magic==0.4.27

# Patched basicsr/gfpgan/facexlib wheels, so the Cookbook's `pip install
# realesrgan` skips the sdists that fail on Python 3.14. --no-deps keeps torch out.
COPY --from=realesrgan-wheels /wheels/ /tmp/odysseus-wheels/
RUN pip install --no-cache-dir --no-deps /tmp/odysseus-wheels/*.whl \
    && rm -rf /tmp/odysseus-wheels

COPY . .
# Require the redistribution notices in the image build context.
COPY licenses/ ./licenses/
COPY THIRD_PARTY_PROVENANCE.json ACKNOWLEDGMENTS.md ./

# Create data directory (mount a volume here for persistence)
RUN mkdir -p data logs services/cache/search

# Drops to PUID/PGID (default 1000:1000) and repairs ownership of the
# bind-mounted /app/data and /app/logs so host users can write them.
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Keep APP_PORT equal to the CMD's --port: loopback calls and OAuth callbacks read it.
ENV APP_PORT=7000
EXPOSE 7000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7000"]
