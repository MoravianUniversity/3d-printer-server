"""
An object-oriented model of working with the Ultimaker API. The primary class is the Ultimaker
class which deals with communication  with the printer and authentication if necessary. A few of
the pieces of the API that are not well documented (e.g. wifi networks) are possibly not implemented
correctly but the vast majority of parts are tested and working correctly.

Instead of accessing the API through a URL like http://<ip>/api/v1/printer/status attribute lookup
is used:

    u = Ultimaker('<ip_or_hostname>')
    u.printer.status

Any simple put/post operations can be done with assignments, such as:

    u.printer.led.hue = 0.5

There are several functions as well for dealing with more complex requests. If any request requires
authentication and no authentication is provided to the Ultimaker constructor, then a username is
made up and a password is requested from the printer itself, however this requires the user to
accept the connection on the printer itself. The credentials are saved on this machine and won't
be required again.
"""

import copy, time, datetime, os # pylint: disable=multiple-imports
from enum import Enum
import collections.abc
from collections.abc import Sequence, Mapping
import requests
from requests.auth import HTTPDigestAuth

# pylint: disable=protected-access, multiple-statements
# pylint: disable=missing-docstring

def _dt(string): return None if not string else datetime.datetime.fromisoformat(string.rstrip("Z"))
def _extract(dictionary, *keys): return {k:dictionary[k] for k in keys}

class Ultimaker:
    def __init__(self, hostname, username=None, password=None):
        self._hostname = hostname
        if username is not None and password is not None:
            self._auth = HTTPDigestAuth(username, password)

    def __eq__(self, other):
        return isinstance(other, Ultimaker) and self._hostname == other._hostname
    def __ne__(self, other): return not self == other

    def _url(self, cmd): return 'http://'+self._hostname+'/api/v1/'+cmd

    @staticmethod
    def _check_response(response):
        if response.status_code == 204: return None
        if response.status_code == 405: raise AttributeError()
        if not response:
            try: data = response.json()
            except ValueError: data = {}
            if 'message' in data:
                if response.status_code == 404:
                    raise KeyError(data['message'])
                raise ValueError(data['message'])
            else: response.raise_for_status()
        res = response.json()
        if isinstance(res, dict) and (res.get('return_value', 1) in (0, False) or
                                      res.get('result', 1) in (0, False)):
            raise ValueError('invalid value')
        return res

    _auth = None
    def _get_auth(self):
        if self._auth is None:
            # Try to load a saved copy of the authetication credentials
            if not self.auth.load():
                id,key = self.auth.acquire('ultimaker-py-api')
                self._id = id
                self._key = key
                self.auth.store()
        return self._auth

    def _get(self, cmd):
        return Ultimaker._check_response(requests.get(self._url(cmd), auth=self._auth))
    def _put(self, cmd, data):
        return Ultimaker._check_response(requests.put(self._url(cmd),
                                                      json=data, auth=self._get_auth()))
    def _post(self, cmd, data):
        return Ultimaker._check_response(requests.post(self._url(cmd),
                                                       json=data, auth=self._get_auth()))
    def _delete(self, cmd, data=None):
        return Ultimaker._check_response(requests.delete(self._url(cmd),
                                                         json=data, auth=self._get_auth()))

    def _get_file(self, cmd):
        response = requests.get(self._url(cmd), auth=self._get_auth())
        response.raise_for_status()
        return response.text
    def _post_file(self, cmd, file, data=None):
        # file can be:
        #   a string with a filename
        #   a file-like object (should have a name attribute)
        #   a tuple of filename and file-like object
        #   a tuple of filename and data
        #   a dictionary of that can be immediately passed to requests
        # file-like objects should be open in 'rb' mode
        if isinstance(file, dict):
            files = file
        elif isinstance(file, str):
            files = {'file':(os.path.basename(file), open(file, 'rb'))}
        return Ultimaker._check_response(
            requests.post(self._url(cmd), data=data, files=files, auth=self._get_auth()))
    def _put_file(self, cmd, file, data=None):
        if isinstance(file, dict): files = file
        elif isinstance(file, str): files = {'file':(os.path.basename(file), open(file, 'rb'))}
        return Ultimaker._check_response(requests.put(self._url(cmd), data=data, files=files,
                                                      auth=self._get_auth()))

    @property
    def id(self): return self._auth.username #pylint: disable=invalid-name
    @property
    def key(self): return self._auth.password

    @property
    def auth(self): return Auth(self)
    @property
    def materials(self): return Materials(self)
    @property
    def printer(self): return Printer(self)
    @property
    def network(self): return PrinterNetwork(self)
    @property
    def print_job(self): return PrintJob(self)
    @property
    def system(self): return System(self)
    @property
    def history(self): return History(self)
    @property
    def camera(self): return Camera(self)

class Auth:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other): return isinstance(other, Auth) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other

    def request(self, application, user=None, host_name=None, exclusion_key=None):
        if user is None:
            from getpass import getuser
            user = getuser()
        if host_name is None:
            import platform
            host_name = platform.node()
        data = {'application':application, 'user':user, 'host_name':host_name}
        if exclusion_key is not None: data['exclusion_key'] = exclusion_key
        response = requests.post(self._ultimaker._url('auth/request'), data=data)
        if response.status_code != 200: response.raise_for_status()
        data = Ultimaker._check_response(response)
        return data["id"], data["key"]

    # Returns one of 'authorized', 'unknown' (currently prompting), or 'unauthorized'
    # 'authorized' is only returned for a short time after the authentication acquisition process,
    # otherwise everyone is marked as 'unauthorized'
    def check(self, id_): return self._ultimaker._get('auth/check/'+id_)["message"]

    def verify(self, auth=None):
        response = requests.get(self._ultimaker._url('auth/verify'),
                                auth=auth or self._ultimaker._auth)
        return response.status_code == 200 and response.json()["message"] == "ok"
        # otherwise:
        #   response.status_code == 403 and response.json()["message"] == "Authorization required."

    def acquire(self, application, user=None, host_name=None, exclusion_key=None, set_auth=True):
        """
        Combination of request(), check(), and verify(). By default this also replaces the
        authorization on the Ultimaker with the new authorization if successful. Turn it off by
        passing set_auth=False. Always returns the id/key acquired if successful. If not successful
        a PermissionError is raised.
        """
        # Create the id and key
        id_, key = self.request(application, user, host_name, exclusion_key)
        # Wait for the user to choose an option
        while self.check(id_) == "unknown": time.sleep(0.25)
        # Raise an error if denied
        if self.check(id_) == "unauthorized": raise PermissionError()
        # Establish the authentication and verify
        auth = HTTPDigestAuth(id_, key)
        if not self.verify(auth): raise PermissionError()
        if set_auth: self._ultimaker._auth = auth
        # Return the results
        return id_, key

    @staticmethod
    def _user_config_dir(appname):
        import sys
        system = sys.platform
        if system.startswith('java'):
            import platform
            os_name = platform.java_ver()[3][0]
            if os_name.startswith('Windows'): system = 'win32'
            elif os_name.startswith('Mac'): system = 'darwin'
            else: system = 'linux2'
        if system == "win32":
            import ctypes
            buf = ctypes.create_unicode_buffer(4096)
            ctypes.windll.shell32.SHGetFolderPathW(None, 28, None, 0, buf)
            if any(ord(c) > 255 for c in buf):
                buf2 = ctypes.create_unicode_buffer(4096)
                if ctypes.windll.kernel32.GetShortPathNameW(buf.value, buf2, 4096):
                    buf = buf2
            path = os.path.normpath(buf.value)
        elif system == 'darwin': path = os.path.expanduser('~/Library/Application Support/')
        else: path = os.getenv('XDG_CONFIG_HOME', os.path.expanduser("~/.config"))
        return os.path.join(path, appname)

    @staticmethod
    def _get_config_path():
        appdir = Auth._user_config_dir('ultimaker-py-api')
        os.makedirs(appdir, exist_ok=True)
        config_path = os.path.join(appdir, 'config.ini')
        with open(config_path, 'a') as file: file.write('')
        return config_path

    def store(self):
        from configparser import ConfigParser
        config_path = Auth._get_config_path()
        config = ConfigParser()
        config.read(config_path)
        hostname = self._ultimaker._hostname
        config.setdefault(hostname, {})
        config[hostname]['id'] = self._ultimaker._id
        config[hostname]['key'] = self._ultimaker._key
        with open(config_path, 'w') as file: config.write(file)

    def load(self):
        from configparser import ConfigParser
        config = ConfigParser()
        config.read(Auth._get_config_path())
        hostname = self._ultimaker._hostname
        if hostname not in config: return False
        info = config[hostname]
        auth = HTTPDigestAuth(info['id'], info['key'])
        if not self.verify(auth): return False
        self._ultimaker._auth = auth
        return True


