# Bar Stock Management - App Build Instructions

## Quick Start

Run the automated build script:

```bash
cd "/Users/kiffy/PGC Barstock"
python3 build_app.py
```

This will create `dist/BarStock.app` which you can drag to your Applications folder.

## Manual Build (if automated fails)

### Method 1: PyInstaller (Recommended)

1. **Install dependencies:**
   ```bash
   pip3 install -r requirements-build.txt
   ```

2. **Build the app using the existing spec:**
   ```bash
   pyinstaller BarStock.spec
   ```

   To code-sign the build, set your developer identity in the environment:
   ```bash
   export CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
   pyinstaller BarStock.spec
   ```

3. **Find your app:**
   - The app will be in `dist/BarStock.app`
   - Drag it to your Applications folder

## Troubleshooting

### "App can't be opened because it is from an unidentified developer"

**Solution 1:** Right-click the app → Open → Confirm

**Solution 2:** Run in Terminal:
```bash
xattr -cr "/Applications/BarStock.app"
```

### "No module named 'pandas'" during build

Install pandas in your system Python:
```bash
pip3 install pandas
```

### Data files not found

The app stores its SQLite database in `~/Library/Application Support/BarStockManagement/barstock.db`.

## Customizing the App

### Adding a Custom Icon

1. Create a 1024x1024 PNG icon
2. Convert to .icns format using:
   ```bash
   mkdir icon.iconset
   sips -z 16 16     icon.png --out icon.iconset/icon_16x16.png
   sips -z 32 32     icon.png --out icon.iconset/icon_32x32.png
   sips -z 128 128   icon.png --out icon.iconset/icon_128x128.png
   sips -z 256 256   icon.png --out icon.iconset/icon_256x256.png
   sips -z 512 512   icon.png --out icon.iconset/icon_512x512.png
   iconutil -c icns icon.iconset
   ```
3. Reference it in the build command with `--icon icon.icns`

## Distribution

After building, create a ZIP for sharing:

```bash
cd dist
zip -r "BarStockManagement-macOS.zip" "BarStock.app"
```

## Files Overview

- `BarStockApp.py` - Main application code
- `BarStock.spec` - PyInstaller specification
- `build_app.py` - Automated build script
- `data_manager.py` - SQLite persistence layer
- `reports.py` - Report data processing
- `pdf_generator.py` - PDF report generation
- `sales_mapping.py` - Parent/child stock mappings
- `categories.py` - Category mappings
- `conversions.py` - Unit conversions
- `dist/` - Built app output directory
