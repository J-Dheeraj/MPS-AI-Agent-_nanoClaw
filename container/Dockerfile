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

# whisper.cpp binary — pulled separately by build.sh
COPY container/bin/whisper-cpp /usr/local/bin/whisper-cpp
RUN chmod +x /usr/local/bin/whisper-cpp

CMD ["bun", "run", "index.ts"]