class _Mapping(Mapping):
    """
    A collection of objects that are treated as a dictionary or mapping. This is used for the
    Materials which map GUIDs to Material objects and Wifi Networks which maps SSIDs to Wifi
    Networks. In both cases the keys are strings. The length of the collection is cached between
    calls. Nothing else is cached.

    You can also remove items using `del mapping[key]` or `mapping.clear()` however this only works
    in special situations.

    Additionally the concrete classes have some additional methods for adding or setting.
    """
    _subtype = None
    class KeysView(collections.abc.KeysView): # pylint: disable=too-many-ancestors
        def __len__(self): return len(self._mapping)
        def __contains__(self, key): return key in self._mapping
        def __iter__(self): return iter(self._mapping)
    class ValuesView(collections.abc.ValuesView):
        def __len__(self): return len(self._mapping)
        def __contains__(self, value):
            return isinstance(value, self._mapping._subtype) and \
                self._mapping.get(self._mapping._get_key(value)) == value
        def __iter__(self):
            subtype = self._mapping._subtype
            for value in self._mapping.raw: yield subtype(value)
    class ItemsView(collections.abc.ItemsView): # pylint: disable=too-many-ancestors
        def __len__(self): return len(self._mapping)
        def __contains__(self, item):
            return (isinstance(item, tuple) and len(item) == 2 and
                    isinstance(item[0], str) and isinstance(item[1], self._mapping._subtype) and
                    item[1] == self._mapping.get(item[0]))
        def __iter__(self):
            for value in self._mapping.raw:
                value = self._mapping._subtype(value)
                yield (self._mapping._get_key(value), value)

    # pylint: disable=not-callable
    _subtype = None # concrete class must specify this along with _get_key below
    _len = -1
    def __init__(self, ultimaker, base):
        self._ultimaker = ultimaker
        self._base = base
    @classmethod
    def _get_key(cls, value): raise NotImplementedError()

    @property
    def raw(self): return self._ultimaker._get(self._base)
    def __iter__(self):
        subtype = self._subtype
        for entry in self.raw: yield self._get_key(subtype(entry))
    def keys(self): return _Mapping.KeysView(self)
    def values(self): return _Mapping.ValuesView(self)
    def items(self): return _Mapping.ItemsView(self)
    def __len__(self):
        if self._len == -1: self._len = len(self.raw)
        return self._len
    def __contains__(self, key):
        # Simple implementation of this, best to overload with better if possible
        try:
            _ = self[key]
            return True
        except KeyError: return False
    def __getitem__(self, key):
        # Simple implementation of this, best to overload with better if possible
        for k, value in self.items():
            if k == key: return value
        raise KeyError
    def get(self, key, default=None):
        try: return self[key]
        except (ValueError, KeyError): return default
    def __eq__(self, other):
        if not isinstance(other, _Mapping) or self._base != other._base: return False
        a, b = self.raw, other.raw # pylint: disable=invalid-name
        if a == b: return True
        if len(a) != len(b): return False
        a.sort()
        b.sort()
        return a == b
    def __ne__(self, other): return not self == other

    # Deleting Items
    def __delitem__(self, key):
        self._ultimaker._delete('%s/%s'%(self._base, key))
        self._len = -1
    def clear(self):
        count = 0
        for key in self:
            try:
                del self[key]
                count += 1
            except (ValueError, KeyError): pass
        return count

