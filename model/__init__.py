#!/usr/bin/env python3

"""PUTs to *.obj save an OBJ file."""

import os.path
import tornado.web

cwd = os.path.dirname(os.path.abspath(__file__))

class ModelHandler(tornado.web.StaticFileHandler): # pylint: disable=abstract-method
    """Supports PUT for OBJ file to save them"""
    def put(self, name): # pylint: disable=arguments-differ
        with open(os.path.join(cwd, name), 'wb') as file:
            # could be made asynchronous with aiofiles, but shouldn't really block for long
            file.write(self.request.body)
        self.finish("file" + name + " is uploaded")
