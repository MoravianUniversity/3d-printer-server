import os.path
from abc import abstractmethod
from datetime import datetime
from functools import cache, cached_property

import requests
from tornado.web import StaticFileHandler, HTTPError

from ultimaker_api.ultimaker import PrinterStatus


@cache
def get_printer_classes_by_type():
    """
    Gets all subclasses of Printer in a dictionary with the key their TYPE.
    """
    subclasses = {}
    def recurse(clazz):
        for subclass in clazz.__subclasses__():
            if hasattr(subclass, 'TYPE'):
                subclasses[subclass.TYPE] = subclass
            recurse(subclass)
    recurse(Printer)
    return subclasses


class PrinterHandler(StaticFileHandler):  # pylint: disable=abstract-method
    def get_printer(self, name):
        # Get the configuration for the printer
        config = self.settings['config']
        if name not in config: raise HTTPError(404)
        config = config[name]
        if 'type' not in config: raise HTTPError(404)

        # Get the class to use for the printer
        cls = get_printer_classes_by_type().get(config['type'], Printer)

        # Create the printer object
        return cls(config)


def file_mod_datetime(path):
    return datetime.utcfromtimestamp(os.path.getmtime(path))


class Printer:
    def __init__(self, config):
        self.config = config

    @property
    def name(self): return self.config.name

    @property
    def supports_video(self):
        """
        If this returns True, this printer supports calling get_video_url().
        Otherwise that method raises an exception. Default is True if the
        printer's configuration includes a 'video' key.
        """
        return 'video' in self.config

    def get_video_url(self): return self.config['video']


    @property
    def supports_gcode(self):
        """
        If this returns True, this printer supports calling get_gcode() and
        is_up_to_date(). Otherwise those methods raise exceptions. Default is
        False.
        """
        return False

    def get_gcode(self):
        """
        Gets the currently printing complete gcode for the printer. Can block.
        """
        raise NotImplementedError()

    def is_up_to_date(self, path):
        """
        Checks if the path is up-to-date. A file is up-to-date if:
          - printer is not printing (whatever data we have is fine)
          - path exists and has a timestamp after the printer start most recent
            print job
        Can block.
        """
        raise NotImplementedError()


class Ultimaker(Printer):
    TYPE = 'ultimaker'

    def __init__(self, config):
        from ultimaker_api.ultimaker import Ultimaker
        if 'hostname' not in config: raise HTTPError(500)
        super().__init__(config)
        self.ultimaker = Ultimaker(config['hostname'])

    @property
    def supports_video(self): return True

    def get_video_url(self):
        return self.config['video'] if 'video' in self.config else \
            f"http://{self.config['hostname']}:8080/?action=stream"

    @property
    def supports_gcode(self): return True

    def get_gcode(self):
        return self.ultimaker.print_job.gcode

    def is_up_to_date(self, path):
        return (
            self.printer_status != PrinterStatus.PRINTING or  # not printing anything
            os.path.isfile(path) and (
                self.print_job_reprint or  # reprint, gcode isn't be available
                file_mod_datetime(path) > self.print_job_started))  # up-to-date


    # These properties get cached to reduce the number of REST API requests

    @cached_property
    def printer_status(self):
        return self.ultimaker.printer.status


    @cached_property
    def print_job_reprint(self):
        return self.ultimaker.print_job.reprint_original_uuid


    @cached_property
    def print_job_started(self):
        return self.ultimaker.print_job.datetime_started


class Ender(Printer):
    # TODO: none of this is tested at all

    TYPE = 'ender'

    def __init__(self, config):
        if 'hostname' not in config or 'apikey' not in config:
            raise HTTPError(500)
        super().__init__(config)


    def fetch(self, url):
        return requests.get(
            url, headers={"X-Api-Key":self.config["apikey"]})

    @cache
    def get(self, cmd):
        return self.fetch(f'http://{self.config["hostname"]}/api/{cmd}').json()

    @property
    def supports_video(self):
        settings = self.get('settings')
        return "webcam" in settings and "streamUrl" in settings["webcam"]

    def get_video_url(self):
        return self.get('settings')["webcam"]["streamUrl"]

    @property
    def supports_gcode(self): return True

    def get_gcode(self):
        job = self.get("job")["job"]
        #filename = job["file"]["name"]
        origin = job["file"]["origin"]
        path = job["file"]["path"]
        file = self.get(f"files/{origin}/{path}")
        return self.fetch(file["refs"]["download"]).json()

    def is_up_to_date(self, path):
        return (
            not self.printer_is_printing or  # not printing anything
            os.path.isfile(path) and (
                file_mod_datetime(path) > self.print_job_started))  # up-to-date

    @property
    def printer_is_printing(self):
        flags = self.get("printer")["state"]["flags"]
        return flags["printing"] or flags["paused"] or flags["pausing"]

    @property
    def print_job_started(self):
        return TODO