class Material: # pylint: disable=too-many-public-methods, too-many-instance-attributes
    @staticmethod
    def _opt_val(node, conv=str):
        return None if node is None else conv(node.text)

    @staticmethod
    def _opt_vals(node, tags, namespace):
        out = {}
        for tag in tags:
            val = node.find('{%s}%s' % (namespace, tag))
            if val is not None: out[tag] = val.text
        return out

    @staticmethod
    def _get_contact_info(node, namespace):
        if node is None: return None
        out = Material._opt_vals(node, ('organization', 'contact', 'email', 'phone'), namespace)
        addr = node.find('{%s}%s'%(namespace, 'address'))
        if addr is not None:
            out['address'] = Material._opt_vals(addr, (
                'street', 'city', 'region', 'zip', 'country'
            ), namespace)
        return out

    @staticmethod
    def _get_settings(node, namespace):
        settings = {}
        for setting in node.iterfind('{%s}setting'%namespace):
            key = setting.attrib['key']
            points = setting.findall('{%s}point'%namespace)
            if points:
                val = [{k:float(v) for k, v in pt.attrib.items()} for pt in points]
            else:
                val = setting.text
                val = val == 'yes' if val in ('yes', 'no') else float(val)
            settings[key] = val
        return settings

    def __init__(self, xml):
        from xml.etree import ElementTree
        self.__xml = xml
        ns = 'http://www.ultimaker.com/material' # pylint: disable=invalid-name
        root = ElementTree.fromstring(xml) # fdmmaterial
        self.__xml_doc_version = root.attrib['version']
        metadata = root.find('{%s}metadata'%ns)
        name = metadata.find('{%s}name'%ns)
        self.__brand = name.find('{%s}brand'%ns).text
        self.__material = name.find('{%s}material'%ns).text
        self.__color = name.find('{%s}color'%ns).text
        self.__label = Material._opt_val(name.find('{%s}label'%ns))
        self.__guid = metadata.find('{%s}GUID'%ns).text
        self.__version = int(metadata.find('{%s}version'%ns).text)
        self.__color_code = metadata.find('{%s}color_code'%ns).text
        self.__description = Material._opt_val(metadata.find('{%s}description'%ns))
        self.__adhesion_info = Material._opt_val(metadata.find('{%s}adhesion_info'%ns))
        self.__instruction_link = Material._opt_val(metadata.find('{%s}instruction_link'%ns))
        self.__ean = Material._opt_val(metadata.find('{%s}EAN'%ns))
        self.__tds = Material._opt_val(metadata.find('{%s}TDS'%ns))
        self.__msds = Material._opt_val(metadata.find('{%s}MSDS'%ns))
        self.__supplier = Material._get_contact_info(metadata.find('{%s}supplier'%ns), ns)
        self.__author = Material._get_contact_info(metadata.find('{%s}author'%ns), ns)
        props = root.find('{%s}properties'%ns)
        self.__diameter = float(props.find('{%s}diameter'%ns).text)
        self.__density = Material._opt_val(props.find('density'), float)
        self.__weight = Material._opt_val(props.find('weight'), float)
        settings = root.find('{%s}settings'%ns)
        self.__settings = Material._get_settings(settings, ns)
        self.__machines = [{
            'machine_identifiers':
                [mi.attrib for mi in machine.iterfind('{%s}machine_identifier'%ns)],
            'hotends':
                {he.attrib['id']:Material._get_settings(he, ns) \
                 for he in machine.iterfind('{%s}hotend'%ns)},
            'buildplates':
                {bp.attrib['id']:Material._get_settings(bp, ns) \
                 for bp in machine.iterfind('{%s}buildplate'%ns)},
            'settings': Material._get_settings(machine, ns),
        } for machine in settings.iterfind('{%s}machine'%ns)]

    @property
    def raw(self): return self.__xml
    @property
    def dict(self):
        return {'metadata':self.metadata,
                'properties':self.properties,
                'settings':self.settings,
                'machines':self.machines}
    def __str__(self): return self.guid + ' ' + self.name
    def __eq__(self, other):
        return isinstance(other, Material) and \
            self.__guid == other.__guid and self.metadata == other.metadata
    def __ne__(self, other): return not self == other
    def __hash__(self): return hash(self.__guid)

    @property
    def xml_document_version(self): return self.__xml_doc_version
    @property
    def metadata(self):
        data = {'name':self.name_data, 'guid':self.__guid,
                'version':self.__version, 'color_code':self.__color_code}
        for name in ('description', 'adhesion_info', 'instruction_link', 'ean', 'tds', 'msds'):
            val = getattr(self, '_Material__'+name)
            if val is not None: data[name] = val
        if self.__supplier is not None: data['supplier'] = self.supplier
        if self.__author is not None: data['author'] = self.author
        return data
    @property
    def name(self):
        name = '%s %s' % (self.__brand, self.__material)
        if self.__color != 'Generic': name += ' - %s' % self.__color
        if self.__label is not None: name += ' (%s)' % self.__label
        return name
    @property
    def name_data(self):
        data = {'brand': self.__brand, 'material': self.__material, 'color': self.__color}
        if self.__label is not None: data['label'] = self.__label
        return data
    @property
    def brand(self): return self.__brand
    @property
    def material(self): return self.__material
    @property
    def color(self): return self.__color
    @property
    def label(self): return self.__label
    @property
    def guid(self): return self.__guid
    @property
    def version(self): return self.__version
    @property
    def color_code(self): return self.__color_code
    @property
    def description(self): return self.__description
    @property
    def adhesion_info(self): return self.__adhesion_info
    @property
    def instruction_link(self): return self.__instruction_link
    @property
    def ean(self): return self.__ean
    @property
    def tds(self): return self.__tds
    @property
    def msds(self): return self.__msds
    @property
    def supplier(self): return copy.deepcopy(self.__supplier)
    @property
    def author(self): return copy.deepcopy(self.__author)
    @property
    def properties(self):
        data = {'diameter':self.__diameter}
        if self.__density is not None: data['density'] = self.__density
        if self.__weight is not None: data['weight'] = self.__weight
        return data
    @property
    def diameter(self): return self.__diameter
    @property
    def density(self): return self.__density
    @property
    def weight(self): return self.__weight
    @property
    def settings(self): return copy.deepcopy(self.__settings)
    @property
    def machines(self): return copy.deepcopy(self.__machines)

class Materials(_Mapping):
    _subtype = Material
    def __init__(self, ultimaker): super().__init__(ultimaker, 'materials')
    @classmethod
    def _get_key(cls, value): return value.guid
    def __contains__(self, key):
        try: self._ultimaker._get('%s/%s'%(self._base, key))
        except (ValueError, KeyError): return False
        return True
    def __getitem__(self, key):
        return self._subtype(self._ultimaker._get('%s/%s'%(self._base, key)))

    # Adding and Updating Materials
    @staticmethod
    def __get_filedata(value):
        from io import IOBase
        if isinstance(value, IOBase): return value.read()
        if isinstance(value, str):
            if not os.path.isfile(value): return value
            with open(value, 'rb') as file: return file.read()
        raise TypeError()
    @staticmethod
    def __get_material(value):
        if isinstance(value, Material): return value
        return Material(Materials.__get_filedata(value))
    @staticmethod
    def __get_files(material, signature=None):
        material = Materials.__get_material(material)
        files = {'file':(material.guid+'.xml', material.raw)}
        if signature is not None:
            signature = Materials.__get_filedata(Materials)
            files['signature_file'] = (material.guid+'.sig', signature)
        return files
    def __setitem__(self, key, value):
        material = Materials.__get_material(value)
        if material.guid != key: raise ValueError()
        return self.add(material) if key not in self else self.update(material)
    def add(self, value, signature_file=None):
        material = Materials.__get_material(value)
        if material.guid in self: raise KeyError()
        files = Materials.__get_files(material, signature_file)
        res = self._ultimaker._post_file(self._base, files)
        self._len = -1
        return res
    def update(self, value, signature_file=None):
        material = Materials.__get_material(value)
        previous = self[material.guid]
        if material.version <= previous.version: raise ValueError()
        files = Materials.__get_files(material, signature_file)
        res = self._ultimaker._put_file('%s/%s'%(self._base, material.guid), files)
        self._len = -1
        return res

class PrinterStatus(Enum):
    IDLE = "idle"
    PRINTING = "printing"
    ERROR = "error"
    MAINTENANCE = "maintenance"
    BOOTING = "booting"

class Printer:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, Printer) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get('printer')
    @property
    def dict(self): return Printer.transform_raw(self.raw)
    @staticmethod
    def transform_raw(data):
        del data['beep']
        del data['diagnostics']
        del data['validate_header']
        data['led'] = PrinterLED.transform_raw(data['led'])
        data['heads'] = PrinterHeads.transform_raw(data['heads'])
        data['bed'] = PrinterBed.transform_raw(data['bed'])
        data['network'] = PrinterNetwork.transform_raw(data['network'])
        return data
    @property
    def diagnostics(self): return PrinterDiagnostics(self._ultimaker)
    @property
    def status(self): return PrinterStatus(self._ultimaker._get('printer/status'))
    @property
    def led(self): return PrinterLED(self._ultimaker)
    @property
    def head(self): return PrinterHead(self._ultimaker, 'printer/heads', 0)
    @property
    def heads(self): return PrinterHeads(self._ultimaker)
    @property
    def bed(self): return PrinterBed(self._ultimaker)
    def validate_header(self, gcode):
        return self._ultimaker._post_file('printer/validate_header', gcode)
    def beep(self, frequency, duration):
        return self._ultimaker._post('printer/beep', {
            'frequency':float(frequency), 'duration':float(duration)
        })
    @property
    def network(self): return PrinterNetwork(self._ultimaker)

class PrinterDiagnostics:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, PrinterDiagnostics) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    def cap_sensor_noise(self, loop_count=100, sample_count=50):
        return self._ultimaker._get('printer/diagnostics/cap_sensor_noise/%d/%d'%(
            int(loop_count), int(sample_count)
        ))
    def temperature_flow(self, sample_count, numpy=False):
        data = self._ultimaker._get('printer/diagnostics/temperature_flow/%d'%int(sample_count))
        if numpy:
            import numpy as np
            data = np.array(data[1:])
        return data
    def probing_report(self):
        return self._ultimaker._get('printer/diagnostics/probing_report')

