#!/usr/bin/env python3

import os, sys, platform, datetime, json, argparse, re
from ultimaker import Ultimaker, Material, HistoryEventTypeId, MaintenanceAction
from getpass import getuser
from enum import Enum

########## argparse type checkers ##########
def num_in_range(mn, mx, type_=int):
    def _num_in_range(value):
        try: val = type_(value)
        except (ValueError, TypeError): raise argparse.ArgumentTypeError("invalid value")
        if mn <= val <= mx: return val
        raise argparse.ArgumentTypeError("must be %s between %d and %d" % ('an integer' if type_ == int else 'a decimal', mn, mx))
    return _num_in_range
def num_at_least(mn, type_=int):
    def _num_at_least(value):
        try: val = type_(value)
        except (ValueError, TypeError): raise argparse.ArgumentTypeError("invalid value")
        if mn <= val: return val
        raise argparse.ArgumentTypeError("must be %s be at least %d" % ('an integer' if type_ == int else 'a decimal', mn))
    return _num_at_least

def csvs(*types):
    def _csvs(value):
        values = value.split(',')
        if len(values) != len(types): raise argparse.ArgumentTypeError("must have %d values seperated by commas" % len(types))
        try:
            return [type_(val) for type_,val in zip(types, values)]
        except (ValueError, TypeError):
            raise argparse.ArgumentTypeError("invalid value")
    return _csvs

def gcode_file(value):
    if not (value.endswith('.gcode') or value.endswith('.gcode.gz') or value.endswith('.ufp')):
        raise argparse.ArgumentTypeError("filename must have the extension .gcode, .gcode.gz, or .ufp")
    if value[0] == '-': return (os.path.basename(value[1:]), sys.stdin)
    if not os.path.isfile(value): raise argparse.ArgumentTypeError("must be a file")
    return (os.path.basename(value), open(value, 'rb'))
    
def valid_sys_name(value):
    if 1 <= len(value) <= 64 and all(c in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' for c in value): return value
    raise argparse.ArgumentTypeError("must be 1 to 63 letters and/or digits")
def valid_country(value):
    if (len(value) == 0 or len(value) == 2) and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in value): return value
    raise argparse.ArgumentTypeError("must be 0 or 2 uppercase letters")

def uuid(value):
    if re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', value) is None:
        raise argparse.ArgumentTypeError("not a valid UUID value")
    return value

def is_pos_float(value):
    if value.isdigit(): return True
    parts = value.split('.')
    return len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()
def time(value):
    # Accepts:
    #   integers for seconds
    #   integer/float followed by 's', 'm', or 'h' for seconds, minutes, or hours
    #   integers seperated with : for minutes:seconds or hours:minutes:seconds
    if value.isdigit(): return int(value)
    if len(value) < 2: raise argparse.ArgumentTypeError("not a valid time value")
    if value[-1] in 'smh' and is_pos_float(value[:-1]):
        t = float(value[:-1])
        if value[-1] == 'm': t *= 60
        elif value[-1] == 'h': t *= 60*60
        return t
    parts = value.split(':')
    if len(parts) not in (2,3) or any(not t.isdigit() for t in parts): raise argparse.ArgumentTypeError("not a valid time value")
    return int(parts[-1]) + int(parts[-2])*60 + (int(parts[0])*60*60 if len(parts) == 3 else 0)

def history_event_type_id(value):
    if value.isdigit(): return int(value)
    return HistoryEventTypeId[value.upper()]
def maintenance_action(value):
    return MaintenanceAction(value)

########## printing helpers ##########
# JSON printer
def json_serial(obj):
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if isinstance(obj, datetime.timedelta):
        return obj.total_seconds()
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError("type %s not serializable" % type(obj))
def print_json(x, columns=None): # pylint: disable=unused-argument
    print(json.dumps(x, default=json_serial))

# String printer (plain)
def print_str_plain(info): print(printable_val(info))

