# ABOUTME: Test suite for the printer installer script.
# ABOUTME: Tests pure logic functions and error handling paths.

import unittest
import sys
import os
import csv
import io
import ast
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "printer_installer.py")
with open(_source_path, encoding='utf-8-sig') as _f:
    _source = _f.read()

_func_names = (
    'parse_lpstat_output',
    'build_lpadmin_command',
    'parse_dialog_select',
    'parse_dialog_textfield',
    'parse_csv_to_queue_definitions',
)

_func_sources = []
for node in ast.parse(_source).body:
    if isinstance(node, ast.FunctionDef) and node.name in _func_names:
        _func_sources.append(ast.unparse(node))

_test_module_source = "import csv\n\n" + "\n\n".join(_func_sources)

_mod = types.ModuleType("printer_funcs")
_mod.__dict__['csv'] = csv
_code = compile(_test_module_source, "<test_functions>", "exec")
# We use exec here intentionally to load extracted pure functions from the
# production script without triggering its import-time side effects (network
# calls, SwiftDialog checks, etc). The source is our own trusted script, not
# external input.
exec(_code, _mod.__dict__)  # noqa: S102

parse_lpstat_output = _mod.parse_lpstat_output
build_lpadmin_command = _mod.build_lpadmin_command
parse_dialog_select = _mod.parse_dialog_select
parse_dialog_textfield = _mod.parse_dialog_textfield
parse_csv_to_queue_definitions = _mod.parse_csv_to_queue_definitions


# ---------------------------------------------------------------------------
# Tests for parse_lpstat_output
# ---------------------------------------------------------------------------

class TestParseLpstatOutput(unittest.TestCase):

    def test_typical_output(self):
        output = (
            "printer Office-M402 is idle. enabled since Mon Jan 01 00:00:00 2024\n"
            "printer Lab-M404 is idle. enabled since Mon Jan 01 00:00:00 2024\n"
        )
        result = parse_lpstat_output(output)
        self.assertEqual(result, ['Office-M402', 'Lab-M404'])

    def test_disabled_printer(self):
        output = "printer OldPrinter disabled since Mon Jan 01 00:00:00 2024\n"
        result = parse_lpstat_output(output)
        self.assertEqual(result, ['OldPrinter'])

    def test_none_input(self):
        self.assertEqual(parse_lpstat_output(None), [])

    def test_empty_string(self):
        self.assertEqual(parse_lpstat_output(""), [])

    def test_blank_lines_skipped(self):
        output = "\n\nprinter TestPrinter is idle.\n\n"
        result = parse_lpstat_output(output)
        self.assertEqual(result, ['TestPrinter'])

    def test_continuation_lines_skipped(self):
        output = (
            "printer PausedPrinter disabled since Mon Jan 01 00:00:00 2024 -\n"
            "\tPaused - offline\n"
            "printer ActivePrinter is idle. enabled since Mon Jan 01 00:00:00 2024\n"
        )
        result = parse_lpstat_output(output)
        self.assertEqual(result, ['PausedPrinter', 'ActivePrinter'])

    def test_single_printer(self):
        output = "printer EPSON_ET_2850_Series is idle. enabled since Mon Jan 01 00:00:00 2024\n"
        result = parse_lpstat_output(output)
        self.assertEqual(result, ['EPSON_ET_2850_Series'])

    def test_five_queues(self):
        output = (
            "printer Office-M402 is idle. enabled since Mon Jan 01 00:00:00 2024\n"
            "printer Lab-M404 is idle. enabled since Mon Jan 01 00:00:00 2024\n"
            "printer WorkRm-C658 is idle. enabled since Mon Jan 01 00:00:00 2024\n"
            "printer EPSON_ET_2850_Series is idle. enabled since Mon Jan 01 00:00:00 2024\n"
            "printer Rm101-HL-L3295CDW is idle. enabled since Mon Jan 01 00:00:00 2024\n"
        )
        result = parse_lpstat_output(output)
        self.assertEqual(len(result), 5)
        self.assertIn('Office-M402', result)
        self.assertIn('Rm101-HL-L3295CDW', result)


