BarStock Management - Bruntsfield Links
=======================================

RUNNING THE APP
---------------
1. Extract the whole ZIP to a folder (do not run it from inside the ZIP).
2. Open the extracted folder and double-click BarStockManagement.exe.
3. If Windows SmartScreen appears, choose "More info" then "Run anyway".
   The app is not code-signed, so Windows may show this warning once.
4. No Python or other software is required.

FIRST RUN
---------
The app starts with an empty stock list. To add your products:
- Click "Import Items.csv" on the dashboard, or
- Use More Actions -> System -> Init from Items.csv.

The CSV must have a "Name" column. Optional columns:
  Division, Unit, Total Stock, Total Value, Cost Price, Sell Price
If Cost Price is omitted, it is calculated from Total Value / Total Stock.
If Sell Price is omitted, a starting price of cost x 1.3 is used.

You can also add items one at a time in Manage Stock.

WHERE YOUR DATA LIVES
---------------------
Your live database, backups and logs are stored outside the app folder:
  %LOCALAPPDATA%\BruntsfieldBarStock
Backups are in the "backups" subfolder. The app takes one automatic backup
per day on first launch and keeps the newest 7. Manual backups are kept (20).

MOVING OR UPDATING THE APP
--------------------------
You can move or replace the app folder without losing data; the data folder
above is separate. Copy the data folder if you want to back it up manually.

SUPPORT
-------
Keep a copy of this README and the app folder together.
