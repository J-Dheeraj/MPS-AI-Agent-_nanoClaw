#!/bin/bash
source ~/.nvm/nvm.sh 2>/dev/null
export PATH="$HOME/.local/bin:$PATH"
export NODE_ENV=development
export ONECLI_HOST=127.0.0.1
export ONECLI_PORT=4891
export WEB_HOST=127.0.0.1
export WEB_PORT=3080
export OLLAMA_URL=http://127.0.0.1:11434

cd /home/dheer/nanoclaw
exec /home/dheer/.nvm/versions/node/v22.22.3/bin/node dist/index.js
