FROM oven/bun:1.1-alpine

WORKDIR /app

# Install system dependencies
RUN apk add --no-cache \
    curl \
    sqlite \
    build-base \
    git

# Copy and install container agent dependencies
COPY container/agent/package.json container/agent/bun.lock* ./
RUN bun install --frozen-lockfile 2>/dev/null || bun install

# Copy container agent source
COPY container/agent/ ./

# Create workspace mount point
RUN mkdir -p /workspace/group

# whisper.cpp binary (optional, on-device voice transcription).
# The binary is NOT vendored in the repo. build.sh fetches it into
# container/bin/ before `docker build`. We copy the whole directory so the
# image builds whether or not the binary is present; if it is absent, voice
# transcription is simply unavailable (text drafting is unaffected).
COPY container/bin/ /usr/local/bin/
RUN if [ -f /usr/local/bin/whisper-cpp ]; then chmod +x /usr/local/bin/whisper-cpp; fi

CMD ["bun", "run", "index.ts"]