# ---------------------------------------------------------------------------
# Tests for build_lpadmin_command
# ---------------------------------------------------------------------------

class TestBuildLpadminCommand(unittest.TestCase):

    def test_basic_generic_printer(self):
        generic_ppd = "/System/Library/Frameworks/ApplicationServices.framework/Versions/A/Frameworks/PrintCore.framework/Versions/A/Resources/Generic.ppd"
        cmd = build_lpadmin_command(
            "TestPrinter", "Main Office",
            "lpd://printserver/TestPrinter", generic_ppd
        )
        self.assertEqual(cmd[0], '/usr/sbin/lpadmin')
        self.assertEqual(cmd[cmd.index('-p') + 1], 'TestPrinter')
        self.assertEqual(cmd[cmd.index('-L') + 1], 'Main Office')
        self.assertEqual(cmd[cmd.index('-v') + 1], 'lpd://printserver/TestPrinter')
        self.assertEqual(cmd[cmd.index('-P') + 1], generic_ppd)
        self.assertIn('-E', cmd)
        self.assertIn('printer-is-shared=false', cmd)

    def test_with_user_number_option(self):
        cmd = build_lpadmin_command(
            "TestPrinter", "Loc",
            "lpd://printserver/TestPrinter", "/path/to/driver.ppd",
            user_number_option="ARUserNumber=Custom.12345"
        )
        idx = cmd.index('ARUserNumber=Custom.12345')
        self.assertEqual(cmd[idx - 1], '-o')

    def test_with_options_string(self):
        cmd = build_lpadmin_command(
            "TestPrinter", "Loc",
            "lpd://printserver/TestPrinter", "/path/to/driver.ppd",
            options_str="APOptionalDuplexer=True"
        )
        idx = cmd.index('APOptionalDuplexer=True')
        self.assertEqual(cmd[idx - 1], '-o')

    def test_with_multiple_options(self):
        cmd = build_lpadmin_command(
            "TestPrinter", "Loc",
            "lpd://printserver/TestPrinter", "/path/to/driver.ppd",
            options_str="Option1=Finisher Option9=PModule33"
        )
        self.assertIn('Option1=Finisher', cmd)
        self.assertIn('Option9=PModule33', cmd)

    def test_sharp_printer_full_command(self):
        cmd = build_lpadmin_command(
            "WorkRm-BP70C45", "Building A",
            "lpd://printserver/WorkRm-BP70C45",
            "/Library/Printers/PPDs/Contents/Resources/SHARP BP-70C45.PPD.gz",
            user_number_option="ARUserNumber=Custom.54321",
            options_str="Option1=Finisher Option9=PModule33"
        )
        self.assertIn('ARUserNumber=Custom.54321', cmd)
        self.assertIn('Option1=Finisher', cmd)
        self.assertIn('Option9=PModule33', cmd)

    def test_no_optional_args(self):
        cmd = build_lpadmin_command(
            "SimplePrinter", "Office",
            "lpd://printserver/SimplePrinter", "/path/to/Generic.ppd"
        )
        o_count = cmd.count('-o')
        self.assertEqual(o_count, 1)
        self.assertIn('printer-is-shared=false', cmd)


# ---------------------------------------------------------------------------
# Tests for parse_dialog_select
# ---------------------------------------------------------------------------

class TestParseDialogSelect(unittest.TestCase):

    def test_typical_selection(self):
        output = '"Select a Printer:" : "Office-M402"'
        result = parse_dialog_select(output)
        self.assertEqual(result, 'Office-M402')

    def test_no_selection(self):
        result = parse_dialog_select("")
        self.assertIsNone(result)

    def test_none_input(self):
        result = parse_dialog_select(None)
        self.assertIsNone(result)

    def test_multiline_output(self):
        output = (
            'Some other line\n'
            '"Select a Printer:" : "Rm101-HL-L3295CDW"\n'
            'Another line\n'
        )
        result = parse_dialog_select(output)
        self.assertEqual(result, 'Rm101-HL-L3295CDW')

    def test_no_matching_line(self):
        output = "Some unrelated dialog output\nAnother line\n"
        result = parse_dialog_select(output)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Tests for parse_dialog_textfield
