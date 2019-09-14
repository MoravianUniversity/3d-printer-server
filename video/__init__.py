#!/usr/bin/env python3
"""Starts and pauses video streaming on-demand"""

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
import threading
import os
import errno

import tornado.web

cwd = os.path.dirname(os.path.abspath(__file__))
streams = {}

async def start_streaming(name):
    """
    Starts the streaming service for the given printer. This function is asynchronous and must be
    used with await since it doesn't complete until the service has completely started.
    """
    # pylint: disable=line-too-long
    # TODO: dynamic URL
    url = 'http://'+name+'.cslab.moravian.edu:8080/?action=stream'
    m3u8 = name + '.m3u8'
    m3u8_full = os.path.join(cwd, m3u8)

    # Remove evidence of previous streaming
    try:
        # could be made asynchronous with aiofiles, but shouldn't really block for long
        os.remove(m3u8_full)
    except OSError as ex:
        if ex.errno != errno.ENOENT:
            raise

    # VLC: https://wiki.videolan.org/Documentation:Streaming_HowTo/Streaming_for_the_iPhone/
    print('Starting stream for '+name+'...')
    proc = subprocess.Popen([
        'vlc', '-I', 'dummy', '--play-and-exit', url, '--sout',
        '#transcode{vcodec=h264,venc=x264{profile=high,ref=1,keyint=10,level=41},acodec=none}' +
        ':std{access=livehttp{index='+m3u8+',delsegs=true,numsegs=3,seglen=2,index-url='+name+'-#######.ts},dst='+name+'-#######.ts,mux=ts{use-key-frames}}'
    ], cwd=cwd)
    # FFMPEG: https://www.ffmpeg.org/ffmpeg-formats.html#hls-2
    # proc = subprocess.Popen([
    #     'ffmpeg', '-i', url,
    #     '-c:v', 'h264', '-profile:v', 'high', '-level', '4.1', '-an', '-flags', '+cgop', '-g', '30',
    #     '-hls_time', '2', '-hls_list_size', '3', '-hls_flags', 'delete_segments', '-f', 'hls', m3u8
    # ], cwd=cwd)

    # Wait for the streaming to begin
    while not os.path.isfile(m3u8_full):
        await asyncio.sleep(0.001)

    # Return the process so it can be terminated later
    return proc

def terminate_streams(stale_secs=None):
    """Terminate all (stale) streams."""
    stale = None if stale_secs is None else time.time() - stale_secs
    for name, info in streams.items():
        if stale is None or info[1] < stale:
            print("Stopping stream for "+name+"...")
            info[0].terminate()
            del streams[name]

stream_terminator = tornado.ioloop.PeriodicCallback(lambda: terminate_streams(120), 60*1000)

class VideoHandler(tornado.web.StaticFileHandler): # pylint: disable=abstract-method
    """Handles *.m3u8 links which start the streaming service."""
    async def get(self, name, include_body=True): # pylint: disable=arguments-differ
        if not stream_terminator.is_running():
            stream_terminator.start()
        if name not in streams:
            # streaming not currently running, start it
            streams[name] = [None, time.time()]
            proc = await start_streaming(name)
            streams[name] = [proc, time.time()]
        else:
            while streams[name] is None:
                # stream is being started right now, wait a little bit
                await asyncio.sleep(0.001)
            # stream is started, update last time accessed
            streams[name][1] = time.time()
        await super().get(name+'.m3u8', include_body)
