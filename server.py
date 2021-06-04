#!/usr/bin/env python3
"""
3D Printer Management Server
"""

import tornado.ioloop
import tornado.web

import model
import video

class TemplateHandler(tornado.web.RequestHandler): # pylint: disable=abstract-method
    """Handles .html files that are templates as .html.template"""
    def get(self, cat, name): # pylint: disable=arguments-differ
        self.render(cat+"/"+cat+".html.template", name=name)

def make_app():
    return tornado.web.Application([
        (r"/model/(.*\.obj)", model.ModelHandler, {"path":"model"}),
        (r"/video/(.*)\.m3u8", video.VideoHandler, {"path":"video"}),
        (r"/(model|video)/(.*)\.html", TemplateHandler),
        (r"/(.*)", tornado.web.StaticFileHandler, {"path":".", "default_filename":"index.html"}),
    ], debug=True, autoreload=True)

if __name__ == "__main__":
    app = make_app()
    app.listen(8888)
    try:
        tornado.ioloop.IOLoop.current().start()
    finally:
        video.terminate_streams()