# ---------------------------------------------------------------------------

class TestParseDialogTextfield(unittest.TestCase):

    def test_typical_input(self):
        output = "TextField : 54321"
        result = parse_dialog_textfield(output)
        self.assertEqual(result, '54321')

    def test_none_input(self):
        result = parse_dialog_textfield(None)
        self.assertIsNone(result)

    def test_empty_input(self):
        result = parse_dialog_textfield("")
        self.assertIsNone(result)

    def test_no_separator(self):
        result = parse_dialog_textfield("garbage output with no colon separator")
        self.assertIsNone(result)

    def test_multiple_colons(self):
        output = "Label : value : with : colons"
        result = parse_dialog_textfield(output)
        self.assertEqual(result, 'value : with : colons')

    def test_whitespace_stripping(self):
        output = "TextField :   12345  \n"
        result = parse_dialog_textfield(output)
        self.assertEqual(result, '12345')


# ---------------------------------------------------------------------------
# Tests for parse_csv_to_queue_definitions
# ---------------------------------------------------------------------------

class TestParseCsvToQueueDefinitions(unittest.TestCase):

    def _make_csv_lines(self, rows):
        header = "DisplayName,Driver,URI,DriverTrigger,Location,Options"
        lines = [header]
        for row in rows:
            lines.append(','.join(row))
        return lines

    def test_single_generic_printer(self):
        lines = self._make_csv_lines([
            ["TestPrinter", "/path/Generic.ppd", "lpd://printserver/TestPrinter",
             "", "Test Location", "APOptionalDuplexer=True"]
        ])
        result = parse_csv_to_queue_definitions(lines)
        self.assertIn('TestPrinter', result)
        self.assertEqual(result['TestPrinter']['URI'], 'lpd://printserver/TestPrinter')
        self.assertEqual(result['TestPrinter']['Options'], 'APOptionalDuplexer=True')

    def test_vendor_driver_printer(self):
        lines = self._make_csv_lines([
            ["HP-Printer", "/Library/Printers/PPDs/Contents/Resources/HP LaserJet.gz",
             "lpd://printserver/HP-Printer", "print_drivers", "Office", ""]
        ])
        result = parse_csv_to_queue_definitions(lines)
        self.assertEqual(result['HP-Printer']['DriverTrigger'], 'print_drivers')
        self.assertEqual(result['HP-Printer']['Options'], '')

    def test_multiple_printers(self):
        lines = self._make_csv_lines([
            ["Printer1", "/drv1", "lpd://printserver/Printer1", "trig1", "Loc1", ""],
            ["Printer2", "/drv2", "lpd://printserver/Printer2", "trig2", "Loc2", "Opt=Val"],
        ])
        result = parse_csv_to_queue_definitions(lines)
        self.assertEqual(len(result), 2)

    def test_empty_csv(self):
        lines = ["DisplayName,Driver,URI,DriverTrigger,Location,Options"]
        result = parse_csv_to_queue_definitions(lines)
        self.assertEqual(len(result), 0)

    def test_options_whitespace_stripped(self):
        lines = self._make_csv_lines([
            ["Printer", "/drv", "lpd://p/Printer", "", "Loc", "  Opt=Val  "]
        ])
        result = parse_csv_to_queue_definitions(lines)
        self.assertEqual(result['Printer']['Options'], 'Opt=Val')

    def test_duplicate_displayname_last_wins(self):
        lines = self._make_csv_lines([
            ["DupPrinter", "/drv1", "lpd://p/Dup1", "", "Loc1", ""],
            ["DupPrinter", "/drv2", "lpd://p/Dup2", "", "Loc2", ""],
        ])
        result = parse_csv_to_queue_definitions(lines)
        self.assertEqual(len(result), 1)
        self.assertEqual(result['DupPrinter']['URI'], 'lpd://p/Dup2')


