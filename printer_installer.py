#!/Library/ManagedFrameworks/Python/Python3.framework/Versions/Current/bin/python3
# ABOUTME: Self-service printer installer for macOS, deployed via Jamf Pro.
# ABOUTME: Downloads printer definitions from a CSV source and maps queues via lpadmin.
# -*- coding: utf-8 -*-

import sys
import syslog
import os
import subprocess
import csv
import argparse
import pwd

__version__ = "0.2.0"

PRINTERICON = "/System/Library/CoreServices/AddPrinter.app/Contents/Resources/Printer.icns"

JAMF = "/usr/local/bin/jamf"
SDPATH = "/usr/local/bin/dialog"
SD_APP_PATH = "/Library/Application Support/Dialog/Dialog.app"

###############################################################################
# CONFIGURATION - Update these values for your organization
###############################################################################

# URL or path to your organization's logo (displayed in SwiftDialog prompts)
BRANDICON = "https://example.com/your-org-logo.png"

# Copy code settings (for copiers that require user authentication codes)
# Set COPY_CODE_ENABLED to False to skip the copy code prompt entirely
COPY_CODE_ENABLED = True
COPY_CODE_DRIVER_KEYWORD = "SHARP"
COPY_CODE_LENGTH = 5
COPY_CODE_DIALOG_TITLE = "Enter Your Copy Code"
COPY_CODE_PROMPT = "Please enter your copy code:"
COPY_CODE_IMAGE = "https://example.com/your-copy-code-image.png"

# Google Sheets CSV export URL for printer definitions
# Share your Google Sheet as "Anyone with the link can view", then use:
# https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/export?format=csv&gid=0
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID_HERE/export?format=csv&gid=0"

# Help desk / support URLs shown to end users
SUPPORT_TICKET_URL = "https://example.com/support/tickets/new"
ACCOUNT_TRACK_ARTICLE_URL = "https://example.com/support/articles/account-tracking"
SHARP_COPIER_ARTICLE_URL = "https://example.com/support/articles/sharp-copiers"

# Help desk contact info shown in the queue selection dialog
HELP_DESK_MESSAGE = (
    "For assistance, please contact your Help Desk."
)

# Message appended to all confirmation dialogs
ASSISTANCE_MESSAGE = (
    "  \n\nIf you encounter any issues, please "
    "[open a service ticket](" + SUPPORT_TICKET_URL + ")."
)

###############################################################################
# End of configuration
###############################################################################

queue_definitions = {}

###############################################################################
# Parsing and Logic Functions (no side effects, testable directly)
###############################################################################


def parse_lpstat_output(lpstat_text):
    """Parse lpstat -p output and return a list of printer queue names."""
    queues = []
    if not lpstat_text:
        return queues
    for line in lpstat_text.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] == 'printer':
            queues.append(parts[1])
    return queues


def build_lpadmin_command(display_name, location, uri, driver_path, user_number_option=None, options_str=None):
    """Build the lpadmin command list from queue parameters."""
    cmd = ['/usr/sbin/lpadmin',
           '-p', display_name,
           '-L', location,
           '-E',
           '-v', uri,
           '-P', driver_path,
           '-o', 'printer-is-shared=false',
           ]
    if user_number_option:
        cmd += ['-o', user_number_option]
    if options_str:
        options_list = options_str.split()
        for option in options_list:
            cmd.extend(['-o', option])
    return cmd


def parse_dialog_select(output_text, select_title="Select a Printer:"):
    """Parse SwiftDialog select output and return the selected value."""
    if not output_text:
        return None
    lines = output_text.split("\n")
    search_key = '"' + select_title + '" :'
    for line in lines:
        if search_key in line:
            parts = line.split(search_key + " ", 1)
            if len(parts) < 2:
                continue
            selected = parts[1].replace('"', '').strip()
            if selected:
                return selected
    return None


def parse_dialog_textfield(output_text):
    """Parse SwiftDialog textfield output and return the entered value."""
    if not output_text:
        return None
    try:
        label, value = output_text.split(" : ", 1)
        return value.strip()
    except ValueError:
        return None


