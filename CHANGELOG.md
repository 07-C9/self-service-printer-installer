# Changelog

## v0.1.0 - Original

- Based on [haircut/self-service-printer-installer](https://github.com/haircut/self-service-printer-installer)
  by Matthew Warren.

## v0.1.1 - 2022-04-06

- Ported from Python 2 to Python 3 using [2to3](https://docs.python.org/3/library/2to3.html).
  Manually fixed a string being passed as bytes after conversion.

## v0.1.2 - 2022-08-12

- Removed the built-in CocoaDialog installer check, which was erroring on first run.
  Replaced with a separate prerequisite policy.

## v0.1.3 - 2023-05-31

- Fixed issue where script errors when cancel is clicked.

## v0.1.4 - 2023-06-29

- Converted UI from CocoaDialog to SwiftDialog. CocoaDialog is
  [no longer actively developed](https://github.com/cocoadialog/cocoadialog) and had
  notarization issues on Catalina and later.
- Fixed issue where printers already installed still appeared in the selection list.
- Fixed `filter_key`/`filter_value` filtering so separate Jamf policies can scope the
  printer list per location (faster, cleaner UX).
- Added organization logo and a help button linking to the service desk.

## v0.1.5 - 2023-08-24

- Added copy code functionality for SHARP copiers. Prompts the user for their copy code
  and writes it to the PPD via lpadmin (`ARUserNumber=Custom.<code>`). Persists the code
  to `~/Library/PrinterInstaller/usernumber` for reuse. Restarts CUPS after writing.

## v0.1.6 - 2024-12-17

- Added `SD_APP_PATH` check. After SwiftDialog updated to 2.5.5, some computers had the .app
  removed from /Library/Application Support/Dialog/. Now checks for both the binary and the
  .app bundle.
- Removed the macOS version check for Big Sur (no longer in the fleet) and the Big Sur-specific
  SwiftDialog installer trigger.

## v0.1.7 - 2025-10-08

- Fixed out-of-index error when a user tries to install a printer while an already-installed
  printer is showing paused/error status. The lpstat output includes a second line for the
  error state, and the script didn't know how to handle it. Added logic to ignore continuation
  lines during lpstat parsing.

## v0.1.8 - 2025-10-09

- Re-added Options column support. Allows per-printer lpadmin options to be defined in the
  CSV/spreadsheet (e.g. stapler/finisher modules on SHARP copiers, duplex on Brother printers).

## v0.2.0 - 2026-05-22

- Comprehensive audit of all pure logic functions; extracted into testable units
- Fixed lpadmin error handling - now checks return code and logs stderr (previously silent on failure)
- Fixed CUPS restart ordering - moved to after lpadmin for SHARP printers
- Added Google Sheets download timeout (30s) and error handling
- Fixed `read_user_number` to validate codes using configurable length (was checking wrong length)
- Fixed `filter_value=None` causing TypeError in queue filtering
- Fixed `preselected_queue` breaking "Add Another Printer" flow
- Fixed `install_drivers` using wrong jamf path
- Fixed `search_for_driver` running `jamf policy -event ""` on empty DriverTrigger
- Fixed `parse_dialog_select` crash (IndexError) on malformed SwiftDialog output
- Fixed bare except on requests import to catch only ImportError
- Added error handling to `save_user_number` file operations
- Removed unnecessary `shell=True` in `get_current_user`
- `run_jamf_policy` now returns False on unexpected output instead of None
- Added 98 tests (unit + end-to-end simulation)
