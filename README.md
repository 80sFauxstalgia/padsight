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
- **Follow mode.** With both controllers connected, the overlay switches to the one you are using, along with the theme you last used for that kind of controller. One OBS source covers every game.
- **Theme Browser** with live previews, plus new Graphite and Vaporwave Pixel themes for both Steam Controllers.
- **Private by design.** The overlay server only listens on `127.0.0.1` (this PC) and sends nothing anywhere else.

## Quick start
1. Download the latest release zip, extract it anywhere, and run `VSCView.exe`.
   * Requires Windows 10 or 11. The .NET Framework 4.8 it needs is built in.
2. Right-click the window and open **Theme Browser…**. Pick a theme for your controller, then **Use in window**.
3. Press any button on your controller. With follow mode on (the default), VSCView picks it up automatically.
4. Add it to OBS as described below.

<!-- SCREENSHOT: docs/screenshots/theme-browser.png. Theme Browser with the 2026 Graphite theme selected. -->

## Adding it to OBS
1. In VSCView, right-click and choose **OBS Browser Source › Copy URL (follows window theme)**. The default URL is `http://127.0.0.1:47817/`.
2. In OBS, under **Sources**, click **+** › **Browser** › **Create new**. Then set:
   * **URL**: paste the URL.
   * **Width × Height**: the theme size, e.g. **1000 × 760** for the Graphite and Vaporwave themes, or **995 × 720** for the original Steam Controller default theme. The Theme Browser shows each theme's size.
   * **Custom CSS**: leave the default. The page is already transparent.
   * Optional: tick **Shutdown source when not visible**, so VSCView renders nothing while the overlay is off screen.
3. Click **OK**, then move and scale the source like any other.

<!-- SCREENSHOT: docs/screenshots/obs-properties.png. OBS Browser Source properties filled in. -->
<!-- SCREENSHOT: docs/screenshots/obs-scene.png. Overlay over gameplay in an OBS scene. -->

You can minimise the VSCView window, but keep it running. If VSCView closes, the source simply goes transparent, and it reconnects on its own when VSCView starts again.

### URL options
| Option | Example | What it does |
| --- | --- | --- |
| `theme` | `?theme=steamcontroller2026/graphite/Full.json` | Pins this source to one theme, independent of the window. The path is relative to the `themes` folder. **Copy URL (pinned to current theme)** and the Theme Browser's **Copy OBS URL** build it for you. |
| `fps` | `&fps=30` | Render rate for this source (default 60). |
| `align` | `&align=bottom` | Where the image sits when the source's aspect ratio differs from the theme: `left`, `right`, `top` or `bottom`. |
| `status` | `&status=1` | Shows the connection status in a corner (troubleshooting). |

Several Browser Sources can show different themes at the same time. All of them follow the controller selected in VSCView.

### Settings
Right-click › **Settings…**:
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
  * Gyro display is not supported for it yet.
  <!-- VERIFY on hardware before release: "works while Steam is running with Steam Input enabled". -->
* **Original (2015) Steam Controller.** Read through VSCView's established HID decoder, as before.
* SDL3 is only allowed to touch the 2026 Steam Controller:
  * it never opens other gamepads, so it can't change their LEDs or rumble;
  * it ignores Steam's virtual Xbox controllers;
  * it leaves the 2015 controller to the HID decoder.

## Troubleshooting
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

The Graphite and Vaporwave Pixel themes are generated by Python scripts in `tools/theme-gen/` (needs Pillow: `pip install pillow`). Re-run them after changing the layout or colours.

Theme authors: [THEMEENGINE.md](THEMEENGINE.md) documents every element type and every controller's inputs, including the 2026 controller's `stick_touch`, `grip2`, `grip_sense`, `qam` and `touch_*:0:pressure`.

## Credits and licenses
* **[VSCView](https://github.com/Nielk1/VSCView)** and **[ExtendInput](https://github.com/Nielk1/ExtendInput)** by Nielk1 (John Klein), MIT. This project is a fork. The rendering, the theme engine and the original Steam Controller support are their work.
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
