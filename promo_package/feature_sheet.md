# BarStock Feature Sheet

## Bar stock and reporting for member clubs

BarStock is a desktop bar stock and reporting system for member clubs, social clubs and small venues that run a bar without an enterprise EPOS or warehouse system. It was built at Prestonfield Golf Club and is in daily use there.

The whole app follows one visual style — the Ledger: chalk paper, bottle green and copper, serif figures and ruled tables. Reports print in the same style as the screen, so a committee pack looks like part of the system rather than a spreadsheet export.

---

## Core stock management

| Feature | What it does |
|---|---|
| Live stock levels | Tracks every product in pints, bottles, measures or units in real time. |
| Delivery logging | Records supplier deliveries line by line; stock updates automatically. |
| Wastage & returns | Logs wastage and supplier returns with reasons, so the variance report can explain itself. |
| Complimentary tracking | Records complimentary drinks without inflating revenue. |
| Open tabs & functions | Holds member and function tabs open until paid or written off, while still deducting the drinks from stock. |
| Stocktake mode | Full or partial stocktakes with variance against expected stock, valued at cost. |
| Baseline reset | Sets a new stock baseline after a full stocktake; earlier transactions are archived but kept for reporting. |
| Running surplus / shortfall | Carries the surplus or shortfall across every stocktake, so one generous count cannot hide a later loss. |

---

## EPOS and sales

| Feature | What it does |
|---|---|
| CSV sales upload | Upload the weekly EPOS sales report; stock deducts automatically. |
| Child product mapping | Half pints, shandies and TG items deduct from parent stock using configurable ratios. |
| Duplicate upload guard | Warns if the same sales file has already been uploaded. |
| Member / non-member split | Records member and non-member quantities where the EPOS provides them. |
| Name aliases | Matches the till's spellings and abbreviations to the right stock item. |
| Delisted products | Products can be retired from the order sheet and stock list while keeping their sales history in every report. |

---

## Reporting

| Feature | What it does |
|---|---|
| Dashboard summary | Stock holding, period sales, active lines and anything needing attention on one ruled page. |
| Comprehensive report | Opening stock, sales, deliveries, wastage, closing stock, stock value and GP per line. |
| Division report | Draught, bottled beer, wine, spirits, soft drinks, hot drinks and functions, each with sales, cost, GP and stock. |
| Sales analytics | Revenue, cost and GP by category and time period, with the inc-VAT figure shown alongside the ex-VAT one. |
| Stock variance | Counted vs expected stock with the pound value of every variance. |
| Surplus / shortfall | Period and running surplus or shortfall, valued at cost, across baseline resets. |
| Draught yield | Pints sold against kegs delivered, so a line that is pouring badly shows up early. |
| Price history | Every cost and sell price change with its date and reason. |
| Audit checks | Data checks that catch a mismatched stock figure before the committee sees it. |

---

## Ordering and pricing

| Feature | What it does |
|---|---|
| PDF order sheets | Printable order sheets grouped by supplier and product type, with count and order columns. |
| Invoice price check | Upload Booker or supplier invoice CSVs to compare invoice prices against the costs in the system. |
| Bulk price update | Re-price several items in one pass, with supplier returns taken into account. |
| Price locking | Lock an item's price so invoice updates and bulk changes leave it alone. |
| Cost per system unit | Converts invoice prices (and VAT) into the unit the system counts in — pint, bottle, 35ml, can. |

---

## Data safety

| Feature | What it does |
|---|---|
| Automatic daily backups | Backs up the live database every day the app is launched. |
| Pre-operation backups | Creates a backup before sales uploads, baseline resets and restores. |
| One-click restore | Restore any previous backup from inside the app. |
| Local data | All data lives in an SQLite database on the club's Mac. No cloud dependency. |
| CSV mirrors | Keeps readable stock and transaction CSVs alongside the database for inspection or export. |

---

## Technical summary

- Runs on macOS (Apple Silicon and Intel)
- Launches from `dist/BarStock.app` or installs to Applications
- Uses a local SQLite database in `~/Library/Application Support/BarStockManagement/`
- Reads and writes standard CSV files for imports and exports
- One interface on screen and in print: chalk paper, bottle green and copper, serif figures, ruled tables
- No cloud subscription, no per-user licence and no internet required after setup
