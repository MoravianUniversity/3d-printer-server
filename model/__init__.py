#!/usr/bin/env python3

"""PUTs to *.obj save an OBJ file."""

import os.path
import tornado.web
from model.gcode_to_obj import gcode_to_obj
from ultimaker_api.ultimaker import Ultimaker, PrinterStatus
from datetime import datetime

cwd = os.path.dirname(os.path.abspath(__file__))

class ModelHandler(tornado.web.StaticFileHandler): # pylint: disable=abstract-method
    """Supports PUT for OBJ file to save them"""  # TODO update
    def get(self, name): # pylint: disable=arguments-differ
        path = os.path.join(cwd, name)
        hostname = name.split('.')[0] + '.cslab.moravian.edu'
        # hostname = 'localhost:' + '5000' if name.split('.')[0] == 'xerox' else '5001'
        ultimaker = Ultimaker(hostname)
        printer = ultimaker.printer
        print_job = ultimaker.print_job
        printer_status = printer.status

        # If a reprint
        if printer_status == PrinterStatus.PRINTING and print_job.reprint_original_uuid and os.path.isfile(path):
            return super().get(name)

        if printer_status != PrinterStatus.PRINTING or os.path.isfile(path) and datetime.utcfromtimestamp(os.path.getmtime(path)) > print_job.datetime_started:
            return super().get(name)

        # Include printer.printer.heads in case a printer has more than one head
        gcode = print_job.gcode.split('\n')
        obj = gcode_to_obj(gcode, [i for i, extruder in enumerate(printer.head.extruders) if extruder.active_material.material.material != "PVA"])
        with open(path, "w") as f:
            f.write(obj)
        
        return super().get(name)
