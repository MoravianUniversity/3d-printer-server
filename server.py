#!/usr/bin/env python3
"""
3D Printer Management Server
"""

import os
import asyncio
from configparser import ConfigParser

from tornado.web import Application, StaticFileHandler, RequestHandler, RedirectHandler
from tornado.options import define, options, parse_command_line

from info import InfoHandler
from model import ModelHandler
from video import VideoHandler, VideoStaticFileHandler, terminate_video_streams

define("port", default=8888, help="Port to listen on")


class TemplateHandler(RequestHandler): # pylint: disable=abstract-method
    """Handles .html files that are templates as .html.template"""
    def get(self, cat, name): # pylint: disable=arguments-differ
        self.render(cat+"/"+cat+".html.template", name=name)


async def main():
    # Get the config information
    config = ConfigParser()
    directory = os.path.dirname(os.path.abspath(__file__))
    config.read(os.path.join(directory, 'config.ini'))
    
    app = Application([
        (r"/info/(.*)\.json", InfoHandler),
        (r"/model/(.*\.(?:gcode|json|obj))", ModelHandler, {"path":"model"}),
        (r"/video/(.*)\.m3u8", VideoHandler),
        (r"/video/(.*\.ts)", VideoStaticFileHandler),
        (r"/(model|video)/(.*)\.html", TemplateHandler),
        (r"/", RedirectHandler, {"url": "/dashboard"}),
        (r"/(.*)", StaticFileHandler, {"path":".", "default_filename":"index.html"}),
    ], debug=True, autoreload=False, config=config)
    
    # Start
    print("Listening on port {options.port}...")
    app.listen(options.port)
    await asyncio.Event().wait()

if __name__ == "__main__":
    parse_command_line()
    try:
        asyncio.run(main())
    finally:
        terminate_video_streams()