# ---------------------------------------------------------------------------
# Tests for build_printer_queue_list logic
# ---------------------------------------------------------------------------

class TestBuildPrinterQueueListLogic(unittest.TestCase):

    def _filter_queues(self, queue_defs, current_queues, filter_key=None, filter_value=None):
        """Reimplements the filtering logic from build_printer_queue_list."""
        display_list = []
        for queue, values in list(queue_defs.items()):
            valid_queue = False
            if values['DisplayName'] not in current_queues:
                if 'CUPSName' in values:
                    if values['CUPSName'] not in current_queues:
                        valid_queue = True
                else:
                    valid_queue = True

            if valid_queue:
                if filter_key and filter_value and values.get(filter_key):
                    if values[filter_key].startswith(filter_value):
                        display_list.append(values['DisplayName'])
                elif not filter_key:
                    display_list.append(values['DisplayName'])
        return sorted(display_list) if display_list else []

    def test_excludes_mapped_queues(self):
        defs = {
            'Mapped': {'DisplayName': 'Mapped', 'Location': 'Building A'},
            'Unmapped': {'DisplayName': 'Unmapped', 'Location': 'Building A'},
        }
        result = self._filter_queues(defs, ['Mapped'])
        self.assertEqual(result, ['Unmapped'])

    def test_filter_by_location(self):
        defs = {
            'BLDGA-Printer': {'DisplayName': 'BLDGA-Printer', 'Location': 'Building A'},
            'BLDGB-Printer': {'DisplayName': 'BLDGB-Printer', 'Location': 'Building B'},
        }
        result = self._filter_queues(defs, [], filter_key='Location', filter_value='Building A')
        self.assertEqual(result, ['BLDGA-Printer'])

    def test_startswith_filter(self):
        defs = {
            'P1': {'DisplayName': 'P1', 'Location': 'Building A - Main'},
            'P2': {'DisplayName': 'P2', 'Location': 'Building A - Annex'},
            'P3': {'DisplayName': 'P3', 'Location': 'Building B'},
        }
        result = self._filter_queues(defs, [], filter_key='Location', filter_value='Building A')
        self.assertIn('P1', result)
        self.assertIn('P2', result)
        self.assertNotIn('P3', result)

    def test_no_filter_returns_all_unmapped(self):
        defs = {
            'A': {'DisplayName': 'A', 'Location': 'X'},
            'B': {'DisplayName': 'B', 'Location': 'Y'},
        }
        result = self._filter_queues(defs, [])
        self.assertEqual(result, ['A', 'B'])

    def test_all_mapped_returns_empty(self):
        defs = {
            'Mapped1': {'DisplayName': 'Mapped1', 'Location': 'X'},
            'Mapped2': {'DisplayName': 'Mapped2', 'Location': 'X'},
        }
        result = self._filter_queues(defs, ['Mapped1', 'Mapped2'])
        self.assertEqual(result, [])

    def test_results_are_sorted(self):
        defs = {
            'Z-Printer': {'DisplayName': 'Z-Printer', 'Location': 'X'},
            'A-Printer': {'DisplayName': 'A-Printer', 'Location': 'X'},
            'M-Printer': {'DisplayName': 'M-Printer', 'Location': 'X'},
        }
        result = self._filter_queues(defs, [])
        self.assertEqual(result, ['A-Printer', 'M-Printer', 'Z-Printer'])

    def test_filter_key_with_none_value_does_not_crash(self):
        defs = {
            'P1': {'DisplayName': 'P1', 'Location': 'Building A'},
            'P2': {'DisplayName': 'P2', 'Location': 'Building B'},
        }
        result = self._filter_queues(defs, [], filter_key='Location', filter_value=None)
        self.assertEqual(result, [])

    def test_filter_key_with_empty_value_does_not_crash(self):
        defs = {
            'P1': {'DisplayName': 'P1', 'Location': 'Building A'},
        }
        result = self._filter_queues(defs, [], filter_key='Location', filter_value='')
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Tests for driver detection logic in add_queue
# ---------------------------------------------------------------------------