def parse_csv_to_queue_definitions(csv_text):
    """Parse CSV text into a queue_definitions dictionary."""
    definitions = {}
    reader = csv.DictReader(csv_text)
    for row in reader:
        queue_name = row['DisplayName']
        definitions[queue_name] = {
            'DisplayName': row['DisplayName'],
            'Driver': row['Driver'],
            'URI': row['URI'],
            'DriverTrigger': row['DriverTrigger'],
            'Location': row['Location'],
            'Options': row.get('Options', '').strip()
        }
    return definitions


###############################################################################
# Program Logic
###############################################################################


class Logger(object):
    """Super simple logging class"""
    @classmethod
    def log(self, message, log_level=syslog.LOG_ALERT):
        """Log to the syslog and stdout"""
        syslog.syslog(log_level, "PRINTMAPPER: " + message)
        print(message)


# Initialize Logger
Logger = Logger()

try:
    import requests
except ImportError:
    Logger.log("Installing requests library")
    subprocess.run([sys.executable, "-m", "pip", "install", "requests"], check=True)

    try:
        import requests
    except ImportError:
        Logger.log("Failed to install the requests library, exiting")
        exit(1)

def get_current_user():
    try:
        result = subprocess.check_output(['/usr/bin/stat', '-f%Su', '/dev/console'])
        return result.decode('utf-8').strip()
    except subprocess.CalledProcessError as e:
        Logger.log("An error occurred getting the username: {}".format(e))
        exit(1)

def read_user_number(username):
    directory_path = f"/Users/{username}/Library/PrinterInstaller"
    file_path = os.path.join(directory_path, "usernumber")

    # Check if the file already exists and read the previous user number if so
    file_user_number = None
    if os.path.exists(file_path):
        print(f"Reading path {file_path}")
        with open(file_path, 'r') as file:
            file_user_number = file.read().strip()
            if file_user_number.isdigit() and len(file_user_number) == COPY_CODE_LENGTH:
                print(f"User number from file: {file_user_number}")
                return file_user_number
            else:
                print(f"Warning: Invalid user number found in {file_path}. Ignoring the saved value.")
    return None


def save_user_number(username, new_user_number):
    directory_path = f"/Users/{username}/Library/PrinterInstaller"
    file_path = os.path.join(directory_path, "usernumber")

    try:
        if not os.path.exists(directory_path):
            os.makedirs(directory_path)
            print(f"Created path {directory_path}")

        with open(file_path, 'w') as file:
            file.write(str(new_user_number))
            print(f"New user number saved to file: {new_user_number}")
        os.chmod(file_path, 0o644)

        uid = pwd.getpwnam(username).pw_uid
        gid = pwd.getpwnam(username).pw_gid
        os.chown(file_path, uid, gid)
    except (OSError, KeyError) as e:
        Logger.log(f"Failed to save user number for {username}: {e}")

