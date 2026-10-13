Monitoring Application (BarpiMonitor.exe)
==========================================

A video monitor for the newsroom: several streams or files side by side, each with
live audio level meters, a SILENCE alarm and a NO SIGNAL alarm.

Run BarpiMonitor.exe. On the first start it asks for the licence key
(ONCUE-XXXXX-XXXXX-XXXXX-XXXXX) that was issued on player.oncue.cy; the key is
checked online and this computer is registered to it. From then on the program
checks in every 5 minutes. If the licence or this computer is locked on the
platform, a red LOCKED screen replaces the video and playback stops until it is
unlocked. Without internet the program keeps working for 3 days on its last
answer. Help > Licence shows the status; Licence > Deactivate frees the seat.

Computers with no internet at all use an offline licence file instead: send the
Computer ID shown on the activation screen (Copy ID) to your supplier, who issues
a .lic file for that computer on player.oncue.cy. Copy it over by USB and click
"Import licence file...". The file works on that computer only, until the expiry
date printed in Help > Licence; ask for a new file to extend it. Setting the
computer's clock back to before the program last ran locks it until the clock
is right again.

Nothing is installed; settings are kept in
%APPDATA%\BarpiMonitor\config.json and a log in %APPDATA%\BarpiMonitor\monitor.log.

First run: Windows SmartScreen may say "Windows protected your PC" because the
program is not code-signed. Click "More info", then "Run anyway".

Adding sources
  Ctrl+N   add a stream: rtsp://  srt://  udp://@239.1.1.1:1234  rtmp://  https://.../index.m3u8
  Ctrl+O   add video files (they loop by default)
  or drag files / URLs onto the window
  You can also start it with sources on the command line:
      BarpiMonitor.exe rtsp://10.0.0.5/live "D:\clips\promo.mp4"

Playback
  Each tile has Play/Pause, Stop and Loop buttons and a position bar (files only).
  Space       play / pause the selected tile       Ctrl+Space  pause / resume everything
  Left/Right  seek 5 s (Shift: 30 s)               Home        back to the start
  F5 restarts the selected source from the beginning.

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

Alarms are red everywhere: the tile turns red and flashes, the alarm name is shown
in red on the video, the status bar and the alarm log list it in red, and every
start and end is written to alarms.csv
  NO SIGNAL   the stream dropped, errored or stalled; it reconnects by itself
  NO VIDEO    no picture can be read for 5 s
  FROZEN      the picture has not changed for 10 s
  BLACK       the picture has stayed dark for 5 s
  OVER        a sample hit full scale (clipping)
  TOO LOUD    short-term loudness over -18 LUFS for 3 s, or 3 peaks at -3 dBFS in 10 s
  SILENCE     every channel under -50 dBFS for 10 s
  L / R MISSING  one channel silent for 10 s while the other carries sound
  LOW LEVEL   the loudest channel under -30 dBFS for 30 s
  All thresholds and times are in Settings (Ctrl+,); each source can switch its
  silence, level and picture alarms off (Edit, F2). Optional beep in Settings.

Keys
  1-9 listen to tile    M mute all      Enter/double-click show one tile
  F2 edit   Del remove   F5 restart     Ctrl+L alarm log  F11 full screen
  Esc back  F1 help
