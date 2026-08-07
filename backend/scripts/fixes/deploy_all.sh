#!/bin/bash
# Master deploy script for all P0 fixes.
# Transfer this entire 'fixes/' directory to the remote server and run this script.
#
# Usage on remote server:
#   cd /home/youyeetoo/backend
#   bash fixes/deploy_all.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="/home/youyeetoo/backend"

echo "=========================================="
echo "PI Agent P0 Fixes — Full Deploy"
echo "Date: 2026-07-14"
echo "=========================================="

# Step 1: Install systemd unit files
echo ""
echo "--- Step 1: Systemd Unit Files ---"
mkdir -p ~/.config/systemd/user/

if [ -f "$SCRIPT_DIR/../systemd/openclaw-chat.service" ]; then
    cp "$SCRIPT_DIR/../systemd/openclaw-chat.service" ~/.config/systemd/user/
    echo "  openclaw-chat.service installed"
else
    echo "  openclaw-chat.service NOT FOUND — skipping"
fi

if [ -f "$SCRIPT_DIR/../systemd/openclaw-doc.service" ]; then
    cp "$SCRIPT_DIR/../systemd/openclaw-doc.service" ~/.config/systemd/user/
    echo "  openclaw-doc.service installed"
else
    echo "  openclaw-doc.service NOT FOUND — skipping"
fi

systemctl --user daemon-reload
echo "  systemd daemon reloaded"

# Step 2: Apply code fixes
echo ""
echo "--- Step 2: Apply Code Fixes ---"
cd "$BACKEND_DIR"
python3 "$SCRIPT_DIR/apply_p0_fixes.py"

# Step 3: Install cleanup script
echo ""
echo "--- Step 3: Install Session Cleanup Script ---"
mkdir -p "$BACKEND_DIR/scripts"
cp "$SCRIPT_DIR/cleanup_pi_sessions.sh" "$BACKEND_DIR/scripts/"
chmod +x "$BACKEND_DIR/scripts/cleanup_pi_sessions.sh"
echo "  cleanup_pi_sessions.sh installed to scripts/"

# Step 4: Verify
echo ""
echo "--- Step 4: Verify ---"
echo "Checking systemd units..."
if [ -f ~/.config/systemd/user/openclaw-chat.service ]; then
    echo "  [OK] openclaw-chat.service"
else
    echo "  [MISSING] openclaw-chat.service"
fi
if [ -f ~/.config/systemd/user/openclaw-doc.service ]; then
    echo "  [OK] openclaw-doc.service"
else
    echo "  [MISSING] openclaw-doc.service"
fi

echo "Checking backups..."
for f in \
    app/routers/conversations.py \
    app/services/pi_agent_client/degradation.py \
    app/services/llm_client.py
do
    if [ -f "$BACKEND_DIR/$f.bak-20260714" ]; then
        echo "  [OK] $f.bak-20260714"
    else
        echo "  [MISSING] $f.bak-20260714"
    fi
done

echo ""
echo "=========================================="
echo "Deploy complete!"
echo ""
echo "Next steps:"
echo "  1. Stop existing nohup openclaw processes:"
echo "     fuser -k 18790/tcp; fuser -k 18791/tcp"
echo ""
echo "  2. Start systemd-managed services:"
echo "     systemctl --user start openclaw-chat openclaw-doc"
echo ""
echo "  3. Enable auto-start on boot:"
echo "     systemctl --user enable openclaw-chat openclaw-doc"
echo ""
echo "  4. Restart backend to pick up code changes:"
echo "     sudo systemctl restart backend  (or fuser -k 8000/tcp && python run.py)"
echo ""
echo "  5. Test document generation from frontend"
echo ""
echo "  Rollback: cp *.bak-20260714 to original filenames"
echo "=========================================="