class PrinterLED:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, PrinterLED) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get('printer/led')
    @property
    def dict(self): return _extract(self.raw, 'hue', 'saturation', 'brightness')
    @staticmethod
    def transform_raw(data): return _extract(data, 'hue', 'saturation', 'brightness')
    @property
    def hue(self): return self._ultimaker._get('printer/led/hue')
    @hue.setter
    def hue(self, value): self._ultimaker._put('printer/led/hue', float(value))
    @property
    def saturation(self): return self._ultimaker._get('printer/led/saturation')
    @saturation.setter
    def saturation(self, value): self._ultimaker._put('printer/led/saturation', float(value))
    @property
    def brightness(self): return self._ultimaker._get('printer/led/brightness')
    @brightness.setter
    def brightness(self, value): self._ultimaker._put('printer/led/brightness', float(value))
    def blink(self, frequency=1, count=1):
        return self._ultimaker._post('printer/led/blink', {
            'frequency':float(frequency), 'count':int(count)
        })
    def set_color(self, h, s, b): # pylint: disable=invalid-name
        return self._ultimaker._put('printer/led', {
            "hue":float(h), "saturation":float(s), "brightness":float(b)
        })
    def set_color_rgb(self, r, g, b): # pylint: disable=invalid-name
        # pylint: disable=invalid-name
        mx = max(r, g, b)
        mn = min(r, g, b)
        if mx == mn: h = 0
        elif mx == r: h = (g-b)/(mx-mn)
        elif mx == g: h = 2 + (b-r)/(mx-mn)
        elif mx == b: h = 4 + (r-g)/(mx-mn)
        h *= 60
        if h < 0: h += 360
        l = (mx+mn)/2
        s = 0 if mx == 0 or mn == 1 else (mx-l)/min(l, 1-l)
        return self.set_color(h, s, l)

class _PrinterSeq(Sequence):
    # pylint: disable=not-callable
    _subtype = None
    _len = -1
    def __init__(self, ultimaker, base):
        self._ultimaker = ultimaker
        self._base = base
    def __eq__(self, other):
        return isinstance(other, _PrinterSeq) and \
            self._ultimaker == other._ultimaker and self._base == other._base
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get(self._base)
    @property
    def list(self): return type(self).transform_raw(self.raw)
    @classmethod
    def transform_raw(cls, data): return [cls._subtype.transform_raw(item) for item in data]
    def __len__(self):
        if self._len == -1: self._len = len(self.raw)
        return self._len
    def __iter__(self):
        for i in range(len(self)): yield self._subtype(self._ultimaker, self._base, i)
    def __reversed__(self):
        for i in range(len(self)-1, -1, -1): yield self._subtype(self._ultimaker, self._base, i)
    def __contains__(self, value):
        return isinstance(value, self._subtype) and value._ultimaker == self._ultimaker
    def index(self, value, start=None, stop=None):
        if value in self: raise ValueError('not in list')
        idx = int(value._base.split('/')[2])
        if start is not None and start < 0: start = max(len(self) + start, 0)
        if stop is not None and stop < 0: stop += len(self)
        if (start is not None and idx < start) or (stop is not None and idx >= stop):
            raise ValueError('not in sublist')
        return idx
    def count(self, value): return 1 if value in self else 0
    def __getitem__(self, idx):
        if idx != 0: # there will always be an index 0 so we don't need to check it
            if idx < 0: idx += len(self)
            if idx < 0 or idx >= len(self): raise IndexError()
        return self._subtype(self._ultimaker, self._base, idx)

class PrinterHead:
    def __init__(self, ultimaker, base, idx):
        self._ultimaker = ultimaker
        self._base = base + '/' + str(idx)
    def __eq__(self, other):
        return isinstance(other, PrinterHead) and \
            self._ultimaker == other._ultimaker and self._base == other._base
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get(self._base)
    @property
    def dict(self): return PrinterHead.transform_raw(self.raw)
    @staticmethod
    def transform_raw(data):
        data['jerk'] = PrinterHeadXYZ.transform_raw(data['jerk'])
        data['max_speed'] = PrinterHeadXYZ.transform_raw(data['max_speed'])
        data['position'] = PrinterHeadXYZ.transform_raw(data['position'])
        data['extruders'] = PrinterHeadExtruders.transform_raw(data['extruders'])
        return data

    @property
    def acceleration(self): return self._ultimaker._get(self._base+'/acceleration')
    @acceleration.setter
    # doing a put silently fails, default is 3000.0, constrained >= 5.0, gcode M204 S%g
    def acceleration(self, value): self._ultimaker._put(self._base+'/acceleration', float(value))

    @property
    def fan(self): return self._ultimaker._get(self._base+'/fan')

    @property
    def jerk(self): return PrinterHeadXYZ(self._ultimaker, self._base, 'jerk')
    @jerk.setter
    # doing a put silently fails, x/y are coupled, default 20.0, constrained >= 0.0, gcode M205 X%g
    # jerk z defaults to 0.4, constrained >= 0.0, gcode M205 Z%g
    def jerk(self, value): self.jerk.xyz = value
    def set_jerk(self, xy, z): return self.jerk._set(xy, xy, z) # pylint: disable=invalid-name
    @property
    def max_speed(self): return PrinterHeadXYZ(self._ultimaker, self._base, 'max_speed')
    @max_speed.setter
    # doing a put silently fails, x and y default to 300.0, constrained >= 5.0,
    # gcode M203 X%g and M203 Y%g
    # max_speed z defaults to 40.0, constrained >= 5.0, gcode M203 Z%g
    def max_speed(self, value): self.max_speed.xyz = value
    def set_max_speed(self, x, y, z): return self.max_speed._set(x, y, z) # pylint: disable=invalid-name

    @property
    def position(self): return PrinterHeadPosition(self._ultimaker, self._base)
    @position.setter
    def position(self, value): self.position.xyz = value
    def set_position(self, x, y, z): return self.position._set(x, y, z) # pylint: disable=invalid-name


    @property
    def extruders(self): return PrinterHeadExtruders(self._ultimaker, self._base)

class PrinterHeads(_PrinterSeq): # pylint: disable=too-many-ancestors
    _subtype = PrinterHead
    def __init__(self, ultimaker): super().__init__(ultimaker, 'printer/heads')

class PrinterHeadXYZ:
    def __init__(self, ultimaker, base, name):
        self._ultimaker = ultimaker
        self._base = base + '/' + name
    @property
    def raw(self): return self._ultimaker._get(self._base)
    @property
    def dict(self): return _extract(self.raw, 'x', 'y', 'z')
    @staticmethod
    def transform_raw(data): return _extract(data, 'x', 'y', 'z')
    def __eq__(self, other):
        return isinstance(other, PrinterHeadXYZ) and \
            self._ultimaker == other._ultimaker and self._base == other._base
    def __ne__(self, other): return not self == other
    # pylint: disable=invalid-name
    @property
    def x(self): return self.raw['x']
    @x.setter
    def x(self, value): raw = self.raw; self._set(value, raw['y'], raw['z'])
    @property
    def y(self): return self.raw['y']
    @y.setter
    def y(self, value): raw = self.raw; self._set(raw['x'], value, raw['z'])
    @property
    def z(self): return self.raw['z']
    @z.setter
    def z(self, value): raw = self.raw; self._set(raw['x'], raw['y'], value)
    @property
    def xyz(self): raw = self.raw; return (raw['x'], raw['y'], raw['z'])
    @xyz.setter
    def xyz(self, value):
        _ = self._set(**value) if isinstance(value, Mapping) else self._set(*value)
    def _set(self, x, y, z):
        return self._ultimaker._put(self._base, {'x', float(x), 'y', float(y), 'z', float(z)})

