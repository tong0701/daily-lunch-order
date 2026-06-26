#!/usr/bin/env bash
# Bootstrap lunch agent on an Inference Ghost VM (or any Linux host).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 -m pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit tokens before starting."
fi

echo ""
echo "Next steps on Ghost:"
echo "  1. Connect Discord in the Ghost dashboard (or set DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID)"
echo "  2. python src/agent.py --onboard"
echo "  3. source .env && python src/ghost_runner.py"
echo ""
