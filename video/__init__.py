#!/usr/bin/env python3
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

import time
import asyncio
import subprocess
import os
import errno

import tornado.web

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


async def start_streaming(app, path, name):
    """
    Starts the streaming service for the given printer. This function is
    asynchronous and must be used with await since it doesn't complete until
    the service has completely started.
    """

    # Ensure path exists
    if have_aiofiles:
        await os.makedirs(path, exist_ok=True)
    else:
        os.makedirs(path, exist_ok=True)

    # Get the video's url
    if name not in app.config: raise tornado.web.HTTPError(404)
    config = app.config[name]
    if 'video' not in config: raise tornado.web.HTTPError(404)
    url = config['video']
    m3u8 = name + '.m3u8'
    m3u8_full = os.path.join(path, m3u8)

    # Remove evidence of previous streaming
    try:
        if have_aiofiles:
            await os.remove(m3u8_full)
        else:
            os.remove(m3u8_full)
    except OSError as ex:
        if ex.errno != errno.ENOENT:
            raise

    print('Starting stream for '+name+'...')
    # FFMPEG: https://www.ffmpeg.org/ffmpeg-formats.html#hls-2
    proc = subprocess.Popen((
        'ffmpeg', '-hide_banner', '-nostats', '-loglevel', 'warning', '-i', url,
        '-c:v', 'h264', '-profile:v', 'high', '-level', '4.1',
        '-an', '-flags', '+cgop', '-g', '30',
        '-hls_time', '2', '-hls_list_size', '3', '-hls_flags', 'delete_segments',
        '-f', 'hls', m3u8
    ), cwd=path)

    # Wait for the streaming to begin
    while not os.path.isfile(m3u8_full):  # TODO: could use aiofiles
        await asyncio.sleep(0.001)

    # Return the process so it can be terminated later
    return proc


def terminate_streams(stale_secs=None):
    """Terminate all (stale) streams."""
    stale = None if stale_secs is None else time.time() - stale_secs
    for name, info in streams.copy().items():
        if stale is None or info[1] < stale:
            print("Stopping stream for "+name+"...")
            info[0].terminate()
            del streams[name]


class VideoStaticFileHandler(tornado.web.StaticFileHandler):  # pylint: disable=abstract-method
    def initialize(self, **kwargs):
        super().initialize(self.get_config('tmp'), **kwargs)

    def get_config(self, name):
        val = self.application.config.get('VIDEO', name, fallback=None)
        return DEFAULT_CONF[name] if val is None else val


class VideoHandler(VideoStaticFileHandler):  # pylint: disable=abstract-method
    """Handles *.m3u8 links which start the streaming service."""

    async def get(self, name, include_body=True):  # pylint: disable=arguments-differ

        # Make sure the terminator has started
        global stream_terminator
        if stream_terminator is None:
            keep_alive = int(self.get_config('keep-alive'))
            stream_terminator = tornado.ioloop.PeriodicCallback(
                lambda: terminate_streams(keep_alive*2), keep_alive*1000)
            stream_terminator.start()
        
        if name not in streams:
            # Streaming not currently running, start it
            streams[name] = [None, time.time()]
            proc = await start_streaming(self.application, self.root, name)
            streams[name] = [proc, time.time()]
        else:
            while streams[name] is None:
                # Stream is being started right now, wait a little bit
                await asyncio.sleep(0.001)
            
            # Stream is started, update last time accessed
            streams[name][1] = time.time()

        await super().get(name+'.m3u8', include_body)
