#!/bin/sh
set -eu

if [ ! -d node_modules ] || [ -z "$(ls -A node_modules 2>/dev/null || true)" ]; then
  npm install
fi

npm run dev -- --host 0.0.0.0 --port 5173
