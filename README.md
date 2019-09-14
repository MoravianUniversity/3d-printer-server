3D Printer Information Server
=============================

This server interfaces with the Ultimaker printers to provide some additional features and nice interfaces. It is broken into a few categories: video, model, and dashboard.

This program requires Tornado which you can install with `pip install tornado`. Video streaming requires `VLC` (although with some small amount of changes could use `ffmpeg`).

The video script assumes how to translate a name to a URL based on Moravian's setup but this will be addressed eventually. There may be a similar problem with the models as well.


Installation
------------

On a fresh Rasbian installation, ssh into the machine and do the following:

```
apt-get install virtualenv vlc
virtualenv -p `which python3` 3d-printer-server
cd 3d-printer-server
. bin/activate
pip install tornado
git clone https://github.com/MoravianCollege/3d-printer-server.git server
cd server
sudo cp 3d-printer-server.service /etc/systemd/system
sudo systemctl enable 3d-printer-server
sudo systemctl start 3d-printer-server

cat >>~/.config/lxsession/LXDE-pi/autostart <<EOF
@xset s off
@xset -dpms
@xset s noblank
@chromium --kiosk --start-fullscreen --disable-restore-session --disable-session-crashed-bubble http://localhost:8888/dashboard
EOF
```


Streaming Video
---------------

Streaming Video:

```
/video/<printer name>.m3u8
```

and example/embeddable webpage:

```
/video/<printer name>.html
```

The streaming video from the Ultimaker printer is converted from MJPEG to [HLS](https://en.wikipedia.org/wiki/HTTP_Live_Streaming) so that it is a bit more robust.

Many browsers cannot play the streaming video directly so you need to include the [hls.js](https://github.com/video-dev/hls.js/) library to provide support. See the example webpage for details. The example webpage is also designed to be placed in an iframe and embedded if you choose to go that route.

The streaming server starts the first time the `m3u8` file is requested which may take a second or two. If that file has not been requested for 2-3 minutes the streaming server shuts down.

Model Files
-----------

OBJ File:

```
/model/<printer name>.obj
```

and example/embeddable webpage:

```
/model/<printer name>.html
```

This provides a 3D model of the current or last object being printed. It is in the ubiquitous OBJ format. This server also supplies some code for displaying OBJ files in `<canvas>` elements.

This service depends on a plugin being installed in Cura. The plugin sends the OBJ file to the server whenever Cura is asked to send a print job to the printer.

Dashboard
---------
A simple dashboard for 2 printers is also provided as `/dashboard`. Doesn't include video stream (designed to be used near the printers).

Currently the dashboard has hard-coded printer names/addresses.

Additional dashboards are planned:
* General Dashboard - includes video stream
* Admin Dashboard - includes general dashboard but with options to pause, resume, and abort the current print job; also has authentication
