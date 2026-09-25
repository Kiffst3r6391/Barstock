#!/bin/bash
# Restore BarStock data from this backup directory.
set -euo pipefail
SCRIPT_DIR=""
APP_SUPPORT="/Users/kiffy/Library/Application Support/BarStockManagement"
REPO_DIR="/Users/kiffy/PGC Barstock"
mkdir -p "$APP_SUPPORT"
cp "$SCRIPT_DIR/barstock.db" "$APP_SUPPORT/barstock.db"
cp "$SCRIPT_DIR/stock.csv" "$REPO_DIR/stock.csv"
cp "$SCRIPT_DIR/transaction_log.csv" "$REPO_DIR/transaction_log.csv"
cp "$SCRIPT_DIR/Items.csv" "$REPO_DIR/Items.csv"
echo "Restored from $SCRIPT_DIR"
