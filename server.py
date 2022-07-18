#!/usr/bin/env python3
"""
3D Printer Management Server
"""

import os
import asyncio
import configparser

import tornado.ioloop
import tornado.web

import model
import video

class TemplateHandler(tornado.web.RequestHandler): # pylint: disable=abstract-method
    """Handles .html files that are templates as .html.template"""
    def get(self, cat, name): # pylint: disable=arguments-differ
        self.render(cat+"/"+cat+".html.template", name=name)


async def main():
    # Get the config information
    config = configparser.ConfigParser()
    config.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini'))

    app = tornado.web.Application([
        (r"/model/(.*\.(?:gcode|json|obj))", model.ModelHandler, {"path":"model"}),
        (r"/video/(.*)\.m3u8", video.VideoHandler),
        (r"/video/(.*\.ts)", video.VideoStaticFileHandler),
        (r"/(model|video)/(.*)\.html", TemplateHandler),
        (r"/(.*)", tornado.web.StaticFileHandler, {"path":".", "default_filename":"index.html"}),
    ], debug=True)
    app.config = config
    
    # Start
    app.listen(8889)
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        video.terminate_streams()
