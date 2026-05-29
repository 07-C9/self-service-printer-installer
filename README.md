# Self-Service Printer Installer

Based on [self-service-printer-installer](https://github.com/haircut/self-service-printer-installer) by [Matthew Warren](https://github.com/haircut).

A macOS script intended for Jamf Pro Self Service that lets end users install network printers on their own. Downloads printer definitions from a Google Sheets CSV at runtime, shows a SwiftDialog picker, and maps the queue via `lpadmin`. Can be adapted for other MDMs or run standalone.

## How it works

1. Downloads the printer catalog from a Google Sheets CSV (nothing is hardcoded)
2. Shows the user a list of available printers, minus any they already have installed
3. Installs the vendor print driver via Jamf policy trigger if needed
4. Maps the queue via `lpadmin` with the correct PPD, URI, and any per-printer options
5. For copiers that require it, can prompt for a copy code and write it into the PPD for account tracking (configurable via `COPY_CODE_ENABLED` and `COPY_CODE_DRIVER_KEYWORD`)
6. User can add another printer or finish

## Printer types

| Type | Driver | Account tracking |
|------|--------|-----------------|
| HP LaserJet | Vendor PPD via Jamf trigger | None |
| Copiers with copy codes (e.g. SHARP) | Vendor PPD + `ARUserNumber` via lpadmin | Configurable (copy code prompted, validated, saved when enabled) |
| Konica Minolta | Vendor PPD via Jamf trigger | Manual (user gets a link to a setup article) |
| Generic (Brother, etc.) | Built-in `Generic.ppd` | None |

When `COPY_CODE_ENABLED` is `True` and the selected printer's Driver path contains the `COPY_CODE_DRIVER_KEYWORD` (defaults to `SHARP`), the script prompts for a copy code, validates the input (length set by `COPY_CODE_LENGTH`), writes it into the PPD with `lpadmin -o ARUserNumber=Custom.<code>`, restarts CUPS, and saves the code to `~/Library/PrinterInstaller/usernumber` so they don't have to enter it again next time. The prompt text, dialog title, and image are all configurable. Set `COPY_CODE_ENABLED` to `False` to disable the feature entirely.

Konica copiers need manual account tracking setup after install. The confirmation dialog links to a configurable support article for that.

## Requirements

- macOS (tested Catalina through Tahoe)
- [Mac Admins Python](https://github.com/macadmins/python) - the shebang points to the Managed Python framework path (`/Library/ManagedFrameworks/Python/Python3.framework/...`). Update the first line of the script if your environment uses a different Python 3 path.
- [SwiftDialog](https://github.com/swiftDialog/swiftDialog) for the UI
- [Jamf Pro](https://www.jamf.com/) (intended for, but the core logic uses `lpadmin` and can be adapted for other MDMs or run standalone)
- `requests` library (auto-installed at runtime if missing)

## Setup

### 1. Create your printer spreadsheet

Create a Google Sheet with these columns:

| DisplayName | Driver | URI | DriverTrigger | Location | Options |
|-------------|--------|-----|---------------|----------|---------|
| Office-M402 | /Library/Printers/PPDs/.../HP LaserJet Pro M402-M403 n-dn.gz | lpd://printserver/Office-M402 | print_drivers | Main Office | |
| WorkRm-BP70C45 | /Library/Printers/PPDs/.../SHARP BP-70C45.PPD | lpd://printserver/WorkRm-BP70C45 | sharp_drivers | Work Room | Option1=Finisher |

Column breakdown:

- `DisplayName` - Queue name shown to the user and used as the CUPS queue name
- `Driver` - Full path to the PPD, or the Generic.ppd path for generic printers
- `URI` - Print queue URI, typically `lpd://your-print-server/queue-name`
- `DriverTrigger` - Jamf policy trigger that installs the vendor driver package
- `Location` - Used for filtering and shown in CUPS printer info
- `Options` - Space-separated `lpadmin -o` options (e.g. `APOptionalDuplexer=True` or `Option1=Finisher Option9=PModule33`)

Share the sheet as "Anyone with the link can view" and grab the CSV export URL:
```
https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/export?format=csv&gid=0
```

The `GOOGLE_SHEET_URL` constant accepts any URL that returns CSV data, so you're not locked into Google Sheets.

See `example_printers.csv` for the expected format.

### 2. Configure the script

Edit the constants at the top of `printer_installer.py`:

```python
# Branding and support
BRANDICON = "https://example.com/your-org-logo.png"
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/export?format=csv&gid=0"
SUPPORT_TICKET_URL = "https://example.com/support/tickets/new"
ACCOUNT_TRACK_ARTICLE_URL = "https://example.com/support/articles/account-tracking"
SHARP_COPIER_ARTICLE_URL = "https://example.com/support/articles/sharp-copiers"
HELP_DESK_MESSAGE = "For assistance, please contact your Help Desk."

# Copy code settings
COPY_CODE_ENABLED = True
COPY_CODE_DRIVER_KEYWORD = "SHARP"
COPY_CODE_LENGTH = 5
COPY_CODE_DIALOG_TITLE = "Enter Your Copy Code"
COPY_CODE_PROMPT = "Please enter your copy code:"
COPY_CODE_IMAGE = "https://example.com/your-copy-code-image.png"
```

### 3. Deploy via Jamf

Upload the script to Jamf Pro (Settings > Scripts), then create a Self Service policy.

Jamf reserves parameters 1-3 (mount point, computer name, username). The script uses:

- Parameter 4 (`preselected_queue`): Auto-install a specific printer by DisplayName, no picker shown
- Parameter 5 (`filter_key`): Any CSV column name to filter on
- Parameter 6 (`filter_value`): Value to match (uses `startswith`, so partial matches work)

### Filtering strategies

The filter uses `startswith` matching against whichever CSV column you specify. This is how you keep things organized when you have hundreds of printers across multiple sites.

**By naming convention:** If your printer names follow a pattern like `SITE-Room-Model` (e.g. `BLDGA-Rm101-M402`), you can filter on `DisplayName` with a site prefix. Set `filter_key` to `DisplayName` and `filter_value` to the prefix. A policy with `filter_value=BLDGA` shows only printers whose name starts with `BLDGA`.

**By location:** If you populate the `Location` column consistently, you can filter on that instead. Set `filter_key` to `Location` and `filter_value` to the building or campus name.

**Combined with Jamf scope:** The script filters which printers appear in the list, but Jamf controls which computers even see the policy. You can scope each policy to a network segment, building, department, or smart/static computer group. For example, a policy scoped to a specific network segment and filtered by site prefix means users only see their local printers when they're on-site.

**No filter (show everything):** Leave parameters 5 and 6 empty. The user sees every printer in the spreadsheet that isn't already installed. This works fine for smaller environments.

**Auto-install a specific printer:** Set parameter 4 to the exact DisplayName. The script skips the picker and maps that queue directly. Useful for lab deployments or default printers pushed by policy.

### Per-printer options

The `Options` column in the CSV passes additional `-o` flags to `lpadmin`. Some real-world examples:

- `APOptionalDuplexer=True` tells CUPS the printer has a duplexer (useful for printers using Generic.ppd that wouldn't otherwise know about the hardware)
- `Option1=Finisher Option9=PModule33` enables the stapler/finisher module on SHARP copiers

Multiple options are space-separated. These get passed straight through to `lpadmin`, so anything `lpadmin -o` accepts will work.

### Jamf policy architecture

```
Printer Installer - Site A (Self Service)
  |-- Scope: Network segment for Site A
  |-- Parameter 5: DisplayName
  |-- Parameter 6: SITEA
  |
  |-- Triggers referenced by DriverTrigger column:
       |-- print_drivers -> installs HP driver package
       |-- sharp_drivers -> installs SHARP driver package
       |-- konica_drivers -> installs Konica Minolta driver package
       |-- InstallSwiftDialog -> installs SwiftDialog if missing
```

## Tests

```bash
python3 -m pytest tests/ -v
```

98 tests covering:
- Pure function logic (lpstat parsing, lpadmin command building, dialog output parsing, CSV parsing)
- Queue filtering and exclusion
- Driver detection (vendor vs. generic)
- End-to-end simulations for HP, SHARP, Konica, and generic printer flows
- Copy code validation (configurable length)
- Edge cases (empty input, malformed output, missing columns)

## Project structure

```
.
├── printer_installer.py      # The script that gets deployed to Jamf
├── example_printers.csv      # Example CSV showing the required format
├── tests/
│   ├── test_printer_installer.py   # Unit tests for pure logic functions
│   └── test_end_to_end.py          # End-to-end flow simulations
├── CHANGELOG.md
├── LICENSE                   # GPL-3.0 (inherited from upstream)
└── README.md
```

## What changed from the original

The original used CocoaDialog for the UI and Python 2. CocoaDialog is [no longer actively developed](https://github.com/cocoadialog/cocoadialog) and had notarization issues on Catalina and later, so it was replaced with SwiftDialog. Python 2 was replaced with Python 3 via Mac Admins Python. See `CHANGELOG.md` for the full history.

## License

GPL-3.0 - See [LICENSE](LICENSE)
