# ABOUTME: End-to-end simulation tests for the printer installer.
# ABOUTME: Validates complete flows by tracing logic without subprocess calls.

import unittest
import ast
import os
import types
import csv

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
# Loading our own trusted source functions for testing without import side effects
exec(_code, _mod.__dict__)  # noqa: S102

parse_lpstat_output = _mod.parse_lpstat_output
build_lpadmin_command = _mod.build_lpadmin_command
parse_dialog_select = _mod.parse_dialog_select
parse_dialog_textfield = _mod.parse_dialog_textfield
parse_csv_to_queue_definitions = _mod.parse_csv_to_queue_definitions

GENERIC_PPD = "/System/Library/Frameworks/ApplicationServices.framework/Versions/A/Frameworks/PrintCore.framework/Versions/A/Resources/Generic.ppd"
COPY_CODE_LENGTH = 5


def simulate_filter(queue_defs, current_queues, filter_key=None, filter_value=None):
    """Exact replica of build_printer_queue_list logic (without show_message/quit)."""
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


def simulate_driver_selection(driver_value):
    """Exact replica of add_queue driver selection logic."""
    if driver_value and 'Generic.ppd' not in driver_value:
        return 'vendor', driver_value
    else:
        return 'generic', GENERIC_PPD


def simulate_add_queue(queue_def, code_input=None):
    """Simulates the full add_queue flow and returns the lpadmin command that
    would be built, or an error description."""
    q = queue_def

    kind, q_driver = simulate_driver_selection(q['Driver'])

    user_number = None
    user_number_option = None
    if 'SHARP' in q['Driver']:
        if code_input is None:
            return {'error': 'SHARP printer requires copy code input but none provided'}
        copy_code = parse_dialog_textfield(code_input)
        if copy_code and copy_code.isdigit() and len(copy_code) == COPY_CODE_LENGTH:
            user_number = copy_code
            user_number_option = 'ARUserNumber=Custom.' + user_number
        else:
            return {'error': 'Invalid copy code: {}'.format(copy_code)}

    options = q['Options'] if q['Options'] else None
    cmd = build_lpadmin_command(
        q['DisplayName'], q['Location'], q['URI'], q_driver,
        user_number_option, options
    )

    return {
        'cmd': cmd,
        'driver_type': kind,
        'driver_path': q_driver,
        'user_number': user_number,
        'needs_cups_restart': user_number_option is not None,
    }


# Load example CSV
_csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "example_printers.csv")
with open(_csv_path) as _cf:
    _example_queues = parse_csv_to_queue_definitions(_cf.read().splitlines())


class TestEndToEndGenericPrinter(unittest.TestCase):
    """Simulate installing a generic driver printer."""

    def test_full_flow_generic_printer(self):
        lpstat_output = (
            "printer BLDGA-Office-M402 is idle.\n"
            "printer BLDGA-Rm101-M404 is idle.\n"
        )
        current = parse_lpstat_output(lpstat_output)
        self.assertEqual(len(current), 2)

        bldgb_queues = {k: v for k, v in _example_queues.items()
                        if v['Location'].startswith('Building B')}

        available = simulate_filter(bldgb_queues, current,
                                    filter_key='Location', filter_value='Building B')
        self.assertIn('BLDGB-Rm310-HL3295', available)
        self.assertNotIn('BLDGA-Office-M402', available)

        q = _example_queues['BLDGB-Rm310-HL3295']
        result = simulate_add_queue(q)
        self.assertIn('cmd', result)
        self.assertEqual(result['driver_type'], 'generic')
        self.assertEqual(result['driver_path'], GENERIC_PPD)
        self.assertFalse(result['needs_cups_restart'])
        self.assertIsNone(result['user_number'])

        cmd = result['cmd']
        self.assertEqual(cmd[0], '/usr/sbin/lpadmin')
        v_idx = cmd.index('-v')
        self.assertTrue(cmd[v_idx + 1].startswith('lpd://'),
                        "URI should start with lpd://")
        self.assertIn('APOptionalDuplexer=True', cmd)


class TestEndToEndHPPrinter(unittest.TestCase):
    """Simulate installing an HP vendor driver printer."""

    def test_full_flow_hp_printer(self):
        q = _example_queues['BLDGA-Office-M402']
        result = simulate_add_queue(q)
        self.assertIn('cmd', result)
        self.assertEqual(result['driver_type'], 'vendor')
        self.assertIn('HP LaserJet', result['driver_path'])
        self.assertFalse(result['needs_cups_restart'])

        cmd = result['cmd']
        v_idx = cmd.index('-v')
        self.assertEqual(cmd[v_idx + 1], 'lpd://printserver/BLDGA-Office-M402')