# Dictionary printer (plain)
def print_dict_plain(info, indent=0, min_width=0):
    if len(info) == 0: return
    if isinstance(info, list): info = {i:v for i,v in enumerate(info)} # treat a list as a dictionary with integer keys
    width = max(min_width, max(len(str(key)) for key in info)) + 1 # for colon
    frmt = ' '*indent + '%-'+str(width)+'s %s'
    for k,v in info.items():
        if isinstance(v, (dict, list)):
            print(frmt%(str(k)+':',''))
            print_dict_plain(v, indent + 2, width - 1)
        else: print(frmt%(str(k)+':',printable_val(v)))
def printable_val(x): return x.value if isinstance(x, Enum) else x
def printable_name(x): return x.name if isinstance(x, Enum) else x

# List printer (plain)
def print_list_plain(info):
    for line in info: print(line)

# Table printers (plain and CSV)
def print_table_plain(info, columns=None):
    if not info: return
    info, columns = list_of_dict_to_list_of_list(info, columns)
    n = len(columns)
    types = []
    for i in range(n):
        if all(isinstance(line[i], int) or isinstance(line[i], float) for line in info):
            types.append('d' if all(isinstance(line[i], int) or line[i].is_integer() for line in info) else '.1f')
        else: types.append('s')
    widths = [max(len(columns[i]), max(len(('%'+types[i])%printable_name(line[i])) for line in info)) for i in range(n)]
    print(' '.join((('%-'+str(width)+'s')%col) for col,width in zip(columns,widths)))
    formats = [(('%-' if typ == 's' else '%')+str(width)+typ) for typ,width in zip(types,widths)]
    for line in info: print(' '.join(format%printable_name(val) for val,format in zip(line,formats)))
def list_of_dict_to_list_of_list(info, columns=None):
    if not info: return None, []
    list_of_dict = isinstance(info[0], dict)
    if columns is None: columns = list(info[0].keys()) if list_of_dict else info.pop(0)
    if list_of_dict: info = [[line[col] for col in columns] for line in info]
    return info, columns
def print_csv(info, columns=None):
    if not info: return
    info, columns = list_of_dict_to_list_of_list(info, columns)
    print(','.join(csv_quote(col) for col in columns))
    for line in info: print(','.join(csv_quote(val) for val in line))
def csv_quote(x):
    if isinstance(x, float) and x.is_integer(): x = int(x)
    s = str(x)
    return ('"'+s.replace('"', '""')+'"') if ',' in s or '\n' in s or '"' in s else s