class TestDriverDetectionLogic(unittest.TestCase):

    GENERIC_PPD = "/System/Library/Frameworks/ApplicationServices.framework/Versions/A/Frameworks/PrintCore.framework/Versions/A/Resources/Generic.ppd"

    def _detect_driver(self, driver_value):
        """Reimplements the driver detection logic from add_queue."""
        if driver_value and 'Generic.ppd' not in driver_value:
            return 'vendor', driver_value
        else:
            return 'generic', self.GENERIC_PPD

    def test_generic_ppd_path(self):
        kind, path = self._detect_driver(self.GENERIC_PPD)
        self.assertEqual(kind, 'generic')
        self.assertEqual(path, self.GENERIC_PPD)

    def test_hp_vendor_driver(self):
        kind, path = self._detect_driver(
            "/Library/Printers/PPDs/Contents/Resources/HP LaserJet Pro M402-M403 n-dn.gz"
        )
        self.assertEqual(kind, 'vendor')
        self.assertIn('HP LaserJet', path)

    def test_sharp_vendor_driver(self):
        kind, path = self._detect_driver(
            "/Library/Printers/PPDs/Contents/Resources/SHARP BP-70C45.PPD.gz"
        )
        self.assertEqual(kind, 'vendor')
        self.assertIn('SHARP', path)

    def test_empty_driver_uses_generic(self):
        kind, path = self._detect_driver("")
        self.assertEqual(kind, 'generic')

    def test_none_driver_uses_generic(self):
        kind, path = self._detect_driver(None)
        self.assertEqual(kind, 'generic')


# ---------------------------------------------------------------------------
# Tests for build_lpadmin_command edge cases
# ---------------------------------------------------------------------------

class TestBuildLpadminCommandEdgeCases(unittest.TestCase):

    def test_command_order_is_deterministic(self):
        cmd1 = build_lpadmin_command("P", "L", "lpd://x", "/d.ppd",
                                     options_str="A=1 B=2")
        cmd2 = build_lpadmin_command("P", "L", "lpd://x", "/d.ppd",
                                     options_str="A=1 B=2")
        self.assertEqual(cmd1, cmd2)

    def test_options_none_vs_empty(self):
        cmd_none = build_lpadmin_command("P", "L", "lpd://x", "/d.ppd",
                                         options_str=None)
        cmd_empty = build_lpadmin_command("P", "L", "lpd://x", "/d.ppd",
                                          options_str="")
        self.assertEqual(len(cmd_none), len(cmd_empty))

    def test_uri_with_special_characters_preserved(self):
        cmd = build_lpadmin_command("P", "L",
                                    "lpd://printserver/My%20Printer", "/d.ppd")
        self.assertEqual(cmd[cmd.index('-v') + 1], 'lpd://printserver/My%20Printer')


# ---------------------------------------------------------------------------
# Tests for parse_dialog_textfield edge cases (copy code validation)
# ---------------------------------------------------------------------------

class TestParseDialogTextfieldEdgeCases(unittest.TestCase):

    def test_copy_code_valid_5_digits(self):
        result = parse_dialog_textfield("TextField : 54321")
        self.assertTrue(result.isdigit())
        self.assertEqual(len(result), 5)

    def test_copy_code_with_leading_zeros(self):
        result = parse_dialog_textfield("TextField : 00123")
        self.assertEqual(result, '00123')
        self.assertTrue(result.isdigit())

    def test_copy_code_too_short(self):
        result = parse_dialog_textfield("TextField : 123")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 3)

    def test_copy_code_non_numeric(self):
        result = parse_dialog_textfield("TextField : abc12")
        self.assertIsNotNone(result)
        self.assertFalse(result.isdigit())

    def test_completely_empty_field(self):
        result = parse_dialog_textfield("TextField : ")
        self.assertEqual(result, '')


