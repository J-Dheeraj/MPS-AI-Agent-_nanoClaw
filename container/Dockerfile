FROM node:20-bookworm

WORKDIR /app

# Install build tools needed for better-sqlite3
RUN apt-get update && apt-get install -y \
    python3 \
    make \
    g++ \
    sqlite3 \
    libsqlite3-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy agent package files
COPY container/agent/package.json ./

# Install dependencies using npm, not Bun
RUN npm install

# Install TypeScript runner for .ts entrypoint
RUN npm install tsx

# Rebuild better-sqlite3 inside Node 20 container
RUN npm rebuild better-sqlite3 --build-from-source

# Copy the agent source
COPY container/agent/ ./

# Create workspace mount point
RUN mkdir -p /workspace/group

CMD ["npx", "tsx", "index.ts"]