class PrinterHeadPosition(PrinterHeadXYZ):
    # Position can have x, y, and z queried independently and has integer values instead of float
    def __init__(self, ultimaker, base): super().__init__(ultimaker, base, 'position')
    @property
    def x(self): return self._ultimaker._get(self._base+'/x')
    @x.setter
    def x(self, value): self._ultimaker._put(self._base+'/x', int(value))
    @property
    def y(self): return self._ultimaker._get(self._base+'/y')
    @y.setter
    def y(self, value): self._ultimaker._put(self._base+'/y', int(value))
    @property
    def z(self): return self._ultimaker._get(self._base+'/z')
    @z.setter
    def z(self, value): self._ultimaker._put(self._base+'/z', int(value))
    def _set(self, x, y, z): return self._ultimaker._put(self._base,
                                                         {'x', int(x), 'y', int(y), 'z', int(z)})

class PrinterHeadExtruder:
    def __init__(self, ultimaker, base, idx):
        self._ultimaker = ultimaker
        self._base = base + '/' + str(idx)
    def __eq__(self, other):
        return isinstance(other, PrinterHeadExtruder) and \
            self._ultimaker == other._ultimaker and self._base == other._base
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get(self._base)
    @property
    def dict(self): return PrinterHeadExtruder.transform_raw(self.raw)
    @staticmethod
    def transform_raw(data):
        data['active_material'] = \
            PrinterHeadExtruderActiveMaterial.transform_raw(data['active_material'])
        data['feeder'] = PrinterHeadExtruderFeeder.transform_raw(data['feeder'])
        data['hotend'] = PrinterHeadExtruderHotend.transform_raw(data['hotend'])
        return data
    @property
    def active_material(self): return PrinterHeadExtruderActiveMaterial(self._ultimaker, self._base)
    @property
    def feeder(self): return PrinterHeadExtruderFeeder(self._ultimaker, self._base)
    @property
    def hotend(self): return PrinterHeadExtruderHotend(self._ultimaker, self._base)

class PrinterHeadExtruders(_PrinterSeq): # pylint: disable=too-many-ancestors
    _subtype = PrinterHeadExtruder
    def __init__(self, ultimaker, base): super().__init__(ultimaker, base + '/extruders')

class PrinterHeadExtruderActiveMaterial:
    def __init__(self, ultimaker, base):
        self._ultimaker = ultimaker
        self._base = base + '/active_material'
    def __eq__(self, other):
        return isinstance(other, PrinterHeadExtruderActiveMaterial) and \
            self._ultimaker == other._ultimaker and self._base == other._base
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get(self._base)
    @property
    def dict(self): return PrinterHeadExtruderActiveMaterial.transform_raw(self.raw)
    @staticmethod
    def transform_raw(data):
        if data['length_remaining'] == -1: data['length_remaining'] = None
        data.pop('GUID', None)
        return data
    @property
    def guid(self): return self._ultimaker._get(self._base+'/guid')
    @property
    def material(self): return self._ultimaker.materials[self.guid]
    @property
    def length_remaining(self):
        value = self._ultimaker._get(self._base+'/length_remaining')
        return None if value == -1 else value

class PrinterHeadExtruderFeeder:
    def __init__(self, ultimaker, base):
        self._ultimaker = ultimaker
        self._base = base + '/feeder'
    def __eq__(self, other):
        return isinstance(other, PrinterHeadExtruderFeeder) and \
            self._ultimaker == other._ultimaker and self._base == other._base
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get(self._base)
    @property
    def dict(self): return self.raw
    @staticmethod
    def transform_raw(data): return data
    #@property # this shows up in the model for Feeder but no where else (not even in the source)
    #def position(self): return self._ultimaker._get(self._base+'/position')
    @property # doing a put silently fails, default is 3000.0, constrained >= 5.0, gcode M204 T%g
    def acceleration(self): return self._ultimaker._get(self._base+'/acceleration')
    @property # doing a put silently fails, default is 5.0, constrained >= 0, gcode M205 E%g
    def jerk(self): return self._ultimaker._get(self._base+'/jerk')
    @property # doing a put silently fails, default is 45.0, constrained >= 5.0, gcode M203 E%g
    def max_speed(self): return self._ultimaker._get(self._base+'/max_speed')

class PrinterHeadExtruderHotend:
    def __init__(self, ultimaker, base):
        self._ultimaker = ultimaker
        self._base = base + '/hotend'
    def __eq__(self, other):
        return isinstance(other, PrinterHeadExtruderHotend) and \
            self._ultimaker == other._ultimaker and self._base == other._base
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get(self._base)
    @property
    def dict(self): return PrinterHeadExtruderHotend.transform_raw(self.raw)
    @staticmethod
    def transform_raw(data):
        data['offset'] = PrinterHeadExtruderHotendOffset.transform_raw(data['offset'])
        data['statistics'] = PrinterHeadExtruderHotendStatistics.transform_raw(data['statistics'])
        data['temperature'] = PrinterTemperature.transform_raw(data['temperature'])
        return data
    @property
    def id(self): return self._ultimaker._get(self._base+'/id') # pylint: disable=invalid-name
    @property
    def serial(self): return self._ultimaker._get(self._base+'/serial')
    @property
    def offset(self): return PrinterHeadExtruderHotendOffset(self._ultimaker, self._base)
    @property
    def statistics(self): return PrinterHeadExtruderHotendStatistics(self._ultimaker, self._base)
    @property
    def temperature(self): return PrinterTemperature(self._ultimaker, self._base)
    @temperature.setter
    def temperature(self, target):
        self._ultimaker._put(self._base+'/temperature/target', float(target))

class PrinterHeadExtruderHotendOffset:
    def __init__(self, ultimaker, base):
        self._ultimaker = ultimaker
        self._base = base + '/offset'
    def __eq__(self, other):
        return isinstance(other, PrinterHeadExtruderHotendOffset) and \
            self._ultimaker == other._ultimaker and self._base == other._base
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get(self._base)
    @property
    def dict(self): return PrinterHeadExtruderHotendOffset.transform_raw(self.raw)
    @staticmethod
    def transform_raw(data):
        data['valid'] = data['state'] == "valid"
        del data['state']
        return data
    @property
    def valid(self): return self._ultimaker._get(self._base+'/state') == "valid"
    # pylint: disable=invalid-name
    @property
    def x(self): return self._ultimaker._get(self._base+'/x')
    @property
    def y(self): return self._ultimaker._get(self._base+'/y')
    @property
    def z(self): return self._ultimaker._get(self._base+'/z')

class PrinterHeadExtruderHotendStatistics:
    def __init__(self, ultimaker, base):
        self._ultimaker = ultimaker
        self._base = base + '/statistics'
    def __eq__(self, other):
        return isinstance(other, PrinterHeadExtruderHotendStatistics) and \
            self._ultimaker == other._ultimaker and self._base == other._base
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get(self._base)
    @property
    def dict(self): return PrinterHeadExtruderHotendStatistics.transform_raw(self.raw)
    @staticmethod
    def transform_raw(data):
        data['time_spent_hot'] = datetime.timedelta(seconds=data['time_spent_hot'])
        return data
    @property
    def last_material_guid(self): return self._ultimaker._get(self._base+'/last_material_guid')
    @property
    def last_material(self): return self._ultimaker.materials[self.last_material_guid]
    @property
    def material_extruded(self): return self._ultimaker._get(self._base+'/material_extruded')
    @property
    def max_temperature_exposed(self):
        return self._ultimaker._get(self._base+'/max_temperature_exposed')
    @property
    def time_spent_hot(self):
        return datetime.timedelta(seconds=self._ultimaker._get(self._base+'/time_spent_hot'))

