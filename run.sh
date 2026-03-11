#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Molty Royale AI Agent Bot — Setup & Run Script (Ubuntu)
# Interactive setup with room type selection and API key config
# ═══════════════════════════════════════════════════════════════

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║          🤖  MOLTY ROYALE AI AGENT BOT  🤖              ║${NC}"
echo -e "${CYAN}${BOLD}║     Continuous Learning • Smart Strategy • Kills Max    ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ─── Step 1: Check Python 3 ──────────────────────────────────
echo -e "${YELLOW}[1/7] Checking Python 3...${NC}"
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 --version 2>&1)
    echo -e "${GREEN}✅ $PY_VERSION found${NC}"
else
    echo -e "${RED}❌ Python 3 not found. Installing...${NC}"
    sudo apt update
    sudo apt install -y python3 python3-pip python3-venv
    echo -e "${GREEN}✅ Python 3 installed${NC}"
fi

# ─── Step 2: Create virtual environment ──────────────────────
echo ""
echo -e "${YELLOW}[2/7] Setting up virtual environment...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}✅ Virtual environment created${NC}"
else
    echo -e "${GREEN}✅ Virtual environment already exists${NC}"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# ─── Step 3: Install dependencies ────────────────────────────
echo ""
echo -e "${YELLOW}[3/7] Installing dependencies...${NC}"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
echo -e "${GREEN}✅ Dependencies installed${NC}"

# ─── Step 4: API Key setup ───────────────────────────────────
echo ""
echo -e "${YELLOW}[4/7] API Key configuration${NC}"
CRED_DIR="$HOME/.molty-royale"
CRED_FILE="$CRED_DIR/credentials.json"

if [ -n "$MR_API_KEY" ]; then
    echo -e "${GREEN}✅ API key found in environment ($MR_API_KEY)${NC}"
    API_KEY="$MR_API_KEY"
elif [ -f "$CRED_FILE" ]; then
    API_KEY=$(python3 -c "import json; print(json.load(open('$CRED_FILE')).get('api_key',''))" 2>/dev/null || echo "")
    if [ -n "$API_KEY" ]; then
        echo -e "${GREEN}✅ API key loaded from $CRED_FILE${NC}"
    fi
fi

if [ -z "$API_KEY" ]; then
    echo -e "${CYAN}Enter your Molty Royale API key (mr_live_...):${NC}"
    read -r API_KEY
    if [ -z "$API_KEY" ]; then
        echo -e "${RED}❌ No API key provided. Cannot continue.${NC}"
        exit 1
    fi
fi

# ─── Step 5: Fetch agent info from API key ───────────────────
echo ""
echo -e "${YELLOW}[5/7] Fetching agent info from API...${NC}"
ACCOUNT_INFO=$(curl -s "https://cdn.moltyroyale.com/api/accounts/me" \
    -H "X-API-Key: $API_KEY" 2>/dev/null || echo "")

if echo "$ACCOUNT_INFO" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('success')" 2>/dev/null; then
    AGENT_NAME=$(echo "$ACCOUNT_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['name'])" 2>/dev/null || echo "MoltyBot")
    BALANCE=$(echo "$ACCOUNT_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['data'].get('balance',0))" 2>/dev/null || echo "0")
    TOTAL_GAMES=$(echo "$ACCOUNT_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['data'].get('totalGames',0))" 2>/dev/null || echo "0")
    TOTAL_WINS=$(echo "$ACCOUNT_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['data'].get('totalWins',0))" 2>/dev/null || echo "0")

    echo -e "${GREEN}✅ Agent: $AGENT_NAME${NC}"
    echo -e "   Balance: $BALANCE \$Moltz"
    echo -e "   Record: ${TOTAL_WINS}W / ${TOTAL_GAMES}G"
else
    echo -e "${RED}⚠️  Could not verify API key. Continuing anyway...${NC}"
    AGENT_NAME="MoltyBot"
fi

# ─── Step 6: Room type selection ─────────────────────────────
echo ""
echo -e "${YELLOW}[6/7] Room type selection${NC}"

# Check for saved preference
SAVED_ROOM_TYPE=""
if [ -f "$CRED_FILE" ]; then
    SAVED_ROOM_TYPE=$(python3 -c "import json; print(json.load(open('$CRED_FILE')).get('room_type',''))" 2>/dev/null || echo "")
fi

if [ -n "$MR_ROOM_TYPE" ]; then
    ROOM_TYPE="$MR_ROOM_TYPE"
    echo -e "${GREEN}✅ Room type from environment: $ROOM_TYPE${NC}"
elif [ -n "$SAVED_ROOM_TYPE" ]; then
    echo -e "   Saved preference: ${BOLD}$SAVED_ROOM_TYPE${NC}"
    echo -e "${CYAN}Use saved preference? (y/n, default: y):${NC}"
    read -r USE_SAVED
    if [ "$USE_SAVED" = "n" ] || [ "$USE_SAVED" = "N" ]; then
        SAVED_ROOM_TYPE=""
    else
        ROOM_TYPE="$SAVED_ROOM_TYPE"
    fi
fi

if [ -z "$ROOM_TYPE" ]; then
    echo -e "   ${BOLD}1)${NC} Free room (no entry fee, 1000 \$Moltz pool)"
    echo -e "   ${BOLD}2)${NC} Paid room (1000 \$Moltz entry, 100K pool)"
    echo -e "${CYAN}Select room type (1/2, default: 1):${NC}"
    read -r ROOM_CHOICE
    case "$ROOM_CHOICE" in
        2) ROOM_TYPE="paid" ;;
        *) ROOM_TYPE="free" ;;
    esac
fi

echo -e "${GREEN}✅ Room type: $ROOM_TYPE${NC}"

# ─── Step 7: Save config & create directories ───────────────
echo ""
echo -e "${YELLOW}[7/7] Saving configuration...${NC}"

mkdir -p "$CRED_DIR"
mkdir -p "$SCRIPT_DIR/data/game_history"
mkdir -p "$SCRIPT_DIR/data/models"

cat > "$CRED_FILE" << EOF
{
    "api_key": "$API_KEY",
    "agent_name": "$AGENT_NAME",
    "room_type": "$ROOM_TYPE"
}
EOF

echo -e "${GREEN}✅ Config saved to $CRED_FILE${NC}"
echo -e "${GREEN}✅ Data directories created${NC}"

# ─── Launch ──────────────────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}${BOLD}  🚀  Launching Molty Royale AI Bot...${NC}"
echo -e "${CYAN}${BOLD}  Agent: $AGENT_NAME | Room: $ROOM_TYPE${NC}"
echo -e "${CYAN}${BOLD}  Press Ctrl+C to stop gracefully${NC}"
echo -e "${CYAN}${BOLD}════════════════════════════════════════════════════════════${NC}"
echo ""

# Export env vars for the Python process
export MR_API_KEY="$API_KEY"
export MR_ROOM_TYPE="$ROOM_TYPE"

# Run the bot
cd "$SCRIPT_DIR"
python3 -m src.multi_runner
