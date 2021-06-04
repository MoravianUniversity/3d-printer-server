#!/usr/bin/env python3

"""PUTs to *.obj save an OBJ file."""

import os.path
import tornado.web
from model.gcode_to_obj import gcode_to_obj

cwd = os.path.dirname(os.path.abspath(__file__))

class ModelHandler(tornado.web.StaticFileHandler): # pylint: disable=abstract-method
    """Supports PUT for OBJ file to save them"""
    def put(self, name): # pylint: disable=arguments-differ
        with open(os.path.join(cwd, name), 'wb') as file:
            # could be made asynchronous with aiofiles, but shouldn't really block for long
            file.write(self.request.body)
        self.finish("file" + name + " is uploaded")

    def get(self, name): # pylint: disable=arguments-differ
        path = os.path.join(cwd, name)
        # Check file age
        #if x < 5 or False: # check time on file and if the printer is not currently printing  os.path.getmtime(path)
        #    return super().get(name)
        
        #eventually get this from printer
        gcode = open(os.path.join(cwd, 'test_generic.gcode')).readlines()
        obj = gcode_to_obj(gcode)
        with open(path, "w") as f:
            f.write(obj)
        return super().get(name)