class PrinterTemperature:
    def __init__(self, ultimaker, base):
        self._ultimaker = ultimaker
        self._base = base + '/temperature'
    def __eq__(self, other):
        return isinstance(other, PrinterTemperature) and \
            self._ultimaker == other._ultimaker and self._base == other._base
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get(self._base)
    @property
    def dict(self): return self.raw
    @staticmethod
    def transform_raw(data): return data
    @property
    def current(self): return self._ultimaker._get(self._base + '/current')
    @property
    def target(self): return self._ultimaker._get(self._base + '/target')
    @target.setter
    def target(self, value): self._ultimaker._put(self._base + '/target', value)
    def __float__(self): return float(self.current)

class PrinterBed:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, PrinterBed) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get('printer/bed')
    @property
    def dict(self): return PrinterBed.transform_raw(self.raw)
    @staticmethod
    def transform_raw(data):
        print(data)
        data['pre_heat'] = PrinterBedPreHeat.transform_raw(data['pre_heat'])
        data['temperature'] = PrinterTemperature.transform_raw(data['temperature'])
        return data
    @property
    def type(self): return self._ultimaker._get('printer/bed/type')
    @property
    def pre_heat(self): return PrinterBedPreHeat(self._ultimaker)
    @property
    def temperature(self): return PrinterTemperature(self._ultimaker, 'printer/bed')
    @temperature.setter
    def temperature(self, target):
        self._ultimaker._put('printer/bed/temperature/target', float(target))

class PrinterBedPreHeat:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, PrinterBedPreHeat) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get('printer/bed/pre_heat')
    @property
    def dict(self): return PrinterBedPreHeat.transform_raw(self.raw)
    @staticmethod
    def transform_raw(data):
        if 'remaining' in data: data['remaining'] = datetime.timedelta(seconds=data['remaining'])
        return data
    @property
    def active(self): return self._ultimaker._get('printer/bed/pre_heat')['active']
    @property
    def remaining(self):
        rem = self._ultimaker._get('printer/bed/pre_heat').get('remaining', None)
        if rem is not None: rem = datetime.timedelta(seconds=rem)
        return rem
    def start(self, temperature, timeout):
        msg = self._ultimaker._put('printer/bed/pre_heat', {
            'temperature':float(temperature), 'timeout':float(timeout)
        })
        return msg['message']
    def cancel(self):
        msg = self._ultimaker._put('printer/bed/pre_heat', {'temperature':0, 'timeout':60})
        return msg['message']

class PrinterNetwork:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, PrinterNetwork) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get('printer/network')
    @property
    def dict(self): return PrinterNetwork.transform_raw(self.raw)
    @staticmethod
    def transform_raw(data):
        data['ethernet'] = PrinterNetworkEthernet.transform_raw(data['ethernet'])
        data['wifi'] = PrinterNetworkWifi.transform_raw(data['wifi'])
        # wifi_networks doesn't need any transformation
        return data
    @property
    def ethernet(self): return PrinterNetworkEthernet(self._ultimaker)
    @property
    def wifi(self): return PrinterNetworkWifi(self._ultimaker)
    @property
    def wifi_networks(self): return PrinterNetworkWifiNetworks(self._ultimaker)

class PrinterNetworkEthernet:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, PrinterNetworkEthernet) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get('printer/network/ethernet')
    @property
    def dict(self): return self.raw
    @staticmethod
    def transform_raw(data): return data
    @property
    def connected(self): return self._ultimaker._get('printer/network/ethernet/connected')
    @property
    def enabled(self): return self._ultimaker._get('printer/network/ethernet/enabled')
    def __bool__(self): return self.connected

class NetworkMode(Enum):
    AUTO_CONNECT = "AUTO"
    HOTSPOT = "HOTSPOT"
    WIFI_SETUP = "WIFI SETUP"
    CABLE = "CABLE"
    WIRELESS = "WIRELESS"
    OFFLINE = "OFFLINE"

class PrinterNetworkWifi:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, PrinterNetworkWifi) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get('printer/network/wifi')
    @property
    def dict(self): return self.raw
    @staticmethod
    def transform_raw(data):
        data['mode'] = NetworkMode(data['mode'])
        if data['ssid'] == 'UM-NO-HOTSPOT-NAME-SET': data['ssid'] = None
        return data
    @property
    def connected(self): return self._ultimaker._get('printer/network/wifi/connected')
    @property
    def enabled(self): return self._ultimaker._get('printer/network/wifi/enabled')
    @property
    def mode(self): return NetworkMode(self._ultimaker._get('printer/network/wifi/mode'))
    @property
    def ssid(self):
        ssid = self._ultimaker._get('printer/network/wifi/ssid')
        return None if ssid == 'UM-NO-HOTSPOT-NAME-SET' else ssid
    def __bool__(self): return self.connected

class PrinterNetworkWifiNetwork:
    def __init__(self, data): self._data = data
    def __eq__(self, other):
        return isinstance(other, PrinterNetworkWifiNetwork) and self._data == other._data
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return copy.deepcopy(self._data)
    @property
    def dict(self): return copy.deepcopy(self._data)
    @property
    def ssid(self): return self._data['ssid']
    @property
    def connected(self): return self._data['connected']
    @property
    def security_required(self): return self._data['security_required']
    @property
    def strength(self): return self._data['strength']

class PrinterNetworkWifiNetworks(_Mapping):
    # NOTE: this likely is only ever 0 or 1 elements in length, see statement about putting below
    _subtype = PrinterNetworkWifiNetwork
    def __init__(self, ultimaker): super().__init__(ultimaker, 'printer/network/wifi_networks')
    @classmethod
    def _get_key(cls, value): return value.ssid

    # My reading of the connectToWifiNetwork and __startConnection functions in
    # network/networkController.py suggest that a network can only be added when in "setup mode" and
    # adding a network erases all previous networks.
    def add(self, ssid, passphrase=None):
        self._ultimaker._put('%s/%s'%(self._base, ssid),
                             data=(None if passphrase is None else {'passphrase':passphrase}))
        self._len = -1

class PrintJobResult(Enum):
    FAILED = "Failed"
    ABORTED = "Aborted"
    FINISHED = "Finished"

class PrintJobState(Enum):
    NO_JOB = "none"
    PRINTING = "printing"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    PRE_PRINT = "pre_print"
    POST_PRINT = "post_print"
    WAIT_CLEANUP = "wait_cleanup"
    WAIT_USER_ACTION = "wait_user_action"
    UNKNOWN = "unknown"

class PrintJobPauseSources(Enum):
    UNKNOWN = "unknown"
    GCODE = "gcode"
    DISPLAY = "display"
    FLOW = "flowsensor"
    PRINTER = "printer"
    API = "api"

