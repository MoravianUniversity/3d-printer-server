"""Serves JSON data containing information about a printer."""

import json
from datetime import timedelta

from tornado.web import RequestHandler

from printers import get_printer
from async_util import run_async


class InfoHandler(RequestHandler):  # pylint: disable=abstract-method
    """Gets JSON describing the currently information about the printer."""
    async def get(self, name):  # pylint: disable=arguments-differ
        self.set_header('Content-Type', 'application/json')
        self.write(await run_async(generate_info, name, self.settings['config']))

    def write_error(self, status_code, **kwargs):
        if 'message' not in kwargs:
            if status_code == 405:
                kwargs['message'] = 'Invalid HTTP method.'
            else:
                kwargs['message'] = 'Unknown error.'
        try:
            self.write(json.dumps(kwargs))
        except TypeError:
            self.write(json.dumps({k:str(v) for k,v in kwargs.items()}))


def generate_info(name, config):
    """
    Creates the output information about the printer.
    This blocks, should be used with an executor.
    """
    printer = get_printer(name, config)
    info = {"name": printer.name}
    info["status"] = printer.status
    if printer.supports_video:
        info["video"] = {
            "url": printer.video_url,
            "type": printer.video_type,
            "settings": printer.video_settings,
        }
    info["link"] = printer.link if printer.supports_link else None
    info["supports_model"] = printer.supports_gcode
    if printer.supports_job:
        remaining = printer.job_remaining_time
        if isinstance(remaining, timedelta):
            remaining = remaining.total_seconds()
        started = printer.job_started.strftime(r"%Y-%m-%dT%H:%M:%SZ")
        info["job"] = {"remaining": remaining, "started": started}
    return json.dumps(info)