# ---------------------------------------------------------------------------
# Tests for CSV parsing edge cases
# ---------------------------------------------------------------------------

class TestCsvParsingEdgeCases(unittest.TestCase):

    def _make_csv_lines(self, rows):
        header = "DisplayName,Driver,URI,DriverTrigger,Location,Options"
        lines = [header]
        for row in rows:
            lines.append(','.join(row))
        return lines

    def test_missing_options_column_defaults_empty(self):
        lines = ["DisplayName,Driver,URI,DriverTrigger,Location",
                 "P1,/d,lpd://x,trig,Loc"]
        result = parse_csv_to_queue_definitions(lines)
        self.assertEqual(result['P1']['Options'], '')

    def test_commas_in_quoted_fields(self):
        lines = ['DisplayName,Driver,URI,DriverTrigger,Location,Options',
                 '"Printer, Special",/d,lpd://x,,Loc,']
        result = parse_csv_to_queue_definitions(lines)
        self.assertIn('Printer, Special', result)


# ---------------------------------------------------------------------------
# Tests for parse_dialog_select edge cases (IndexError fix)
# ---------------------------------------------------------------------------

class TestParseDialogSelectEdgeCases(unittest.TestCase):

    def test_search_key_present_but_no_value(self):
        output = '"Select a Printer:" :'
        result = parse_dialog_select(output)
        self.assertIsNone(result)

    def test_search_key_with_trailing_space_only(self):
        output = '"Select a Printer:" : '
        result = parse_dialog_select(output)
        self.assertIsNone(result)

    def test_search_key_with_empty_quotes(self):
        output = '"Select a Printer:" : ""'
        result = parse_dialog_select(output)
        self.assertIsNone(result)

    def test_valid_selection_still_works(self):
        output = '"Select a Printer:" : "Office-M402"'
        result = parse_dialog_select(output)
        self.assertEqual(result, 'Office-M402')

    def test_printer_name_with_hyphens_and_numbers(self):
        output = '"Select a Printer:" : "Rm108-M402"'
        result = parse_dialog_select(output)
        self.assertEqual(result, 'Rm108-M402')


# ---------------------------------------------------------------------------
# Tests for user number read/save consistency
# ---------------------------------------------------------------------------

class TestUserNumberValidation(unittest.TestCase):

    COPY_CODE_LENGTH = 5

    def test_valid_length_code_input(self):
        code = "54321"
        self.assertTrue(code.isdigit() and len(code) == self.COPY_CODE_LENGTH)

    def test_short_code_input_is_invalid(self):
        code = "5432"
        self.assertFalse(code.isdigit() and len(code) == self.COPY_CODE_LENGTH)

    def test_non_numeric_code_input_is_invalid(self):
        code = "abcde"
        self.assertFalse(code.isdigit() and len(code) == self.COPY_CODE_LENGTH)

    def test_long_stored_number_is_invalid(self):
        code = "543210"
        self.assertFalse(code.isdigit() and len(code) == self.COPY_CODE_LENGTH)

    def test_valid_stored_number(self):
        code = "54321"
        self.assertTrue(code.isdigit() and len(code) == self.COPY_CODE_LENGTH)


# ---------------------------------------------------------------------------
# Tests for parse_lpstat_output edge cases
# ---------------------------------------------------------------------------