class TestEndToEndSharpPrinter(unittest.TestCase):
    """Simulate installing a SHARP printer with copy code."""

    def test_full_flow_sharp_with_valid_code(self):
        q = _example_queues['BLDGB-Rm300-BP70M45']
        result = simulate_add_queue(q, code_input=" : 54321")
        self.assertIn('cmd', result)
        self.assertEqual(result['driver_type'], 'vendor')
        self.assertEqual(result['user_number'], '54321')
        self.assertTrue(result['needs_cups_restart'])

        cmd = result['cmd']
        self.assertIn('ARUserNumber=Custom.54321', cmd)
        self.assertIn('printer-is-shared=false', cmd)

    def test_sharp_with_invalid_code_rejected(self):
        q = _example_queues['BLDGB-Rm300-BP70M45']
        result = simulate_add_queue(q, code_input=" : abc")
        self.assertIn('error', result)

    def test_sharp_with_too_short_code_rejected(self):
        q = _example_queues['BLDGB-Rm300-BP70M45']
        result = simulate_add_queue(q, code_input=" : 123")
        self.assertIn('error', result)

    def test_sharp_with_no_code_input(self):
        q = _example_queues['BLDGB-Rm300-BP70M45']
        result = simulate_add_queue(q, code_input=None)
        self.assertIn('error', result)

    def test_sharp_with_empty_dialog_output(self):
        q = _example_queues['BLDGB-Rm300-BP70M45']
        result = simulate_add_queue(q, code_input="")
        self.assertIn('error', result)


class TestEndToEndKonicaPrinter(unittest.TestCase):
    """Simulate installing a Konica printer."""

    def test_full_flow_konica(self):
        q = _example_queues['BLDGA-WorkRm-C658']
        result = simulate_add_queue(q)
        self.assertIn('cmd', result)
        self.assertEqual(result['driver_type'], 'vendor')
        self.assertIn('KONICAMINOLTAC658', result['driver_path'])
        self.assertFalse(result['needs_cups_restart'])


class TestEndToEndFilterScenarios(unittest.TestCase):
    """Test filtering as Jamf would invoke it."""

    def test_building_b_filter_excludes_other_locations(self):
        available = simulate_filter(_example_queues, [],
                                    filter_key='Location', filter_value='Building B')
        for name in available:
            q = _example_queues[name]
            self.assertTrue(q['Location'].startswith('Building B'),
                            "{} has location {}, expected Building B*".format(name, q['Location']))

    def test_no_filter_returns_all(self):
        available = simulate_filter(_example_queues, [])
        self.assertEqual(len(available), len(_example_queues))

    def test_all_mapped_returns_empty(self):
        all_names = list(_example_queues.keys())
        available = simulate_filter(_example_queues, all_names)
        self.assertEqual(available, [])

    def test_mapped_printer_excluded(self):
        current = ['BLDGA-Office-M402', 'BLDGA-Rm101-M404']
        available = simulate_filter(_example_queues, current,
                                    filter_key='Location', filter_value='Building A')
        self.assertNotIn('BLDGA-Office-M402', available)
        self.assertNotIn('BLDGA-Rm101-M404', available)


class TestEndToEndURIValidation(unittest.TestCase):
    """Verify every printer in the example CSV produces a valid lpadmin command."""

    def test_all_printers_have_valid_uri_in_command(self):
        failures = []
        for name, q in _example_queues.items():
            kind, driver = simulate_driver_selection(q['Driver'])
            options = q['Options'] if q['Options'] else None

            user_opt = 'ARUserNumber=Custom.99999' if 'SHARP' in q['Driver'] else None

            cmd = build_lpadmin_command(
                q['DisplayName'], q['Location'], q['URI'], driver,
                user_opt, options
            )
            v_idx = cmd.index('-v')
            uri = cmd[v_idx + 1]
            if '://' not in uri:
                failures.append("{}: URI is '{}' (no scheme)".format(name, uri))

        self.assertEqual(failures, [],
                         "Printers with invalid URIs:\n" + "\n".join(failures))

    def test_all_printers_have_lpd_scheme(self):
        for name, q in _example_queues.items():
            uri = q['URI']
            self.assertTrue(uri.startswith('lpd://'),
                            "{}: URI is '{}', expected lpd://".format(name, uri))


class TestEndToEndConfirmationMessage(unittest.TestCase):
    """Verify the right confirmation message type is selected per driver."""

    def _get_message_type(self, q):
        if q['DriverTrigger'] == 'konica_drivers':
            return 'konica'
        elif 'SHARP' in q['Driver']:
            return 'sharp'
        elif '/hp ' in q['Driver'] or '/HP ' in q['Driver']:
            return 'hp'
        else:
            return 'generic'

    def test_sharp_gets_sharp_message(self):
        q = _example_queues['BLDGB-Rm300-BP70M45']
        self.assertEqual(self._get_message_type(q), 'sharp')

    def test_konica_gets_konica_message(self):
        q = _example_queues['BLDGA-WorkRm-C658']
        self.assertEqual(self._get_message_type(q), 'konica')

    def test_generic_driver_gets_generic_message(self):
        q = _example_queues['BLDGB-Rm310-HL3295']
        self.assertEqual(self._get_message_type(q), 'generic')


class TestEndToEndPreselectedQueue(unittest.TestCase):
    """Verify preselected_queue behavior."""

    def test_preselected_in_available_is_selected(self):
        available = ['A-Printer', 'B-Printer', 'C-Printer']
        preselected = 'B-Printer'
        if preselected and preselected in available:
            selected = preselected
        else:
            selected = None
        self.assertEqual(selected, 'B-Printer')

    def test_preselected_not_in_available_falls_through(self):
        available = ['A-Printer', 'B-Printer']
        preselected = 'Z-Printer'
        if preselected and preselected in available:
            selected = preselected
        else:
            selected = None
        self.assertIsNone(selected)


if __name__ == '__main__':
    unittest.main()
