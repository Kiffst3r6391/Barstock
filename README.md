# Bar Stock Management System

A complete bar inventory management application for macOS with gross profit reporting, surplus tracking, and transaction logging.

## Features

- **Stock Management**: Add, update, delete, and search inventory items
- **Transaction Logging**: Record deliveries, sales, wastage, and complimentary items
- **Stock Takes**: Perform full stock counts with variance tracking
- **Reports**:
  - Gross Profit Report with percentages
  - Surplus/Variance Report
  - Draught Yield Report
  - Transaction Log Viewer
- **Data Validation**: Prevents negative inventory, duplicate IDs, and invalid entries
- **Search**: Filter inventory by ID or name
- **User-Friendly**: Dropdown selectors instead of manual ID entry

## Quick Start - Run Without Building

If you have Python 3 installed, you can run the app directly:

```bash
cd "/Users/kiffy/PGC Barstock"
python3 BarStockApp.py
```

Or double-click the `launch.sh` file.

## Building a Launchable App

### Option 1: Automated Build (Recommended)

Run the build script:

```bash
cd "/Users/kiffy/PGC Barstock"
python3 build_app.py
```

This will create `dist/BarStock.app` which you can drag to Applications.

### Option 2: Manual PyInstaller Build

```bash
# Install dependencies
pip3 install pyinstaller pandas

# Build the app
pyinstaller BarStock.spec
```

Result will be in `dist/BarStock.app`.

See [BUILD_README.md](BUILD_README.md) for detailed build instructions.

## Installation

### From Built App

1. Drag `BarStock.app` to your Applications folder
2. Double-click to launch

### First Time Launch

On first run, macOS may show a security warning:
- **Option A**: Right-click the app → Open → Open
- **Option B**: System Preferences → Security & Privacy → Open Anyway

## Data Files

Your data is stored in:
- `~/Library/Application Support/BarStockManagement/barstock.db` - SQLite database with inventory, transactions, backups, and settings

Legacy `stock.csv` and `transaction_log.csv` files are migrated into the database on first run and renamed to `.bak`.

## Requirements

- macOS 10.12 or later
- Python 3.8+ (if running from source)
- pandas library: `pip3 install pandas`

## File Structure

```
/Users/kiffy/PGC Barstock/
├── BarStockApp.py              # Main application code
├── build_app.py                # Automated build script
├── BarStock.spec               # PyInstaller specification
├── data_manager.py             # SQLite persistence layer
├── reports.py                  # Report data processing
├── pdf_generator.py            # PDF report generation
├── sales_mapping.py            # Parent/child stock mappings
├── categories.py               # Category mappings
├── conversions.py              # Unit conversions
├── launch.sh                   # Simple launcher script
├── entitlements.plist          # macOS sandbox entitlements (optional)
├── assets/                     # App icons and Info.plist
├── tests/                      # Unit tests
├── BUILD_README.md             # Detailed build instructions
└── README.md                   # This file
```

## Troubleshooting

### "Python is not installed"

Install Python 3 from https://python.org or via Homebrew:
```bash
brew install python
```

### "No module named 'pandas'"

Install all dependencies:
```bash
pip3 install -r requirements.txt
```

### App won't open (security warning)

Right-click the app → Open → Confirm

Or run in Terminal:
```bash
xattr -cr "/Applications/BarStock.app"
```

### Data files not found

Check that you have permissions to write to `~/Library/Application Support/BarStockManagement/`. The app will create this folder automatically.

## License

© 2024 CArmstrong PGC
