#!/bin/bash
# Clean up corrupted PI Agent sessions after crash.
# Run when PI Agent doc/chat is stuck (requests hang, health check OK but no response).

set -e

PI_AGENT_DIR="/home/youyeetoo/InNet_box/backend/.pi-agent"

echo "=== Cleaning PI Agent Sessions ==="

clean_sessions() {
    local agent_name="$1"
    local state_dir="$PI_AGENT_DIR/$agent_name/state"
    local sessions_dir="$state_dir/sessions"

    if [ -d "$sessions_dir" ]; then
        local count=$(ls "$sessions_dir"/*.jsonl 2>/dev/null | wc -l)
        if [ "$count" -gt 0 ]; then
            echo "  [$agent_name] Removing $count session files from $sessions_dir"
            rm -f "$sessions_dir"/*.jsonl
        else
            echo "  [$agent_name] No session files to clean"
        fi
    else
        echo "  [$agent_name] No sessions directory at $sessions_dir"
    fi
}

clean_sessions "doc"
clean_sessions "chat"

echo ""
echo "=== Session cleanup complete ==="
echo "Restart affected PI Agent services:"
echo "  systemctl --user restart openclaw-doc"
echo "  systemctl --user restart openclaw-chat"