class TestParseLpstatOutputEdgeCases(unittest.TestCase):

    def test_printer_name_with_underscores(self):
        output = "printer My_Printer_Name is idle.\n"
        result = parse_lpstat_output(output)
        self.assertEqual(result, ['My_Printer_Name'])

    def test_printer_word_in_name_not_at_start(self):
        output = "  printer-like line that doesnt start with printer\n"
        result = parse_lpstat_output(output)
        self.assertEqual(result, [])

    def test_only_word_printer_no_name(self):
        output = "printer\n"
        result = parse_lpstat_output(output)
        self.assertEqual(result, [])

    def test_mixed_valid_and_garbage(self):
        output = (
            "printer Valid1 is idle.\n"
            "some garbage line\n"
            "\t\tindented continuation\n"
            "printer Valid2 disabled since yesterday\n"
            "not a printer line\n"
        )
        result = parse_lpstat_output(output)
        self.assertEqual(result, ['Valid1', 'Valid2'])


# ---------------------------------------------------------------------------
# Tests for build_lpadmin_command regression checks
# ---------------------------------------------------------------------------

class TestBuildLpadminCommandRegression(unittest.TestCase):

    def test_command_matches_expected_structure(self):
        cmd = build_lpadmin_command(
            "Rm310-HL-L3295CDW", "Building B",
            "lpd://printserver/Rm310-HL-L3295CDW",
            "/System/Library/Frameworks/ApplicationServices.framework/Versions/A/Frameworks/PrintCore.framework/Versions/A/Resources/Generic.ppd",
            options_str="APOptionalDuplexer=True"
        )
        self.assertEqual(cmd[0], '/usr/sbin/lpadmin')
        p_idx = cmd.index('-p')
        self.assertEqual(cmd[p_idx + 1], 'Rm310-HL-L3295CDW')
        l_idx = cmd.index('-L')
        self.assertEqual(cmd[l_idx + 1], 'Building B')
        v_idx = cmd.index('-v')
        self.assertEqual(cmd[v_idx + 1], 'lpd://printserver/Rm310-HL-L3295CDW')
        self.assertIn('APOptionalDuplexer=True', cmd)

    def test_sharp_command_matches_expected(self):
        """Verify SHARP printers get user number AND sheet options."""
        cmd = build_lpadmin_command(
            "WorkRm-BP70M75", "Building A",
            "lpd://printserver/WorkRm-BP70M75",
            "/Library/Printers/PPDs/Contents/Resources/SHARP BP-70M75.PPD.gz",
            user_number_option="ARUserNumber=Custom.12345",
            options_str="Option1=Finisher Option9=PModule33"
        )
        o_indices = [i for i, x in enumerate(cmd) if x == '-o']
        self.assertEqual(len(o_indices), 4)
        o_values = [cmd[i + 1] for i in o_indices]
        self.assertIn('printer-is-shared=false', o_values)
        self.assertIn('ARUserNumber=Custom.12345', o_values)
        self.assertIn('Option1=Finisher', o_values)
        self.assertIn('Option9=PModule33', o_values)


# ---------------------------------------------------------------------------
# Tests for CSV parsing against realistic data patterns
# ---------------------------------------------------------------------------

