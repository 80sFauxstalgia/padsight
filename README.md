# VSCView (OBS edition)

On-screen controller overlay for streams and videos, with first-class support for **both Steam Controllers**:
- the original 2015 controller;
- the 2026 controller.

OBS shows it as a **transparent Browser Source**, so no green screen or chroma key is needed.

This is a fork of [Nielk1/VSCView](https://github.com/Nielk1/VSCView). Every original theme and controller still works.

<!-- SCREENSHOT: hero image, docs/screenshots/hero.png. Both controllers side by side in OBS over gameplay (Graphite 2026 + Vaporwave 2015), no green fringe. -->

## Features
- **Real Steam Controller input.**
  - Both controllers: real trackpad touch positions and trails, and the rear grips / back buttons.
  - 2026 controller extras: trackpad pressure, capacitive thumbstick touch, all four back buttons (L4/L5/R4/R5) and grip sense.
- **True transparency in OBS.** VSCView streams its own rendering to a Browser Source over a local WebSocket, with no chroma-key fringing.
- **Control panel.** A setup guide, live controller cards, a theme gallery with previews, an OBS URL builder and plain-language status, in its own window. The same panel also works as an **OBS dock**.
- **Follow mode.** With both controllers connected, the overlay switches to the one you are using, along with the theme you last used for that kind of controller. One OBS source covers every game.
- **New themes:** Graphite and Vaporwave Pixel for both Steam Controllers.
- **Private by design.** The overlay server only listens on `127.0.0.1` (this PC) and sends nothing anywhere else.

## Quick start
1. Download the latest release zip, extract it anywhere, and run `VSCView.exe`.
   * Requires Windows 10 or 11. The .NET Framework 4.8 it needs is built in.
2. The control panel opens with a three-step setup: press a button on your controller, pick a look, add it to OBS.
3. Afterwards it lives in the tray. Click the tray icon to open the panel again; right-click it to exit.

The classic borderless window is still there for anyone who used it: turn on **Settings › Desktop preview window** in the panel. It's on by default if you used an earlier version.

<!-- SCREENSHOT: docs/screenshots/theme-browser.png. Theme Browser with the 2026 Graphite theme selected. -->

## Verify your download
GitHub Actions builds every release from this repository's source. Each release includes:
* `SHA256SUMS.txt` (and a `.sha256` file per zip). Check the zip matches before running it:
  ```powershell
  Get-FileHash .\VSCView-0.6.0-win-x64.zip -Algorithm SHA256
  ```
  The hash must equal the one listed in `SHA256SUMS.txt`.
* A **build provenance attestation**: a signed record of which repository, commit and workflow produced the file. Verify it with the [GitHub CLI](https://cli.github.com/):
  ```
  gh attestation verify VSCView-0.6.0-win-x64.zip --repo 80sFauxstalgia/vscview-overlay
  ```

**Code signing is planned but not active yet.** Releases will be Authenticode-signed for Talaria Software LLC through Azure Artifact Signing. Until then, Windows SmartScreen may warn the first time you run `VSCView.exe`. The checksum and the attestation above are the way to confirm the download is genuine.

## Adding it to OBS
1. In the control panel, open **OBS** and click **Copy** next to the URL. It also shows the width and height to use. The default URL is `http://127.0.0.1:47817/`.
2. In OBS, under **Sources**, click **+** › **Browser** › **Create new**. Then set:
   * **URL**: paste the URL.
   * **Width × Height**: the size shown on the OBS page, e.g. **1000 × 760** for the Graphite and Vaporwave themes.
   * **Custom CSS**: leave the default. The page is already transparent.
   * Optional: tick **Shutdown source when not visible**, so VSCView renders nothing while the overlay is off screen.
3. Click **OK**, then move and scale the source like any other.

<!-- SCREENSHOT: docs/screenshots/obs-properties.png. OBS Browser Source properties filled in. -->
<!-- SCREENSHOT: docs/screenshots/obs-scene.png. Overlay over gameplay in an OBS scene. -->

You can close the panel, but keep VSCView running in the tray. If VSCView closes, the source simply goes transparent, and it reconnects on its own when VSCView starts again.

### URL options
| Option | Example | What it does |
| --- | --- | --- |
| `theme` | `?theme=steamcontroller2026/graphite/Full.json` | Pins this source to one theme, independent of the app. The path is relative to the `themes` folder. Each theme card's **Copy URL** builds it for you. |
| `fps` | `&fps=30` | Render rate for this source (default 60). |
| `idle` | `&idle=8` | Fades the overlay out after 8 seconds without input, and back in on the next input. |
| `opacity` | `&opacity=0.8` | Overall opacity, from 0.1 to 1. |
| `crop` | `&crop=0,380,1000,380` | Shows only part of the theme: left, top, width, height in theme pixels. Set the source to that width and height. |
| `align` | `&align=bottom` | Where the image sits when the source's aspect ratio differs from the theme: `left`, `right`, `top` or `bottom`. |
| `status` | `&status=1` | Shows the connection status in a corner (troubleshooting). |

The panel's OBS page builds these for you, with a live preview. Several Browser Sources can show different themes at the same time; all of them follow the controller on the overlay.

### Control it from inside OBS (dock)
The control panel also works as an OBS dock. On the panel's OBS page, click **Copy dock URL**. In OBS, open **Docks › Custom Browser Docks**, name it, and paste the URL. The dock URL contains this PC's panel key, so paste it only into OBS and don't show it on stream.

### Settings
The panel's **Settings** page covers follow mode, per-controller themes, auto-select, the default frame rate, the accent colour and the desktop preview window. Port and background colour are in the classic dialog (the panel's **Port and background colour…** button, or right-click › **Settings…** in the preview window):
* **OBS Browser Source**: on/off, port, frame rate, the URL to copy, and live status (connected sources, render and encode time per frame).
* **Controllers**:
  * auto-select a lone controller;
  * follow the controller in use;
  * remember a theme per kind of controller.
* **Window**: background colour. This only matters for the old chroma-key workflow; OBS Browser Sources are transparent anyway.

<!-- SCREENSHOT: docs/screenshots/settings.png -->

## Controller notes
* **2026 Steam Controller.** VSCView reads it through [SDL3](https://www.libsdl.org/), over USB or the wireless puck.
  * It appears in the **Controller** menu as *Steam Controller (2026)*.
  * Its gyro and accelerometer are read and fused into an orientation, so themes with a gyro display tilt with the controller. Turn it off in the panel's **Settings** if you don't want it.
  <!-- VERIFY on hardware before release: "works while Steam is running with Steam Input enabled". -->
* **Original (2015) Steam Controller.** Read through VSCView's established HID decoder, as before. Its gyro is off by default because reading it changes a controller setting while VSCView runs; turn on **Settings › Gyro on the 2015 Steam Controller** in the panel to show it.
* **Skins follow the controller.** Each kind of controller (2015 or 2026 Steam Controller, Xbox/XInput, DualShock 4, DualSense) gets its own skin: the one you last picked while using it, or a built-in default. When follow mode switches controllers, the overlay switches skin with it.
* SDL3 is only allowed to touch the 2026 Steam Controller:
  * it never opens other gamepads, so it can't change their LEDs or rumble;
  * it ignores Steam's virtual Xbox controllers;
  * it leaves the 2015 controller to the HID decoder.

## Troubleshooting
* **Start here:** the panel's **Help & status** page explains every controller and OBS state and what to do next. **Copy diagnostics** puts a report on the clipboard for bug reports.
* **The panel window doesn't open.** It uses Microsoft Edge WebView2, which is built into Windows 11 and current Windows 10. Without it, the panel opens in your default browser instead.
* **The OBS source is empty.**
  * Check that VSCView is running and has a theme loaded.
  * Add `&status=1` to the URL to see whether it connects.
  * Open the URL in a normal browser: you should see the controller.
* **"Could not listen on 127.0.0.1:47817".** Another program is using the port. Pick another one in **Settings…** and update the URL in OBS.
* **The 2026 controller is not in the Controller menu.**
  * **Settings…** shows the SDL3 status line.
  * Make sure `SDL3.dll` is next to `VSCView.exe`.
  * Turn the controller on, or plug it in, while VSCView is running. It is detected within a second.
* **The overlay is on the wrong controller.** Press a button on the one you're using; follow mode switches after the other has been idle for 2 seconds. Or pick it from the **Controller** menu.
* **Diagnostics.** `http://127.0.0.1:47817/status.json` lists the detected controllers, which one is active and its live inputs, the SDL3 status, and per-source render timings.
* **CPU use.**
  * Rendering only happens while a source is connected, and unchanged frames are skipped.
  * Lower the frame rate in **Settings…** or with `&fps=30` if needed.

## Building from source
Requirements: Windows and the [.NET SDK](https://dotnet.microsoft.com/download), version 8 or newer. Then:

```
git clone --recursive https://github.com/80sFauxstalgia/vscview-overlay
cd vscview-overlay
dotnet build VSCView.sln -c Release
```

The output lands in `VSCView/bin/Release/net462/`.

On the first build, MSBuild downloads the official SDL3 release:
* `SDL3-3.4.20-win32-x64.zip` from `github.com/libsdl-org/SDL`;
* it is checked against a pinned SHA-256 before use (see `VSCView/VSCView.csproj`).

To make a release zip, run `powershell -ExecutionPolicy Bypass -File tools\package.ps1`. It writes `dist/VSCView-<version>-win-x64.zip` and a `.sha256` file.

The Graphite and Vaporwave Pixel themes are generated by Python scripts in `tools/theme-gen/` (needs Pillow: `pip install pillow`). Re-run them after changing the layout or colours.

Theme authors: [THEMEENGINE.md](THEMEENGINE.md) documents every element type and every controller's inputs, including the 2026 controller's `stick_touch`, `grip2`, `grip_sense`, `qam` and `touch_*:0:pressure`.

## Credits and licenses
This edition is developed and published by **Talaria Software LLC**. It is released under the MIT License, keeping the original copyright notice (see [LICENSE](LICENSE)):
```
Copyright (c) 2018-2021 John Klein
Copyright (c) 2026 Talaria Software LLC
```

* **[VSCView](https://github.com/Nielk1/VSCView)** and **[ExtendInput](https://github.com/Nielk1/ExtendInput)** by Nielk1 (John Klein), MIT. This project is a fork. The rendering, the theme engine and the original Steam Controller support are their work.
* Every bundled library and its license is listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
* Theme authors are credited in the list below and in each theme's `theme.json`.
* **[SDL3](https://www.libsdl.org/)**, zlib license. It is downloaded at build time and its license ships as `licenses/SDL3.txt`.
* **[SDL3-CS](https://github.com/flibitijibibo/SDL3-CS)** C# bindings, zlib license. They are vendored unmodified in `VSCView/ThirdParty/SDL3-CS/`.
* The 2026 controller's input mapping follows SDL's `SDL_hidapi_steam_triton.c`. It was cross-checked against [Steam-Controller-Gamepad-Viewer by ramonchi5](https://github.com/ramonchi5/Steam-Controller-Gamepad-Viewer-by-Ramonchi_5) (MIT), used as a reference only; no code was copied.
* Steam and Steam Controller are trademarks of Valve Corporation. This project is unofficial and not affiliated with or endorsed by Valve. The Graphite and Vaporwave Pixel controller art is original, drawn from code; no Valve artwork is included.

## Included themes
* ﻿Sony DualSense
  * Default by [Al. Lopez (AL2009man)](https://github.com/AL2009man)
    - Color: Cosmic Red
    - Color: Galactic Purple
    - Color: Midnight Black 
    - Color: Nova Pink
    - Color: Starlight Blue
    - Color: White
* ﻿Sony DualShock 4
  * Default by [Al. Lopez (AL2009man)](https://github.com/AL2009man)
    - Color: Glacier White
    - Color: Gold
    - Color: Jet Black
    - Color: Magma Red
    - Color: Midnight Blue
  * Devil May Cry 5 by [Al. Lopez (AL2009man)](https://github.com/AL2009man)
  * PlayStation 20th Anniversary by [Al. Lopez (AL2009man)](https://github.com/AL2009man)
* ﻿General
  * Genshin Impact by Nielk1
  * Arcade Stick by [Al. Lopez (AL2009man)](https://github.com/AL2009man)
    - Directional Pad
    - Ergonomics (HITBOX-style)
    - Joystick+D-PAD Combo
    - Joystick (Joystick Output only)
    - WASD
* ﻿Nintendo Switch Pro Controller
  * Default by [Al. Lopez (AL2009man)](https://github.com/AL2009man)
* ﻿Nintendo Switch Joy-Con
  * Default by (AL2009man)](https://github.com/AL2009man)
* ﻿Valve Steam Controller
  * Default by [Al. Lopez (AL2009man)](https://github.com/AL2009man)
    - Color: Black
    - Color: White
  * ahNOMinal 2 by [ahMEmon](https://www.twitch.tv/ahmemon)
  * Buh-Lack by [ahMEmon](https://www.twitch.tv/ahmemon)
  * Classic by Nielk1
  * Docteur Controller by [Docteur Controller](https://www.youtube.com/channel/UC1GoAgop-6tbftsU4qtpSOQ)
  * Devieus Glass by [Devieus](https://www.youtube.com/user/Devieus)
  * Diagnostic by [Al. Lopez (AL2009man)](https://github.com/AL2009man)
  * Grey Minimal by [CriticalComposer](https://www.youtube.com/c/criticalcomposer)
  * Line Art by [Ishmobile](https://www.youtube.com/channel/UCTAPOuAcWv9JGdiQsVVSxkQ)
  * Line Art Invert by Sora Firestone & [Ishmobile](https://www.youtube.com/channel/UCTAPOuAcWv9JGdiQsVVSxkQ)
  * Cat Paws by Nielk1
  * Black Stencil by [RambleTan](https://www.youtube.com/channel/UCYI8ifruvIqVtAY3joqlpfw)
  * Outline 2018 by [RambleTan](https://www.youtube.com/channel/UCYI8ifruvIqVtAY3joqlpfw)
  * Outline 2019 by [RambleTan](https://www.youtube.com/channel/UCYI8ifruvIqVtAY3joqlpfw)
  * Fire Sale by Nielk1, [Twenty-Six Twelve](https://www.reddit.com/user/Twenty-Six_Twelve/)
  * White Cerberus by [8BitCerberus](https://github.com/8BitCerberus/vscview-themes)
  * Graphite (generated, this fork)
  * Vaporwave Pixel (generated, this fork)
* Valve Steam Controller (2026)
  * Graphite (generated, this fork)
  * Vaporwave Pixel (generated, this fork)
* ﻿Valve Steam Controller Chell
  * Default by Nielk1
* ﻿Valve Steam Deck
  * Default by [Al. Lopez (AL2009man)](https://github.com/AL2009man)
    - Color: Black
* ﻿Microsoft Xbox 360 Controller
  * Default by [Al. Lopez (AL2009man)](https://github.com/AL2009man)
    - Color: Black 
    - Color: White
  * Wikimedia by [Al. Lopez (AL2009man)](https://github.com/AL2009man)
* ﻿Microsoft Xbox Wireless Controller
  * Default by [Al. Lopez (AL2009man)](https://github.com/AL2009man)
    - Xbox One Controller
      * Color: Black
      * Color: White
    - Xbox One S Controller
      * Color: Black
      * Color: Blue
      * Color: Red
      * Color: White
    - Xbox Series X|S Controller
      * Color: Carbon Black
      * Color: Shock Blue
      * Color: Deep Pink
      * Color: Pulse Red
      * Color: Electric Volt
      * Color: Robot White
  * Devil May Cry 5 by [Al. Lopez (AL2009man)](https://github.com/AL2009man)
