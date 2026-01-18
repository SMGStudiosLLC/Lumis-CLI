#!/bin/bash
# Lumis CLI Setup Script
# Run: chmod +x setup.sh && ./setup.sh
#
# WINDOWS USERS:
# This script is for macOS/Linux. For Windows 11:
# 1. Install Python from python.org (check "Add to PATH")
# 2. Open PowerShell and run: pip install requests
# 3. Create folder: mkdir %USERPROFILE%\.lumis
# 4. Run Lumis: python lumis.py
# Or use WSL (Windows Subsystem for Linux) and run this script.

BLUE='\033[38;5;33m'
GREEN='\033[92m'
YELLOW='\033[93m'
WHITE='\033[97m'
GRAY='\033[90m'
RESET='\033[0m'

echo ""
echo -e "${BLUE}╔═══════════════════════════════════════╗${RESET}"
echo -e "${BLUE}║${WHITE}       LUMIS CLI SETUP WIZARD          ${BLUE}║${RESET}"
echo -e "${BLUE}╚═══════════════════════════════════════╝${RESET}"
echo ""

# Check Python
echo -e "${WHITE}[1/4]${GRAY} Checking Python...${RESET}"
if command -v python3 &> /dev/null; then
    PY_VER=$(python3 --version 2>&1 | cut -d' ' -f2)
    echo -e "  ${GREEN}✓${RESET} Python $PY_VER found"
else
    echo -e "  ${YELLOW}✗${RESET} Python 3 not found. Install from python.org"
    exit 1
fi

# Check/install requests
echo -e "${WHITE}[2/4]${GRAY} Checking dependencies...${RESET}"
if python3 -c "import requests" 2>/dev/null; then
    echo -e "  ${GREEN}✓${RESET} requests module installed"
else
    echo -e "  ${YELLOW}→${RESET} Installing requests..."
    pip3 install requests --quiet
    echo -e "  ${GREEN}✓${RESET} requests installed"
fi

# Setup config directory
echo -e "${WHITE}[3/4]${GRAY} Setting up config...${RESET}"
mkdir -p ~/.lumis
if [ ! -f ~/.lumis/api_keys.json ]; then
    echo '{"keys": []}' > ~/.lumis/api_keys.json
    echo -e "  ${GREEN}✓${RESET} Created ~/.lumis/api_keys.json"
else
    echo -e "  ${GREEN}✓${RESET} Config already exists"
fi

# Make executable and create alias
echo -e "${WHITE}[4/4]${GRAY} Setting up command...${RESET}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$SCRIPT_DIR/lumis.py"

# Detect shell
if [ -f ~/.zshrc ]; then
    SHELL_RC=~/.zshrc
elif [ -f ~/.bashrc ]; then
    SHELL_RC=~/.bashrc
else
    SHELL_RC=~/.profile
fi

# Add alias if not present
if ! grep -q "alias lumis=" "$SHELL_RC" 2>/dev/null; then
    echo "" >> "$SHELL_RC"
    echo "# Lumis CLI" >> "$SHELL_RC"
    echo "alias lumis='python3 $SCRIPT_DIR/lumis.py'" >> "$SHELL_RC"
    echo -e "  ${GREEN}✓${RESET} Added 'lumis' alias to $SHELL_RC"
else
    echo -e "  ${GREEN}✓${RESET} Alias already configured"
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════${RESET}"
echo -e "${WHITE}  Setup complete!${RESET}"
echo ""
echo -e "${GRAY}  To start Lumis:${RESET}"
echo -e "    ${WHITE}source $SHELL_RC${RESET}  (or restart terminal)"
echo -e "    ${WHITE}lumis${RESET}"
echo ""
echo -e "${GRAY}  Or run directly:${RESET}"
echo -e "    ${WHITE}python3 $SCRIPT_DIR/lumis.py${RESET}"
echo -e "${GREEN}═══════════════════════════════════════${RESET}"
echo ""