class PrintJob:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, PrintJob) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    def submit(self, gcode, name=None):
        return self._ultimaker._post_file('print_job', gcode, {'jobname':name} if name else None)
    @property
    def raw(self): return self._ultimaker._get('print_job')
    @property
    def dict(self):
        info = self.raw
        info['datetime_started'] = _dt(info['datetime_started'])
        info['datetime_finished'] = _dt(info['datetime_finished'])
        info['datetime_cleaned'] = _dt(info['datetime_cleaned'])
        info['time_elapsed'] = datetime.timedelta(seconds=info['time_elapsed'])
        info['time_total'] = datetime.timedelta(seconds=info['time_total'])
        return info
    @property
    def name(self): return self._ultimaker._get('print_job/name')
    @property
    def datetime_started(self): return _dt(self._ultimaker._get('print_job/datetime_started'))
    @property
    def datetime_finished(self): return _dt(self._ultimaker._get('print_job/datetime_finished'))
    @property
    def datetime_cleaned(self): return _dt(self._ultimaker._get('print_job/datetime_cleaned'))
    @property
    # can be WEB_API/?, WEB_API, USB, CALIBRATION_MENU, Reboot, Unknown, or "", TODO: anything else?
    def source(self): return self._ultimaker._get('print_job/source')
    @property
    def source_user(self): return self._ultimaker._get('print_job/source_user')
    @property
    def source_application(self): return self._ultimaker._get('print_job/source_application')
    @property
    def uuid(self): return self._ultimaker._get('print_job/uuid')
    @property
    def reprint_original_uuid(self): return self._ultimaker._get('print_job/reprint_original_uuid')
    @property
    def time_elapsed(self):
        return datetime.timedelta(seconds=self._ultimaker._get('print_job/time_elapsed'))
    @property
    def time_total(self):
        return datetime.timedelta(seconds=self._ultimaker._get('print_job/time_total'))
    @property
    def progress(self): return self._ultimaker._get('print_job/progress')
    @property
    def gcode(self): return self._ultimaker._get_file('print_job/gcode')
    @property
    def container(self): return self._ultimaker._get_file('print_job/container')
    @property
    def pause_source(self):
        return PrintJobPauseSources(self._ultimaker._get('print_job/pause_source'))
    @property
    def state(self): return PrintJobState(self._ultimaker._get('print_job/state'))
    def pause(self): return self._ultimaker._put('print_job/state', {'target':'pause'})
    def resume(self): return self._ultimaker._put('print_job/state', {'target':'print'})
    def abort(self): return self._ultimaker._put('print_job/state', {'target':'abort'})
    @property
    def result(self):
        res = self._ultimaker._get('print_job/result')
        return None if res is "" else PrintJobResult(res)

class History:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, History) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    @property
    def print_jobs(self): return HistoryPrintJobs(self._ultimaker)
    @property
    def events(self): return HistoryEvents(self._ultimaker)
    def events_by_type(self, type_id):
        return HistoryEvents(self._ultimaker, HistoryEventTypeId(type_id).value)

class _HistorySeq:
    # pylint: disable=not-callable
    _subtype = None
    def __init__(self, ultimaker, base):
        self._ultimaker = ultimaker
        self._base = base + ('?' if '?' not in base else '&') + 'offset=%d&count=%d'
    def __eq__(self, other):
        return isinstance(other, _HistorySeq) and \
            self._ultimaker == other._ultimaker and self._base == other._base
    def __ne__(self, other): return not self == other
    # not a real Sequence since it doesn't support __len__
    # __iter__ produces values
    # __getitem__ takes pos. integer indices or slices (with a pos. start, stop, and a step of 1)
    def __iterate(self, start, stop, max_count=50):
        # gets max_count at a time, can iterate over the entire dataset is stop is None
        off = start
        while stop is None or off < stop:
            size = max_count if stop is None else min(max_count, stop - off)
            data = self._ultimaker._get(self._base%(off, size))
            if not data: break
            for elem in data: yield self._subtype(elem)
            off += size
    def __iter__(self): return self.__iterate(0, None)
    def __getitem__(self, idx):
        if isinstance(idx, slice):
            if idx.step is not None and idx.step != 1: raise IndexError()
            start, stop = idx.start or 0, idx.stop
            if start < 0 or (stop is not None and (stop < 0 or stop <= start)): raise IndexError()
            return list(self.__iterate(start, stop))
        return self._subtype(self._ultimaker._get(self._base%(idx, 1))[0])

class HistoryPrintJob:
    def __init__(self, data): self.__data = data
    def __eq__(self, other):
        return isinstance(other, HistoryPrintJob) and self.__data == other.__data
    def __ne__(self, other): return not self == other
    def __repr__(self): return 'HistoryPrintJob(%r)'%self.__data
    @property
    def raw(self): return copy.deepcopy(self.__data)
    @property
    def dict(self):
        info = self.raw
        info['time_elapsed'] = datetime.timedelta(seconds=info['time_elapsed'])
        info['time_estimated'] = datetime.timedelta(seconds=info['time_estimated'])
        info['time_total'] = datetime.timedelta(seconds=info['time_total'])
        info['datetime_started'] = _dt(info['datetime_started'])
        info['datetime_finished'] = _dt(info['datetime_finished'])
        info['datetime_cleaned'] = _dt(info['datetime_cleaned'])
        return _extract(info, 'uuid', 'name', 'time_elapsed', 'time_estimated', 'time_total',
                        'datetime_started', 'datetime_finished', 'datetime_cleaned', 'result',
                        'source', 'reprint_original_uuid')
    @property
    def name(self): return self.__data['name']
    @property
    def time_elapsed(self): return datetime.timedelta(seconds=self.__data['time_elapsed'])
    @property
    def time_estimated(self): return datetime.timedelta(seconds=self.__data['time_estimated'])
    @property
    def time_total(self): return datetime.timedelta(seconds=self.__data['time_total'])
    @property
    def datetime_started(self): return _dt(self.__data['datetime_started'])
    @property
    def datetime_finished(self): return _dt(self.__data['datetime_finished'])
    @property
    def datetime_cleaned(self): return _dt(self.__data['datetime_cleaned'])
    @property# Can only be "Aborted" or "Finished" here
    def result(self): return PrintJobResult(self.__data['result'])
    @property
    # can be WEB_API/?, WEB_API, USB, CALIBRATION_MENU, Unknown, or "", TODO: anything else?
    def source(self): return self.__data['source']
    @property
    def uuid(self): return self.__data['uuid']
    @property
    def reprint_original_uuid(self): return self.__data['reprint_original_uuid']

class HistoryPrintJobs(_HistorySeq):
    _subtype = HistoryPrintJob
    def __init__(self, ultimaker): super().__init__(ultimaker, 'history/print_jobs')
    # __getitem__ additionally supports taking keys (UUIDs)
    def __getitem__(self, idx):
        if isinstance(idx, str):
            return HistoryPrintJob(self._ultimaker._get('history/print_jobs/%s'%idx))
        return super().__getitem__(idx)

class HistoryEventTypeId(Enum):
    # pylint: disable=bad-whitespace
    #0x0000XXXX range, system related events
    SYSTEM_STARTUP     = 0x00000001
    CRITICAL_ERROR     = 0x00000002
    SYSTEM_RESET       = 0x00000003
    SYSTEM_MAINTENANCE = 0x00000004 # only user-enterable type

    #0x0001XXXX range, hotend related events
    HOTEND_CARTRIDGE_CHANGE = 0x00010000
    HOTEND_MATERIAL_CHANGE  = 0x00010001
    HOTEND_CARTRIDGE_REMOVE = 0x00010002

    #0x0002XXXX range, print related events
    PRINT_STARTED  = 0x00020000
    PRINT_PAUSED   = 0x00020001
    PRINT_RESUMED  = 0x00020002
    PRINT_ABORTED  = 0x00020003
    PRINT_FINISHED = 0x00020004
    PRINT_CLEARED  = 0x00020005

    #0x0010XXXX range, authentication related events
    AUTHENTICATION_KEYS_ADDED   = 0x00100000
    AUTHENTICATION_KEYS_REMOVED = 0x00100001

class MaintenanceAction(Enum):
    clean_printer = "clean_printer"
    lubricate_axles = "lubricate_axles"
    check_for_play_on_axles = "check_for_play_on_axles"
    check_tension_of_short_belts = "check_tension_of_short_belts"
    check_for_residue_in_front_fan_of_print_head = "check_for_residue_in_front_fan_of_print_head"
    check_quality_of_silicone_nozzle_cover = "check_quality_of_silicone_nozzle_cover"
    clean_print_cores = "clean_print_cores"
    lubricate_lead_screw_z_motor = "lubricate_lead_screw_z_motor"
    clean_feeders_and_replace_bowden_tubes = "clean_feeders_and_replace_bowden_tubes"
    #clean_feeders = "clean_feeders"
    #replace_bowden_tubes = "replace_bowden_tubes"
    #lubricate_feeder_gears = "lubricate_feeder_gears"
    #clean_system_fans = "clean_system_fans"
    #lubricate_door_hinges = "lubricate_door_hinges"