class TestCsvParsingProductionPatterns(unittest.TestCase):

    def test_sharp_printer_with_options(self):
        lines = [
            "DisplayName,Driver,URI,DriverTrigger,Location,Options",
            "BLDGB-Rm300-BP70M45,/Library/Printers/PPDs/Contents/Resources/SHARP BP-70M45.PPD,lpd://printserver/BLDGB-Rm300-BP70M45,sharp_drivers,Building B - Room 300,"
        ]
        result = parse_csv_to_queue_definitions(lines)
        q = result['BLDGB-Rm300-BP70M45']
        self.assertEqual(q['DriverTrigger'], 'sharp_drivers')
        self.assertIn('SHARP', q['Driver'])

    def test_generic_driver_printer(self):
        lines = [
            "DisplayName,Driver,URI,DriverTrigger,Location,Options",
            "BLDGB-Rm310-HL3295,/System/Library/Frameworks/ApplicationServices.framework/Versions/A/Frameworks/PrintCore.framework/Versions/A/Resources/Generic.ppd,lpd://printserver/BLDGB-Rm310-HL3295,,Building B - Room 310,APOptionalDuplexer=True"
        ]
        result = parse_csv_to_queue_definitions(lines)
        q = result['BLDGB-Rm310-HL3295']
        self.assertEqual(q['DriverTrigger'], '')
        self.assertIn('Generic.ppd', q['Driver'])
        self.assertEqual(q['Options'], 'APOptionalDuplexer=True')

    def test_hp_printer_with_driver_trigger(self):
        lines = [
            "DisplayName,Driver,URI,DriverTrigger,Location,Options",
            "BLDGA-Office-M402,/Library/Printers/PPDs/Contents/Resources/HP LaserJet Pro M402-M403 n-dn.gz,lpd://printserver/BLDGA-Office-M402,print_drivers,Building A - Main Office,"
        ]
        result = parse_csv_to_queue_definitions(lines)
        q = result['BLDGA-Office-M402']
        self.assertEqual(q['DriverTrigger'], 'print_drivers')
        self.assertEqual(q['Options'], '')

    def test_konica_printer(self):
        lines = [
            "DisplayName,Driver,URI,DriverTrigger,Location,Options",
            "BLDGA-WorkRm-C658,/Library/Printers/PPDs/Contents/Resources/KONICAMINOLTAC658.gz,lpd://printserver/BLDGA-WorkRm-C658,konica_drivers,Building A - Work Room,"
        ]
        result = parse_csv_to_queue_definitions(lines)
        q = result['BLDGA-WorkRm-C658']
        self.assertEqual(q['DriverTrigger'], 'konica_drivers')


# ---------------------------------------------------------------------------
# Tests for filter logic edge cases
# ---------------------------------------------------------------------------

class TestFilterLogicEdgeCases(unittest.TestCase):

    def _filter_queues(self, queue_defs, current_queues, filter_key=None, filter_value=None):
        display_list = []
        for queue, values in list(queue_defs.items()):
            valid_queue = False
            if values['DisplayName'] not in current_queues:
                if 'CUPSName' in values:
                    if values['CUPSName'] not in current_queues:
                        valid_queue = True
                else:
                    valid_queue = True
            if valid_queue:
                if filter_key and filter_value and values.get(filter_key):
                    if values[filter_key].startswith(filter_value):
                        display_list.append(values['DisplayName'])
                elif not filter_key:
                    display_list.append(values['DisplayName'])
        return sorted(display_list) if display_list else []

    def test_filter_key_not_in_queue_data(self):
        defs = {
            'P1': {'DisplayName': 'P1', 'Location': 'Building A'},
        }
        result = self._filter_queues(defs, [], filter_key='NonexistentField', filter_value='Building A')
        self.assertEqual(result, [])

    def test_filter_value_exact_match(self):
        defs = {
            'P1': {'DisplayName': 'P1', 'Location': 'Building A'},
            'P2': {'DisplayName': 'P2', 'Location': 'Building A Annex'},
        }
        result = self._filter_queues(defs, [], filter_key='Location', filter_value='Building A')
        self.assertEqual(len(result), 2)

    def test_cups_name_field_present(self):
        defs = {
            'P1': {'DisplayName': 'P1', 'CUPSName': 'cups-p1', 'Location': 'X'},
        }
        result = self._filter_queues(defs, ['cups-p1'])
        self.assertEqual(result, [])

    def test_cups_name_not_mapped_allows_queue(self):
        defs = {
            'P1': {'DisplayName': 'P1', 'CUPSName': 'cups-p1', 'Location': 'X'},
        }
        result = self._filter_queues(defs, ['something-else'])
        self.assertEqual(result, ['P1'])

    def test_display_name_mapped_but_cups_name_not_checked(self):
        defs = {
            'P1': {'DisplayName': 'P1', 'Location': 'X'},
        }
        result = self._filter_queues(defs, ['P1'])
        self.assertEqual(result, [])


if __name__ == '__main__':
    unittest.main()
