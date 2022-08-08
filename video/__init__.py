"""
Starts and pauses video streaming on-demand.

This uses a ram-disk to serve files from to avoid excessive SD card writes on a
Raspberry Pi.
"""

# Resource usage:
# VLC: (ffmpeg likely to be similar since it uses the same core library)
#   ~1.50GiB per stream  virtual
#   ~0.22GiB per stream  reserved
#   30-50% CPU per stream
# Server:
#   ~250 MiB virtual
#   ~25kb reserved
#   0% CPU usage

import os
import errno
import asyncio
import subprocess
from time import time

from tornado.web import StaticFileHandler, HTTPError
from tornado.ioloop import PeriodicCallback

from printers import PrinterHandlerMixin

try:
    import aiofiles
    have_aiofiles = True
except ImportError:
    have_aiofiles = False

DEFAULT_CONF = {
    'tmp': '/dev/shm/vid-stream',
    'keep-alive': 60,
}

streams = {}
stream_terminator = None


async def start_streaming(printer, path):
    """
    Starts the streaming service for the given printer. This function is
    asynchronous and must be used with await since it doesn't complete until
    the service has completely started.
    """

    # Ensure path exists
    if have_aiofiles: await os.makedirs(path, exist_ok=True)
    else: os.makedirs(path, exist_ok=True)

    # Get the video's files
    m3u8 = printer.name + '.m3u8'
    m3u8_full = os.path.join(path, m3u8)

    # Remove evidence of previous streaming
    try:
        if have_aiofiles: await os.remove(m3u8_full)
        else: os.remove(m3u8_full)
    except OSError as ex:
        if ex.errno != errno.ENOENT: raise

    print('Starting stream for '+printer.name+'...')
    # TODO: base conversions needed off of video type
    # e.g. could be HLS already and RTSP may not need transcoding
    # FFMPEG: https://www.ffmpeg.org/ffmpeg-formats.html#hls-2
    proc = subprocess.Popen((
        'ffmpeg', '-hide_banner', '-nostats', '-loglevel', 'error',
        '-i', printer.video_url,
        '-c:v', 'h264', '-profile:v', 'high', '-level', '4.1',
        '-an', '-flags', '+cgop', '-g', '30', '-pix_fmt', 'yuv420p',
        '-hls_time', '2', '-hls_list_size', '3',
        '-hls_flags', 'delete_segments', '-f', 'hls', m3u8
    ), cwd=path)

    # Wait for the streaming to begin
    while not os.path.isfile(m3u8_full):  # TODO: could use aiofiles
        await asyncio.sleep(0.001)

    # Return the process so it can be terminated later
    return proc


def terminate_video_streams(stale_secs=None):
    """Terminate all (stale) streams."""
    stale = None if stale_secs is None else time() - stale_secs
    for name, info in streams.copy().items():
        if stale is None or info[1] < stale:
            print("Stopping stream for "+name+"...")
            info[0].terminate()
            del streams[name]


class VideoStaticFileHandler(StaticFileHandler, PrinterHandlerMixin):  # pylint: disable=abstract-method
    def initialize(self, **kwargs):
        super().initialize(self.get_config('tmp'), **kwargs)

    def get_config(self, name):
        val = self.settings['config'].get('VIDEO', name, fallback=None)
        return DEFAULT_CONF[name] if val is None else val


class VideoHandler(VideoStaticFileHandler):  # pylint: disable=abstract-method
    """Handles *.m3u8 links which start the streaming service."""

    async def get(self, name, include_body=True):  # pylint: disable=arguments-differ
        # Make sure the terminator has started
        global stream_terminator
        if stream_terminator is None:
            keep_alive = int(self.get_config('keep-alive'))
            stream_terminator = PeriodicCallback(
                lambda: terminate_video_streams(keep_alive*2), keep_alive*1000)
            stream_terminator.start()
        
        if name not in streams:
            # Streaming not currently running, start it
            printer = self.get_printer(name)
            if not printer.supports_video: raise HTTPError(400)
            streams[name] = [None, time()]
            proc = await start_streaming(printer, self.root)
            streams[name] = [proc, time()]
        else:
            while streams[name] is None:
                # Stream is being started right now, wait a little bit
                await asyncio.sleep(0.001)
            
            # Stream is started, update last time accessed
            streams[name][1] = time()

        await super().get(name+'.m3u8', include_body)
