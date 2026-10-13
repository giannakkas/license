Barpi Monitor
=============

A video monitor for the newsroom: several streams or files side by side, each with
live audio level meters, a SILENCE alarm and a NO SIGNAL alarm.

Run BarpiMonitor.exe. Nothing is installed; settings are kept in
%APPDATA%\BarpiMonitor\config.json and a log in %APPDATA%\BarpiMonitor\monitor.log.

First run: Windows SmartScreen may say "Windows protected your PC" because the
program is not code-signed. Click "More info", then "Run anyway".

Adding sources
  Ctrl+N   add a stream: rtsp://  srt://  udp://@239.1.1.1:1234  rtmp://  https://.../index.m3u8
  Ctrl+O   add video files (they loop by default)
  or drag files / URLs onto the window
  You can also start it with sources on the command line:
      BarpiMonitor.exe rtsp://10.0.0.5/live "D:\clips\promo.mp4"

Listening
  Click a tile to hear it. Exactly one source is audible at a time; keys 1-9
  switch. "Mute all" silences the speakers but the meters keep working.
  "Audio out" picks the sound device.

Meters (dBFS)
  Wide bar  = peak level, instant rise, slow fall (PPM style)
  Inner bar = RMS
  White line = peak hold, with the held value printed above the bar
  Green up to -18 dBFS (EBU alignment level), amber to -9 dBFS (maximum
  permitted level), red above. OVER lights when a sample hits full scale.
  Under each tile: EBU R128 momentary (M) and short-term (S) loudness in LUFS.
  5.1 and other multichannel sources show one bar per channel.

Alarms (tile flashes red, listed in the status bar, counted in the title)
  SILENCE    every channel under the threshold (default -50 dBFS) for 10 s
  NO SIGNAL  the stream dropped, errored or stalled; it reconnects by itself
  Settings (Ctrl+,) change thresholds, timing and an optional beep.

Keys
  1-9 listen to tile    M mute all      Enter/double-click show one tile
  F2 edit   Del remove   F5 restart     F11 full screen   Esc back   F1 help
