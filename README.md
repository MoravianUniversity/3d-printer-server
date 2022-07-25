3D Printer Information Server
=============================

This server interfaces with the Ultimaker printers to provide some additional features and nice interfaces. It is broken into a few categories: video, model, and dashboard.

This program requires Tornado and requests libtraris which you can install with `pip install tornado requests`. Optionally requires `aiofiles` (for improved asynchronous operations) and `trimesh` (for OBJ models). Video streaming requires the `ffmpeg` program.

Installation
------------

On a fresh Raspbian installation, ssh into the machine and do the following to fully setup the server (`ffmpeg` and `trimesh` are optional):

```shell
sudo apt-get install python3 ffmpeg  # Raspbian
#brew install python3 ffmpeg  # macOS
python3 -m venv ~/3d-print-server
cd ~/3d-print-server
. bin/activate
pip install tornado requests aiofiles trimesh
git clone https://github.com/MoravianCollege/3d-printer-server.git
cd 3d-printer-server
git submodule init
git submodule update
sudo cp 3d-print-server.service /etc/systemd/system  # Raspbian
sudo systemctl enable 3d-print-server  # Raspbian
sudo systemctl start 3d-print-server  # Raspbian
#sudo cp 3d-print-server.plist /Library/LaunchDaemons  # macOS
#launchctl load /Library/LaunchDaemons/3d-print-server.plist  # macOS
```

To setup the kiosk display on Raspbian:

```shell
sudo apt-get install mesa-utils unclutter
sudo raspi-config
        Advanced Options > GL Driver > GL (Full KMS)
        Performance Options > GPU Memory > 256
        Finish and Reboot
mkdir -p ~/.config/lxsession/LXDE-pi
cp /etc/xdg/lxsession/LXDE-pi/autostart ~/.config/lxsession/LXDE-pi/autostart
cat >>~/.config/lxsession/LXDE-pi/autostart <<EOF
@xset s off
@xset -dpms
@xset s noblank
@unclutter -root
@chromium --kiosk --app=http://localhost:8888/display
EOF
nano ~/.config/lxsession/LXDE-pi/autostart
        Comment out @xscreensaver -no-splash by placing a # in front
        The other lines before @xset can likely be commented out as well
```

Setting Up Printers
-------------------

The config.ini file specifies the known printers and their settings along with a few global settings.

Each printer gets its own section (e.g. `[xerox]`). Each printer should have at least a `type=` entry so that it is usable. The types can be any of the known printer types in printers.py and js/printers.js (see the `TYPE` fields in the classes there).

The default `Printer` type only knows how to stream video if there is a `video=` entry with a URL to the video stream. It can also have a link to an online portal with `portal=`. It is unable to do anything else with the printer (no status, models, etc).

Additional subclasses of `Printer` are provided that support more features for other types of printers. The known types are:

* `ultimaker` - only requires `hostname=` entry (no `video=` or `portal=`, although those will be used if provided), supports all features (video, models, status, portal link, ...)
* `octopi` - only requires `hostname=` and `apikey=` entries (no `video=` or `portal=`, although those will be used if provided), supports all features (video, models, status, portal link, ...)

Other printer types can be added as classes there.

Streaming Video
---------------

Available as HLS stream at `/video/<printer name>.m3u8` and an example/embeddable webpage at `/video/<printer name>.html`. Most printers produce either MJPEG or RTSP. HLS is an alternative (RTSP can't be used in the browser at all, MJPEG can sometimes be unstable).

Many browsers cannot play HLS directly so you need to include the [hls.js](https://github.com/video-dev/hls.js/) library to provide support. See the example webpage for details. The example webpage is also designed to be placed in an iframe and embedded if you choose to go that route.

The streaming server starts the first time the `m3u8` file is requested which may take a second or two. If that file has not been requested for 2-3 minutes the streaming server shuts down.

Model Files
-----------

You can request the raw GCODE file for the currently or most recently printed model along with the model converted to OBJ or a special JSON format with the following:

```
/model/<printer name>.gcode
/model/<printer name>.obj
/model/<printer name>.json
```

Like with streaming video, there is an example/embeddable webpage (which uses the JSON file):

```
/model/<printer name>.html
```

Dashboard and Display
---------------------
TODO: Coming soon.

A simple dashboard for 2 printers is also provided as `/dashboard`. Doesn't include video stream (designed to be used near the printers).

Currently the dashboard has hard-coded printer names/addresses.

Additional dashboards are planned:

* General Dashboard - includes video stream
* Admin Dashboard - includes general dashboard but with options to pause, resume, and abort the current print job; also has authentication
