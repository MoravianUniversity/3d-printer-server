#!/usr/bin/env python3
"""
3D Printer Management Server
"""

import os
import asyncio
from configparser import ConfigParser

from tornado.web import Application, StaticFileHandler, RequestHandler, RedirectHandler

from info import InfoHandler
from model import ModelHandler
from video import VideoHandler, VideoStaticFileHandler, terminate_video_streams


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
    app.listen(8888)
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        terminate_video_streams()