def main():
    parser = argparse.ArgumentParser(description='Control the Ultimaker printer')
    parser.add_argument('hostname', help='the hostname or IP address of the Ultimaker printer')
    parser.add_argument('--id', help='the authentication id (username) to use', default=None)
    parser.add_argument('--key', help='the authentication key (password) to use', default=None)
    parser.add_argument('--json', action='store_true', help='output information in JSON format if applicable')
    cmds = parser.add_subparsers(dest='cmd', help='the command to run', required=True)
    
    ##### Authorization #####
    auth = cmds.add_parser('auth', description='Deal with authentication with the device')
    auth = auth.add_subparsers(dest='auth_cmd', help='the authorization command', required=True)
    auth.add_parser('verify', description='Verify that you are authorized (either with stored credentials or given with --id and --key)')
    auth.add_parser('store', description='Store the given credentials for future use from the command line for the given hostname')
    auth.add_parser('view', description='View the credntials stored for use from the command line for the given hostname')
    acquire = auth.add_parser('acquire', description='Acqurie a new id and key for authorization of the given machine. Usually this happens automatically as needed but you may want to do it in case the old authorization is no longer valid, won\'t have physical access to the machine, or want to get an id and key for another program.')
    acquire.add_argument('application', nargs='?', default='ultimaker-py-api', help='application name to authorize, default is ultimaker-py-api')
    acquire.add_argument('user', nargs='?', default=getuser(), help='user name to authorize, default is '+getuser())
    acquire.add_argument('host_name', nargs='?', default=platform.node(), help='hostname to authorize, default is '+platform.node())
    acquire.add_argument('exclusion_key', nargs='?', default=None, help='Old key to make sure only one authorisation will exist on the remote printer with this same key, automatically de-authenticating the old one')
    acquire.add_argument('--no-store', action='store_true', help='if provided will not automatically store the new credentials')

    ##### Materials #####
    materials = cmds.add_parser('materials', description='View or edit the materials known by the printer')
    materials.add_argument('guid', type=uuid, nargs='?', default=None, help='onyl show the material with this GUID, default is to show all')
    materials.add_argument('--xml', action='store_true', help='output materials in XML format')
    materials.add_argument('--brand', default=None, help='filter materials by brand')
    materials.add_argument('--type', default=None, help='filter materials by type')
    materials.add_argument('--color', default=None, help='filter materials by color')

    materials = materials.add_subparsers(dest='materials_cmd', help='the materials command')
    materials.add_parser('guids', description='List all material GUIDs')

    put = materials.add_parser('put', description='Put a material, either updating it or adding it')
    put.add_argument('xml_file', type=argparse.FileType(), help='XML file that defines the material, use - for stdin')
    put.add_argument('sig_file', type=argparse.FileType(), nargs='?', default=None, help='optional signature file to use for the material')
    
    delete = materials.add_parser('delete', description='Delete a material (note that this doesn\'t actually work in most cases)')
    delete.add_argument('guid', type=uuid, help='the GUID of the material to delete')

    ##### Printer #####
    printer = cmds.add_parser('printer', description='Interact with the printer')
    printer = printer.add_subparsers(dest='printer_cmd', help='the printer command to run')

    printer.add_parser('status', description='Display the printer status')

    bed = printer.add_parser('bed', description='Interact with the print bed')
    bed_cmd = bed.add_subparsers(dest='bed_cmd', help='the bed command to run')

    bed_temp = bed_cmd.add_parser('temp', description='Interact with temperature of the print bed')
    bed_temp.add_argument('target', type=num_in_range(0,115,float), nargs='?', default=None, help='target bed temperature (0°C to 115°C)')
    
    pre_heat = bed_cmd.add_parser('pre-heat', description='Pre-heat the print bed, resetting if no print started within a given timeout')
    pre_heat.add_argument('temperature', type=num_in_range(0,115,float), nargs='?', default=None, help='target bed temperature (0°C to 115°C, values less than 20°C will cancel pre-heating)')
    pre_heat.add_argument('timeout', type=num_in_range(60,3600,time), nargs='?', default=300, help='timeout of pre-heated bed (60 to 3600 seconds, can enter values with s, m, or h suffix or as h:m:s or m:s, default 5 min)')

    head = printer.add_parser('head', description='Interact with the print head')
    head.add_argument('head', type=num_at_least(0), nargs='?', default=0, help='print head to interact with (default is 0)')
    head = head.add_subparsers(dest='head_cmd', help='the head command to run')

    class XYZAction(argparse.Action):
        def __init__(self, option_strings, dest, required=None, nargs=None, **kwargs):
            super().__init__(option_strings, dest, required=False, nargs=3, **kwargs)
            self.metavar = '[x y z]'
        def __call__(self, parser, namespace, values, option_string=None):
            values = [int(values[0]), int(values[1]), int(values[2])]
            setattr(namespace, self.dest, values)

    pos = head.add_parser('position')
    pos.add_argument('xyz', action=XYZAction)
    pos.add_argument('--no-check', action='store_true', help='the command line won\'t check the validity of the position based on the machine type')
    
    extruder = head.add_parser('extruder', description='Interact with an extruder')
    extruder.add_argument('extruder', type=num_at_least(0), help='extruder to interact with')
    extruder.add_argument('target', type=num_in_range(0,350,float), nargs='?', default=None, help='set target bed temperature (0°C to 350°C)')

    led = printer.add_parser('led', description='Interact with the frame LEDs')
    led = led.add_subparsers(dest='led_cmd', help='the led command to run')

    ledset = led.add_parser('set', description='Set the frame LEDs')
    ledset.add_argument('hue', type=num_in_range(0,360,float), help='LED hue (0 to 360)')
    ledset.add_argument('saturation', type=num_in_range(0,100,float), help='LED saturation (0 to 100)')
    ledset.add_argument('brightness', type=num_in_range(0,100,float), help='LED brightness (0 to 100)')

    blink = led.add_parser('blink', description='Blink the frame LEDs')
    blink.add_argument('frequency', type=num_at_least(1, float), nargs='?', default=1, help='frequency of blinking (>0 Hz, default 1 Hz)')
    blink.add_argument('count', type=num_at_least(1), nargs='?', default=1, help='number of blinks (>0, default once)')

    beep = printer.add_parser('beep', description='Emit an audible tone')
    beep.add_argument('frequency', type=num_in_range(440, 22000), help='frequency of the beep in Hz')
    beep.add_argument('duration', type=num_in_range(10, 5000), help='duration of the beep in miliseconds')

    network = printer.add_parser('network', description='Interact with the network')
    network = network.add_subparsers(dest='network_cmd', help='the network command to run')
    
    connect = network.add_parser('connect', description='Connect to a wifi network')
    connect.add_argument('ssid', help='wifi SSID to connect to')
    connect.add_argument('passphrase', nargs='?', default=None, help='wifi passphrase is needed')

    forget = network.add_parser('forget', description='Forget a wifi network')
    forget.add_argument('ssid', help='wifi SSID to forget')

    ##### Print Job #####
    print_job = cmds.add_parser('print_job', description='Interact with the current print job or submit a new print job')
    print_job = print_job.add_subparsers(dest='print_job_cmd', help='the print job command to run')

    submit = print_job.add_parser('submit', description='Submit a gcode file to be printed')
    submit.add_argument('file', type=gcode_file, help='.gcode, .gcode.gz, or .ufp file to be printed, can be prefixed with - to read from standard in but must still include a (fake) filename after that')
    submit.add_argument('name', nargs='?', default=None, help='name of the print job')

    validate = print_job.add_parser('validate', description='Validate that a gcode file can be printed')
    validate.add_argument('file', type=gcode_file, help='.gcode, .gcode.gz, or .ufp file to be validated, can be prefixed with - to read from standard in but must still include a (fake) filename after that')

    print_job.add_parser('pause', description='Pause the current print job')
    print_job.add_parser('resume', description='Resume the current print job')
    print_job.add_parser('abort', description='Abort the current print job')

    download = print_job.add_parser('download', description='Download the current printing gcode')
    download.add_argument('--container', action='store_true', help='Download the container file instead of the gcode if available')

    ##### History #####
    history = cmds.add_parser('history', description='View historical print jobs and events')
    history = history.add_subparsers(dest='history_cmd', help='the historical information to view', required=True)
    
    hpj = history.add_parser('print_job', description='View information about a previous print job')
    hpj.add_argument('uuid', type=uuid, help='the uuid of the print job to view information about')

    hpjs = history.add_parser('print_jobs', description='View information about previous print jobs')
    hpjs.add_argument('offset', type=num_at_least(0), nargs='?', default=0, help='the offset to start viewing print jobs from')
    hpjs.add_argument('count', type=num_at_least(1), nargs='?', default=50, help='the number of print jobs to view')
    hpjs.add_argument('--csv', action='store_true', help='output as csv')

    events = history.add_parser('events', description='View information about events on the printer')
    events.add_argument('offset', type=num_at_least(0), nargs='?', default=0, help='the offset to start viewing events from')
    events.add_argument('count', type=num_at_least(1), nargs='?', default=50, help='the number of events to view')
    events.add_argument('--type', type=history_event_type_id, default=None, help='only show events with a matching type id')
    events.add_argument('--csv', action='store_true', help='output as csv')

    ##### Maintence #####
    maintenance = cmds.add_parser('maintenance', description='View prior maintance and record new maintenance events')
    maintenance.add_argument('action', type=maintenance_action, nargs='?', default=None, help='the action completed, one of '+', '.join(MaintenanceAction.__members__.keys()))
    maintenance.add_argument('mechanic', nargs='?', default=None, help='the person who completed the action')

    ##### Diagnostics #####
    diagnostics = cmds.add_parser('diagnostics', description='Run diagnostics on the printer')
    diagnostics = diagnostics.add_subparsers(dest='diag_cmd', help='the system command to run', required=True)
    
    csn = diagnostics.add_parser('cap_sensor_noise', description='Calculate noise variances on the cap sensor')
    csn.add_argument('loops', type=num_at_least(1), nargs='?', default=100, help='the number of loop iterations')
    csn.add_argument('samples', type=num_at_least(1), nargs='?', default=50, help='the number of samples per iteration')

    tf = diagnostics.add_parser('temperature_flow', description='Get historical temperature & flow data')
    tf.add_argument('samples', type=num_at_least(1), help='the number of samples to retrieve')
    tf.add_argument('--csv', action='store_true', help='output as csv')

    diagnostics.add_parser('probing_report', description='Get probing data, always output as JSON')

    ##### System #####
    system = cmds.add_parser('system', description='Interact with the system')
    system = system.add_subparsers(dest='system_cmd', help='the system command to run')

    display = system.add_parser('display', description='Display a message on the printer\'s LCD screen')
    display.add_argument('message', help='the message to display')
    display.add_argument('caption', nargs='?', default='Ok', help='the caption to display for the confirm button (default \'Ok\')')

    log = system.add_parser('log', description='Display system log')
    log.add_argument('count', type=num_at_least(1), nargs='?', default=50, help='the number of log entries to retrieve')
    log.add_argument('--prev', action='store_true', help='get log from previous boot')

    name = system.add_parser('name', description='Display or set the name of the system')
    name.add_argument('value', type=valid_sys_name, nargs='?', default=None, help='the new name of the system, 1-63 letters or digits')

    country = system.add_parser('country', description='Display or set the country of the system')
    country.add_argument('value', type=valid_country, nargs='?', default=None, help='the new country for the system, used to determine wifi bands to use; either an empty string or 2 uppercase letters')

    firmware = system.add_parser('firmware', description='Display the current firmware or update the firmware')
    firmware.add_argument('--update', action='store_true', help='update the firmware on the device')
    firmware.add_argument('--testing', action='store_true', help='display/update the testing version of the firmware')
    
    ##### Camera #####
    cmds.add_parser('camera', description='Get the camera stream URL')


    # Prepare for running commands
    args = parser.parse_args()
    print_str = print_str_plain
    print_dict = print_dict_plain
    print_list = print_list_plain
    print_table = print_table_plain
    if args.json:
        print_str = print_json
        print_dict = print_json
        print_list = print_json
        print_table = print_json
    if 'csv' in args and args.csv:
        print_table = print_csv
    
    if (args.id is None) != (args.key is None):
        args.error('Both --id and --key must provided if either is provdied')

    ultimaker = Ultimaker(args.hostname, args.id, args.key)

    ##### Authorization #####
    if args.cmd == 'auth':
        if args.auth_cmd == 'verify':
            if args.id is None and not ultimaker.auth.load(): args.error('no provided or stored credentials')
            if ultimaker.auth.verify(): print_str('verified')
            else: print_str('not verified'); sys.exit(1)
        elif args.auth_cmd == 'store':
            if args.id is None: args.error('most provide credentials to store')
            ultimaker.auth.store()
        elif args.auth_cmd == 'view':
            if not ultimaker.auth.load():
                print_str('no stored credentials')
                sys.exit(1)
            print_dict({'id':ultimaker.id, 'key':ultimaker.key})
        elif args.auth_cmd == 'acquire':
            id_, key = ultimaker.auth.acquire(args.application, args.user, args.host_name, args.exclusion_key)
            print_dict({'id':id_, 'key':key})
            if not args.no_store: ultimaker.auth.store()

    ##### Materials #####
    elif args.cmd == 'materials':
        materials = ultimaker.materials
        if args.materials_cmd is None:
            if args.guid is not None:
                if args.xml: print(materials[args.guid].raw.strip())
                else: print_dict(materials[args.guid].dict)
            elif args.xml and args.brand is None and args.type is None and args.color is None: print(''.join(materials.raw).strip())
            else:
                mats = [m for m in materials.values()
                        if (args.brand is None or m.brand == args.brand) and
                           (args.type is None or m.material == args.type) and
                           (args.color is None or m.color == args.color)]
                if args.xml: print(''.join([m.raw for m in mats]).strip())
                else: print_dict([m.dict for m in mats])
        elif args.materials_cmd == 'guids': print_list(list(materials.keys()))
        elif args.materials_cmd == 'delete': del materials[args.guid]
        elif args.materials_cmd == 'put':
            material = Material(args.xml_file.read())
            if material.guid in materials: materials.update(material, args.sig_file)
            else: materials.add(material, args.sig_file)
    
    ##### Printer #####
    elif args.cmd == 'printer':
        printer = ultimaker.printer
        if args.printer_cmd is None: print_dict(printer.dict)
        elif args.printer_cmd == 'status': print_str(printer.status)
        elif args.printer_cmd == 'led':
            led = printer.led
            if args.led_cmd is None: print_dict(led.dict)
            elif args.led_cmd == 'set': led.set_color(args.hue, args.saturation, args.brightness)
            elif args.led_cmd == 'blink': led.blink(args.frequency, args.count)
        elif args.printer_cmd == 'beep':  printer.beep(args.frequency, args.duration)
        elif args.printer_cmd == 'bed':
            bed = printer.bed
            if args.bed_cmd is None: print_dict(bed.dict)
            elif args.bed_cmd == 'temp':
                if args.target is None: print_dict(bed.temperature.dict)
                else: bed.temperature.target = args.target
            elif args.bed_cmd == 'pre-heat':
                if args.temperature is None: print_dict(bed.pre_heat.dict)
                elif args.temperature < 20: print_str(bed.pre_heat.cancel())
                else: print_str(bed.pre_heat.start(args.temperature, args.timeout))
        elif args.printer_cmd == 'head':
            heads = printer.heads
            if args.head < 0 or args.head >= len(heads): parser.error('there are only %d heads'%len(heads))
            head = printer.heads[args.head]
            if args.head_cmd is None: print_dict(head.dict)
            elif args.head_cmd == 'position':
                if args.xyz is None: print_dict(head.position.dict)
                else:
                    # x goes left to right, y goes front to back, z goes plate up to down
                    if not args.no_check:
                        x, y, z = args.xyz
                        if x < 0 or y < 0 or z < 0: args.error('invalid position')
                        maxes = {
                            'Ultimaker 3': (215, 215, 210),
                            'Ultimaker 3 Extended': (215, 215, 310),
                            'Ultimaker S5': (330, 240, 310),
                        }
                        maxes = maxes.get(ultimaker.system.variant)
                        if maxes is not None and (x > maxes[0] or y > maxes[1] or z > maxes[2]): args.error('invalid position')
                    head.position = args.xyz
            elif args.head_cmd == 'extruder':
                extruders = head.extruders
                if args.extruder < 0 or args.extruder >= len(extruders): parser.error('there are only %d extruders on head %d'%(len(args.extruder),args.head))
                extruder = extruders[args.extruder]
                if args.target is None: print_dict(extruder.dict)
                else: extruder.hotend.temperature.target = args.target
        elif args.printer_cmd == 'network':
            network = printer.network
            if args.network_cmd is None: print_dict(network.dict)
            elif args.network_cmd == 'connect': network.wifi_networks.add(args.ssid, args.passphrase)
            elif args.network_cmd == 'forget':  del network.wifi_networks[args.ssid]

    ##### Print Job #####
    elif args.cmd == 'print_job':
        print_job = ultimaker.print_job
        if args.print_job_cmd is None: print_dict(print_job.dict)
        elif args.print_job_cmd == 'print': print_job.submit(args.file, args.name)
        elif args.print_job_cmd == 'validate':
            issues = ultimaker.printer.validate_header(args.file)
            if args.json: print_json(issues)
            elif issues: print_table(issues, ['level', 'code', 'message', 'data'])
            else: print_str('valid')
            if issues: sys.exit(1)
        elif args.print_job_cmd == 'pause':  print_job.pause()
        elif args.print_job_cmd == 'resume': print_job.resume()
        elif args.print_job_cmd == 'abort':  print_job.abort()
        elif args.print_job_cmd == 'download': print(print_job.container if args.container else print_job.gcode)

    ##### History #####
    elif args.cmd == 'history':
        history = ultimaker.history
        if args.history_cmd == 'print_job': print_dict(history.print_jobs[args.uuid].dict)
        elif args.history_cmd == 'print_jobs': print_table([pj.dict for pj in history.print_jobs[args.offset:args.count]])
        elif args.history_cmd == 'events':
            events = history.events if args.type is None else history.events_by_type(args.type)
            events = [event.dict for event in events[args.offset:args.count]]
            print_table(events)

    ##### Maintenance #####
    elif args.cmd == 'maintenance':
        history = ultimaker.history
        if args.action is None:
            events = list(history.events_by_type(HistoryEventTypeId.SYSTEM_MAINTENANCE))
            last = {}
            for event in events:
                action = event.parameters[0]
                if action not in last or last[action]['time'] < event.time:
                    last[action] = event.dict
            print_dict(last)
        else: history.events.post_maintenance(args.action, args.mechanic)

    ##### Diagnostics #####
    elif args.cmd == 'diagnostics':
        diagnostics = ultimaker.printer.diagnostics
        if   args.diag_cmd == 'cap_sensor_noise': print_dict(diagnostics.cap_sensor_noise(args.loops, args.samples))
        elif args.diag_cmd == 'temperature_flow': print_table(diagnostics.temperature_flow(args.samples))
        elif args.diag_cmd == 'probing_report':   print(diagnostics.probing_report()) # always JSON output

    ##### System #####
    elif args.cmd == 'system':
        system = ultimaker.system
        if args.system_cmd is None: print_dict(system.dict)
        elif args.system_cmd == 'display-msg':
            system.display_message(args.message, args.caption)
        elif args.system_cmd == 'log': print_list(system.log(-1 if args.prev else 0, args.count))
        elif args.system_cmd == 'name':
            if args.value is None: print_str(system.name)
            else: system.name = args.value
        elif args.system_cmd == 'country':
            if args.value is None: print_str(system.country)
            else: system.country = args.value
        elif args.system_cmd == 'firmware':
            if args.update: system.firmware.update(not args.testing)
            else:
                info = {
                    'current': system.firmware.version,
                    'stable': system.firmware.stable,
                    'status': system.firmware.status,
                }
                if args.testing: info['testing'] = system.firmware.testing
                if info['status'] == 'IDLE': del info['status']
                print_dict(info)

    ##### Camera #####
    elif args.cmd == 'camera':
        camera = ultimaker.camera
        print_dict(camera.dict)

if __name__ == "__main__": main()
