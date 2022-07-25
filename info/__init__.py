#!/usr/bin/env python3

"""Serves JSON data containing information about a printer."""

import json
from datetime import timedelta
from re import L

from tornado.ioloop import IOLoop

from printers import PrinterHandler


class InfoHandler(PrinterHandler):  # pylint: disable=abstract-method
    """Gets JSON describing the currently information about the printer."""
    async def get(self, name):  # pylint: disable=arguments-differ
        self.set_header('Content-Type', 'application/json')
        printer = self.get_printer(name)
        loop = IOLoop.current()
        data = await loop.run_in_executor(None, self.generate_info, printer)
        self.write(json.dumps(data))


    def write_error(self, status_code, **kwargs):
        if 'message' not in kwargs:
            if status_code == 405:
                kwargs['message'] = 'Invalid HTTP method.'
            else:
                kwargs['message'] = 'Unknown error.'
        self.write(json.dumps(kwargs))


    def generate_info(self, printer):
        """
        Creates the output information about the printer.
        This blocks, should be used with an executor.
        """
        name = printer.name
        info = {"name": name}
        info["status"] = printer.status
        if printer.supports_video:
            info["video"] = {
                "url": printer.video_url,
                "type": printer.video_type,
            }
        info["link"] = printer.link if printer.supports_link else None
        info["supports_model"] = printer.supports_gcode
        if printer.supports_job:
            remaining = printer.job_remaining_time
            if isinstance(remaining, timedelta):
                remaining = remaining.total_seconds()
            started = printer.job_started.strftime(r"%Y-%m-%dT%H:%M:%SZ")
            info["job"] = {"remaining": remaining, "started": started}
        return True
