#!/bin/zsh

set -euo pipefail

BASE_DIR="/Users/m2macbookair/비쥬얼스튜디오"
PLIST_PATH="$HOME/Library/LaunchAgents/com.m2.stock.researchlab.automation.plist"
PYTHON_BIN="$BASE_DIR/.venv/bin/python"
STDOUT_LOG="$BASE_DIR/research_lab_automation.log"
STDERR_LOG="$BASE_DIR/research_lab_automation.err.log"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="/usr/bin/python3"
fi

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.m2.stock.researchlab.automation</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>-m</string>
        <string>research_lab.automation</string>
        <string>run-due</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$BASE_DIR</string>

    <key>StartInterval</key>
    <integer>300</integer>

    <key>StandardOutPath</key>
    <string>$STDOUT_LOG</string>
    <key>StandardErrorPath</key>
    <string>$STDERR_LOG</string>

    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
PLIST

chmod 644 "$PLIST_PATH"
launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo "설치 완료: $PLIST_PATH"
echo "Research Lab 자동화는 5분마다 시장별 due 상태만 확인합니다."
echo "한국장: Asia/Seoul 09:05~09:50 open, 15:50~17:20 daily"
echo "미국장: America/New_York 09:35~10:20 open, 16:20~17:50 daily"
echo "로그: $STDOUT_LOG / $STDERR_LOG"