class HistoryEvent:
    # Type IDs (in hex) with messages and frequencies on xerox:
    #      1 92   System started
    #      3 1    Cleared all settings and history
    #      4 -    Something to do with maintenance (and possibly the only one allowed from the API)

    #  10000 5017 Hotend <0|1> changed to <??|AA|BB|CC & 0.25|0.4|0.8> with serial b'<6 chars>'
    #  10001 149  Hotend <1|2> material changed to <GUID> by <RFID|USER>
    #  10002 5020 Hotend <1|2> removed

    #  20000 523  Print <UUID> started with name <NAME>
    #  20001 57   Print <UUID> paused
    #  20002 21   Print <UUID> resumed
    #  20003 159  Print <UUID> aborted
    #  20004 206  Print <UUID> finished
    #  20005 522  Print <UUID> cleared

    # 100000 11   API Authentication added for application: <APP> user: <USER> with id: <ID>
    # 100001 3    API Authentication removed for application: <APP> user: <USER> with id: <ID>

    #             Last two have parameters [<ID>, <APP>, <USER>]
    #             All others have parameters in the order they appear
    def __init__(self, data): self.__data = data
    def __eq__(self, other): return isinstance(other, HistoryEvent) and self.__data == other.__data
    def __ne__(self, other): return not self == other
    def __repr__(self): return 'HistoryEvent(%r)'%self.__data
    @property
    def raw(self): return copy.deepcopy(self.__data)
    @property
    def dict(self):
        info = self.raw
        info['time'] = _dt(info['time'])
        info['type_id'] = HistoryEventTypeId(info['type_id'])
        return _extract(info, 'time', 'type_id', 'message', 'parameters')
    @property
    def time(self): return _dt(self.__data['time'])
    @property
    def type_id(self): return HistoryEventTypeId(self.__data['type_id'])
    @property
    def message(self): return self.__data['message']
    @property
    def parameters(self): return self.__data['parameters']

class HistoryEvents(_HistorySeq):
    _subtype = HistoryEvent
    def __init__(self, ultimaker, type_id=None):
        super().__init__(ultimaker, 'history/events' +
                         ('' if type_id is None else '?type_id=%d'%type_id))
    def post(self, type_id, *parameters):
        self._ultimaker._post('history/events', {
            'type_id':HistoryEventTypeId(type_id).value, 'parameters':parameters
        })
    def post_maintenance(self, action, mechanic=None):
        action = MaintenanceAction(action).value
        if mechanic is None:
            self.post(HistoryEventTypeId.SYSTEM_MAINTENANCE, action)
        else:
            self.post(HistoryEventTypeId.SYSTEM_MAINTENANCE, action, mechanic)

class System:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, System) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get('system')
    @property
    def dict(self):
        info = self.raw
        del info['log'], info['display_message']
        info['time'] = datetime.datetime.utcfromtimestamp(info['time']['utc'])
        info['uptime'] = datetime.timedelta(seconds=info['uptime'])
        return info
    @property
    def platform(self): return self._ultimaker._get('system/platform')
    @property
    def hostname(self): return self._ultimaker._get('system/hostname')
    @property
    def firmware(self): return SystemFirmware(self._ultimaker)
    @property
    def memory(self): return SystemMemory(self._ultimaker)
    @property
    def time(self):
        return datetime.datetime.utcfromtimestamp(self._ultimaker._get('system/time/utc'))
    def log(self, boot=0, lines=50):
        return self._ultimaker._get('system/log?boot=%d&lines=%d'%(boot, lines))
    @property
    def name(self): return self._ultimaker._get('system/name')
    @name.setter
    def name(self, value): self._ultimaker._put('system/name', value)
    @property
    def country(self): return self._ultimaker._get('system/country')
    @country.setter
    def country(self, value): self._ultimaker._put('system/country', value)
    @property
    def language(self): return self._ultimaker._get('system/language')
    @property
    def uptime(self): return datetime.timedelta(seconds=self._ultimaker._get('system/uptime'))
    @property
    def type(self): return self._ultimaker._get('system/type')
    @property
    def variant(self): return self._ultimaker._get('system/variant')
    @property
    def hardware(self): return SystemHardware(self._ultimaker)
    @property
    def guid(self): return self._ultimaker._get('system/guid')
    def display_message(self, message, button_caption):
        return self._ultimaker._put('system/display_message',
                                    {'message':message, 'button_caption':button_caption})

class SystemMemory:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, SystemMemory) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get('system/memory')
    @property
    def dict(self): return self.raw
    @property
    def total(self): return self._ultimaker._get('system/memory/total')
    @property
    def used(self): return self._ultimaker._get('system/memory/used')

class SystemHardware:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, SystemHardware) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get('system/hardware')
    @property
    def dict(self): return self.raw
    @property
    def revision(self): return self._ultimaker._get('system/hardware/revision')
    @property
    def typeid(self): return self._ultimaker._get('system/hardware/typeid')

class SystemFirmwareUpdateStatus(Enum):
    IDLE = "IDLE"
    INIT_DOWNLOAD = "INIT_DOWNLOAD"
    DOWNLOADING = "DOWNLOADING"
    COPYING = "COPYING"
    VERIFYING = "VERIFYING"
    INSTALLING = "INSTALLING"
    FAILED_DOWNLOAD = "FAILED_DOWNLOAD"
    FAILED_USB = "FAILED_USB"
    FAILED_SIGNATURE = "FAILED_SIGNATURE"
    FAILED_VERSION_CHECK = "FAILED_VERSION_CHECK"
    FAILED_DOWNLOAD_INSUFFICIENT_SPACE = "FAILED_DOWNLOAD_INSUFFICIENT_SPACE"
    FAILED_PRE_UPDATE = "FAILED_PRE_UPDATE"

class SystemFirmware:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, SystemFirmware) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    def __str__(self): return self._ultimaker._get('system/firmware')
    @property
    def version(self): return self._ultimaker._get('system/firmware')
    def update(self, stable=True):
        return self._ultimaker._put('system/firmware', {
            'update_type':('stable' if stable else 'testing')
        })
    @property
    def status(self):
        return SystemFirmwareUpdateStatus(self._ultimaker._get('system/firmware/status'))
    @property
    def stable(self): return self._ultimaker._get('system/firmware/stable')
    @property
    def testing(self): return self._ultimaker._get('system/firmware/testing')

class Camera:
    def __init__(self, ultimaker): self._ultimaker = ultimaker
    def __eq__(self, other):
        return isinstance(other, Camera) and self._ultimaker == other._ultimaker
    def __ne__(self, other): return not self == other
    @property
    def raw(self): return self._ultimaker._get('camera')
    @property
    def dict(self):
        data = self.raw
        try:
            i = 0
            while True:
                data[i] = {'stream':self.stream(i), 'snapshot':self.snapshot(i)}
                i = i + 1
        except IndexError: pass
        return data
    @property
    def feed(self): return self._ultimaker._get('camera/feed')

    # These take indices and give redirects to the proper URLs
    def __get_redir(self, name, i):
        response = requests.get(self._ultimaker._url('camera/%d/%s'%(i, name)),
                                allow_redirects=False)
        if response.status_code == 302:
            return response.headers['Location']
        if response.json()['message'] == "Camera index not found": raise IndexError()
        raise ValueError()
    def stream(self, i): return self.__get_redir('stream', i)
    def snapshot(self, i): return self.__get_redir('snapshot', i)