def run_jamf_policy(trigger, quiet=False):
    """Runs a jamf policy given the provided trigger"""
    if not quiet:
        # Open SwiftDialog progress bar and run it in the background
        progress_bar = subprocess.Popen([SDPATH, '-p', '--title', 'Please wait...',
                                         '--text', 'Installing software...',
                                         '--progress', '1'],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)

    jamf_policy = subprocess.Popen([JAMF, 'policy', '-event', trigger],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

    policy_return, error = jamf_policy.communicate()

    if not quiet:
        # Close the progress bar
        progress_bar.terminate()

    policy_return_str = policy_return.decode("utf-8")

    if "No policies were found for the" in policy_return_str:
        Logger.log("Unable to run JAMF policy via trigger " + trigger)
        return False
    elif "Submitting log to" in policy_return_str:
        Logger.log("Successfully ran JAMF policy via trigger " + trigger)
        return True
    else:
        Logger.log("Unexpected JAMF policy output for trigger " + trigger + ": " + policy_return_str[:200])
        return False

def check_for_swiftdialog():
    """
    Checks for the existence of SwiftDialog at both specified paths.
    Runs 'InstallSwiftDialog' policy trigger if any or both are missing.
    """
    if not os.path.exists(SDPATH) or not os.path.exists(SD_APP_PATH):
        return run_jamf_policy("InstallSwiftDialog", True)
    else:
        return True

check_for_swiftdialog()

def get_printer_list():
    try:
        response = requests.get(GOOGLE_SHEET_URL, timeout=30)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        Logger.log("Timed out downloading printer list from Google Sheets")
        show_message("Unable to download the printer list - the request timed out. Please check your network connection and try again.")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        Logger.log(f"Failed to download printer list: {e}")
        show_message("Unable to download the printer list. Please check your network connection and try again.")
        sys.exit(1)

    csv_text = response.text.splitlines()
    if len(csv_text) < 2:
        Logger.log("Printer list CSV appears empty or malformed")
        show_message("The printer list could not be loaded. Please contact your support team for assistance.")
        sys.exit(1)

    queue_definitions.update(parse_csv_to_queue_definitions(csv_text))

def parse_args():
    """Set up argument parser"""
    parser = argparse.ArgumentParser(
        description=("Maps or 'installs' a printer queue after displaying "
                     "a list of available printer queues to the user. "
                     "Can specify a preselected_queue as argument 4, a filter "
                     "key as argument 5, and a filter value as arugment 6.")
    )
    parser.add_argument("jamf_mount", type=str, nargs='?',
                        help="JAMF-passed target drive mount point")
    parser.add_argument("jamf_hostname", type=str, nargs='?',
                        help="JAMF-passed computer hostname")
    parser.add_argument("jamf_user", type=str, nargs='?',
                        help="JAMF-passed name of user running policy")
    parser.add_argument("preselected_queue", type=str, nargs='?',
                        help="DisplayName of an available queue to map "
                             "without prompting user for selection")
    parser.add_argument("filter_key", type=str, nargs='?',
                        help="Field name of an attribute which you would "
                             "like to filter the available queues base upon")
    parser.add_argument("filter_value", type=str, nargs='?',
                        help="Value to search the provided filter_key "
                             "attribute for")

    return parser


def show_message(message_text, heading="Printer Installer", icon_path=BRANDICON):
    """Displays a message to the user via SwiftDialog"""
    command = [SDPATH, '--title', heading, '--message', message_text, '--icon', icon_path]
    showit = subprocess.Popen(command)
    message_return, error = showit.communicate()
    return True


def get_currently_mapped_queues():
    """Return a list of print queues currently mapped on the system"""
    try:
        Logger.log('Gathering list of currently mapped queues')
        lpstat_result = subprocess.check_output(['/usr/bin/lpstat', '-p']).decode('utf-8')
    except subprocess.CalledProcessError as e:
        Logger.log('No current print queues found')
        lpstat_result = None
    current_queues = parse_lpstat_output(lpstat_result)
    for q in current_queues:
        Logger.log(f'Found mapped queue: {q}')
    Logger.log(f'Total queues found: {len(current_queues)}')
    return current_queues


def build_printer_queue_list(current_queues, filter_key, filter_value):
    """Builds a list of available print queues for GUI presentation"""
    display_list = []
    for queue, values in list(queue_definitions.items()):

        valid_queue = False
        if not values['DisplayName'] in current_queues:
            # If the CUPSName field is present check for its value among
            # mapped queues
            if 'CUPSName' in values:
                if values['CUPSName'] not in current_queues:
                    valid_queue = True
            else:
                valid_queue = True

        if valid_queue:
            # Queue is available but not currently mapped
            if filter_key and filter_value and values.get(filter_key):
                # Filter is applied, and the passed key exists in the queue
                # definitions, so check for match condition
                if values[filter_key].startswith(filter_value):
                    # Match condition met, so add queue to list
                    display_list.append(values['DisplayName'])
                # Implicit else of condition not met, do not add queue to list
            elif not filter_key:
                # No filter applied, so just add the queue to the list
                display_list.append(values['DisplayName'])

    if len(display_list) >= 1:
        return sorted(display_list)
    else:
        Logger.log("No currently-unmapped queues are available")
        show_message("All available printer queues are already installed on your Mac. Please contact your support team if you need further assistance.")
        quit()


def prompt_queue(list_of_queues):
    """Prompts the user to select a queue name"""
    Logger.log('Prompting user to select desired queue')

    queue_str = ','.join(list_of_queues)

    queue_dialog = subprocess.Popen([SDPATH, '--selecttitle', 'Select a Printer:',
                                     '--selectvalues', queue_str,
                                     '--messagealignment', 'center',
                                     '--moveable',
                                     '--ontop',
                                     '--title', 'Printer Installer',
                                     '--message', 'none',
                                     '--button1text', 'Add',
                                     '--button2text', 'Cancel',
                                     '--centericon',
                                     '--icon', BRANDICON,
                                     '--iconsize', '300',
                                     '--helpmessage', HELP_DESK_MESSAGE],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)

    prompt_return, error = queue_dialog.communicate()
    prompt_return = prompt_return.decode('utf-8')

    # Check the exit code of the subprocess
    if queue_dialog.returncode == 2:
        Logger.log('User canceled queue selection')
        return False
    else:
        selected_queue = parse_dialog_select(prompt_return)
        if selected_queue:
            Logger.log('User selected queue ' + selected_queue)
            return selected_queue

        Logger.log('No queue was selected')
        return False


def install_drivers(trigger):
    """Attempts to install drivers via a JAMF policy specified by trigger"""
    Logger.log(f"Running JAMF policy for trigger: {trigger}")

    try:
        result = subprocess.run([JAMF, 'policy', '-event', trigger],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                check=True)

        # Log the output of the command
        Logger.log(f"JAMF policy output: {result.stdout.decode('utf-8')}")

        # The command succeeded, so return True
        return True

    except subprocess.CalledProcessError as e:
        # The command failed (non-zero exit code), log the error and return False
        Logger.log(f"JAMF policy failed: {e.output.decode('utf-8')}")
        return False

def search_for_driver(driver, trigger):
    """Searches the system for the appropriate driver and if not found,
       attempts to install it via JAMF policy"""
    if not os.path.exists(driver):
        Logger.log("The driver was not found at " + driver)
        if not trigger:
            Logger.log("No driver trigger configured for this printer")
            show_message("A driver is required for this printer, but no install trigger is configured. Please contact your support team for assistance.")
            Logger.log('Quitting program')
            quit()
        if not install_drivers(trigger):
            show_message("A driver is required for full control of this printer, but an error occurred when attempting to install the software. Please contact your support team for assistance.")
            Logger.log('Quitting program')
            quit()

def add_queue(queue):
    # Reference the queue dictionary by name
    q = queue_definitions[queue]

    # Define the path to the generic PPD for a clear and reliable check.
    generic_ppd_path = "/System/Library/Frameworks/ApplicationServices.framework/Versions/A/Frameworks/PrintCore.framework/Versions/A/Resources/Generic.ppd"

    # This logic correctly identifies generic vs. vendor drivers
    if q['Driver'] and 'Generic.ppd' not in q['Driver']:
        Logger.log("Queue " + q['DisplayName'] + " requires a vendor driver")
        search_for_driver(q['Driver'], q['DriverTrigger'])
        q_driver = q['Driver']
    else:
        Logger.log(q['DisplayName'] + " uses a generic driver")
        # Ensure we use the canonical path to the generic driver.
        q_driver = generic_ppd_path

    user_number = None
    if COPY_CODE_ENABLED and COPY_CODE_DRIVER_KEYWORD in q['Driver']:
        while True:  # Loop to keep prompting until valid input is received
            user_number_command = [
                SDPATH,
                '--title', COPY_CODE_DIALOG_TITLE,
                '--message', COPY_CODE_PROMPT,
                '--textfield', '',
                '--button1text', 'Submit',
                '--button2text', 'Cancel',
                '--icon', BRANDICON,
                '--iconsize', '300',
                '--image', COPY_CODE_IMAGE,
                '--imagesize', '600',
                '--width', '650',
                '--height', '450',
                '--style', 'alert',
                '--ontop',
                '--big',
                '--messagealignment', 'left',
                '--messageposition', 'top',
            ]
            user_number_dialog = subprocess.Popen(
                user_number_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            user_number_return, error = user_number_dialog.communicate()

            # If the user presses cancel, return to printer selection
            if user_number_dialog.returncode == 2:
                return 1

            user_number_return = user_number_return.decode('utf8')

            copy_code = parse_dialog_textfield(user_number_return)

            if copy_code and copy_code.isdigit() and len(copy_code) == COPY_CODE_LENGTH:
                user_number = copy_code
                user_number_option = 'ARUserNumber=Custom.' + user_number
                print(f"User number inputted: {user_number}")
                break
            else:
                error_message = f"Invalid input. Please enter exactly {COPY_CODE_LENGTH} numeric digits."
                show_message(error_message, "Error")
    else:
        user_number_option = None

    if q['Options']:
        Logger.log(f"Applying custom options from sheet: {q['Options']}")

    cmd = build_lpadmin_command(
        q['DisplayName'], q['Location'], q['URI'], q_driver,
        user_number_option, q['Options'] if q['Options'] else None
    )

    Logger.log("Executing command: " + ' '.join(cmd))
    mapq = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            shell=False)
    map_return, map_error = mapq.communicate()

    if mapq.returncode != 0:
        error_text = map_error.decode('utf-8', errors='replace').strip()
        Logger.log(f"lpadmin failed with exit code {mapq.returncode}")
        if error_text:
            Logger.log(f"lpadmin stderr: {error_text}")
        Logger.log('Attempted command: ' + ' '.join(cmd))
        show_message("There was a problem mapping the printer queue - please try again. If the problem persists, contact your support team for further assistance.")
        return 1

    Logger.log("Queue " + q['DisplayName'] + " successfully mapped")

    # Restart CUPS and save user number for SHARP printers (after lpadmin)
    if user_number_option:
        subprocess.run(["launchctl", "stop", "org.cups.cupsd"],
                        check=False)
        subprocess.run(["launchctl", "start", "org.cups.cupsd"],
                        check=False)

        current_user = get_current_user()
        if read_user_number(current_user) == user_number:
            print("User numbers match from file")
        else:
            save_user_number(current_user, user_number)

    confirmation_title = "Success!"
    confirmation_message = f"The printer {q['DisplayName']} was successfully added." + ASSISTANCE_MESSAGE

    # For Konicas - account tracking requires manual setup
    if q['DriverTrigger'] == 'konica_drivers':
        confirmation_title = "Notice"
        confirmation_message = f"The Konica copier {q['DisplayName']} has been installed.  \n\nFor account tracking setup, [see this solutions article](" + ACCOUNT_TRACK_ARTICLE_URL + ")." + ASSISTANCE_MESSAGE

    elif COPY_CODE_DRIVER_KEYWORD in q['Driver'] and user_number:
        confirmation_message = f"The SHARP copier {q['DisplayName']} has been installed.  \n\nYour copy code / user number is:  \n**{user_number}**.  \n\n*This code will be needed for making copies*.  \n\n\n For troubleshooting steps [click here](" + SHARP_COPIER_ARTICLE_URL + ")" + ASSISTANCE_MESSAGE

    elif COPY_CODE_DRIVER_KEYWORD in q['Driver']:
        confirmation_message = f"The SHARP copier {q['DisplayName']} has been installed.  \n\nFor troubleshooting steps [click here](" + SHARP_COPIER_ARTICLE_URL + ")" + ASSISTANCE_MESSAGE

    # For HP Printers
    elif '/hp ' in q['Driver'] or '/HP ' in q['Driver']:
        confirmation_message = f"The HP Printer {q['DisplayName']} has been installed." + ASSISTANCE_MESSAGE

    confirmation_prompt = [SDPATH,
                       '--message', confirmation_message,
                       '--title', confirmation_title,
                       '--button1text', 'Finish',
                       '--button2text', 'Add Another Printer'
                       ]
    confirmation_process = subprocess.Popen(confirmation_prompt, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    confirmation_process.communicate()
    if confirmation_process.returncode == 2:
        print("\nUser is adding another printer:")
        return 1
    return 0


def main():
    """Manage arguments and run workflow"""
    get_printer_list()
    # Parse command line / JAMF-passed arguments
    parser = parse_args()
    # parse_known_args() works around potentially empty arguments passed by
    # a JAMF policy
    args = parser.parse_known_args()[0]

    while True:  # Loop to allow adding multiple printers
        # Build list of currently mapped queues on client
        currently_mapped_queues = get_currently_mapped_queues()
        # Build list of available queues excluding currently-mapped queues
        available_queues = build_printer_queue_list(currently_mapped_queues,
                                                args.filter_key,
                                                args.filter_value)
        # Determine if a pre-selected print queue was passed or prompt for queue selection
        if args.preselected_queue and args.preselected_queue in available_queues:
            selected_queue = args.preselected_queue
            args.preselected_queue = None
        else:
            selected_queue = prompt_queue(available_queues)

        if selected_queue and selected_queue in available_queues:
            add_another_printer = add_queue(selected_queue)
            if add_another_printer == 0:
                break
        else:
            print("No selection was made")
            break



if __name__ == '__main__':
    main()
