#!/usr/bin/env python3

"""Serves GCODE, JSON, and OBJ versions of the currently printing model."""

import os.path
from distutils.util import strtobool

from tornado.web import HTTPError
from tornado.ioloop import IOLoop

from printers import PrinterHandler
from model.gcode_parser import gcode_to_json, gcode_to_obj

CWD = os.path.dirname(os.path.abspath(__file__))


class ModelHandler(PrinterHandler):  # pylint: disable=abstract-method
    """
    Gets gcode files from the printer along with converting gcode files to
    either json or obj files.
    """
    async def get(self, name_ext):  # pylint: disable=arguments-differ
        name, ext = name_ext.rsplit('.', 1)

        # Get the printer's information
        self.printer = self.get_printer(name)
        if not self.printer.supports_gcode: raise HTTPError(400)

        loop = IOLoop.current()

        # Get the gcode
        gcode_path = os.path.join(CWD, name) + '.gcode'
        updated = await loop.run_in_executor(
            None, self.update_gcode, gcode_path)

        if ext == 'gcode':
            self.absolute_path = gcode_path
        else:
            # Update the output file
            self.absolute_path = await loop.run_in_executor(
                None, self.update_output, updated, gcode_path, name, ext)

        # Return the file itself
        return await super().get(name_ext)


    def update_output(self, updated, gcode_path, name, ext):
        """
        Ensure that the output (json or obj) is updated. Recreates it from the
        gcode if necessary.

        This blocks, should be used with an executor.
        """
        # Get the arguments
        func = gcode_to_json if ext == 'json' else gcode_to_obj
        try: infill = strtobool(self.get_argument('infill', None))
        except (ValueError, AttributeError): infill = None
        try: support = strtobool(self.get_argument('support', 'false'))
        except (ValueError, AttributeError): support = False

        # Auto-pick infill as True if file is less than 10 MiB
        if infill is None: infill = os.path.getsize(gcode_path) < 10485760

        # Compute the output name
        name_ext = name
        if not infill: name_ext += '_no_infill'
        if support: name_ext += '_support'
        name_ext += '.' + ext
        output_path = os.path.join(CWD, name_ext)

        # Check if an update is needed
        if not updated and self.printer.is_up_to_date(output_path):
            return output_path

        # Convert and save the file
        with open(gcode_path) as gcode, open(output_path, "w") as f:
            func(gcode, out=f,
                 ignore_infill=not infill, ignore_support=not support)

        return output_path


    def update_gcode(self, path):
        """
        Ensure that we have an up-to-date gcode file at that path. If not
        already up-to-date, downloads it from the remote source and writes
        to the path.

        This blocks, should be used with an executor.
        """
        if self.printer.is_up_to_date(path): return False

        # Download the current gcode and save the file
        gcode = self.printer.get_gcode()
        with open(path, "w") as f: f.write(gcode)
        return True
