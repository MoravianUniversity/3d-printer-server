"""Serves GCODE, JSON, and OBJ versions of the currently printing model."""

import os.path

from tornado.web import StaticFileHandler, HTTPError
from async_util import run_async

from printers import PrinterHandlerMixin, get_printer
from model.gcode_parser import gcode_to_json, gcode_to_obj

CWD = os.path.dirname(os.path.abspath(__file__))


_BOOL_VALS = {
    'y': True, 'yes': True,
    'n': False, 'no': False,
    't': True, 'true': True,
    'f': False, 'false': False,
    'on': True, 'off': False,
    '1': True, '0': False,
}

def strtobool(value):
    try:
        return _BOOL_VALS[str(value).lower()]
    except KeyError:
        return ValueError(f'"{value}" is not a valid bool value')


class ModelHandler(StaticFileHandler, PrinterHandlerMixin):  # pylint: disable=abstract-method
    """
    Gets gcode files from the printer along with converting gcode files to
    either json or obj files.
    """
    async def get(self, name_with_ext):  # pylint: disable=arguments-differ
        # Get the arguments
        try: infill = strtobool(self.get_argument('infill', None))
        except (ValueError, AttributeError): infill = None
        try: support = strtobool(self.get_argument('support', 'false'))
        except (ValueError, AttributeError): support = False

        filename = await run_async(generate_model,
            name_with_ext, self.settings["config"], infill, support)

        # Return the file itself
        return await super().get(filename)


def generate_model(name_with_ext, config, infill=None, support=False):
    name, ext = name_with_ext.rsplit('.', 1)

    # Get the printer's information
    printer = get_printer(name, config)
    if not printer.supports_gcode: raise HTTPError(400)

    # Get the gcode
    gcode_path = os.path.join(CWD, name) + '.gcode'
    updated = update_gcode(printer, gcode_path)
    if not os.path.isfile(gcode_path): raise HTTPError(404)
    if ext == 'gcode': return name_with_ext

    # Update the output file
    return update_output(printer, updated, gcode_path, name, ext, infill, support)


def update_gcode(printer, path):
    """
    Ensure that we have an up-to-date gcode file at that path. If not
    already up-to-date, downloads it from the remote source and writes
    to the path.

    This blocks, should be used with an executor.
    """
    if printer.is_up_to_date(path): return False

    # Download the current gcode and save the file
    gcode = printer.gcode
    with open(path, "w") as f: f.write(gcode)
    return True


def update_output(printer, updated, gcode_path, name, ext, infill=None, support=False):
    """
    Ensure that the output (json or obj) is updated. Recreates it from the
    gcode if necessary.

    This blocks, should be used with an executor.
    """
    # Get the output file type
    func = gcode_to_json if ext == 'json' else gcode_to_obj

    # Auto-pick infill as True if file is less than 10 MiB
    if infill is None: infill = os.path.getsize(gcode_path) < 10485760

    # Compute the output name
    if not infill: name += '_no_infill'
    if support: name += '_support'
    name += '.' + ext
    output_path = os.path.join(CWD, name)

    if updated or not printer.is_up_to_date(output_path):
        # Convert and save the file
        with open(gcode_path) as gcode, open(output_path, "w") as f:
            func(gcode, out=f,
                 ignore_infill=not infill, ignore_support=not support)

    return name
