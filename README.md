# VSCView
On-screen Controller Overlay for Steam Controller and various other controllers.

This fork adds:
* **The 2026 Steam Controller**, read natively through [SDL3](https://www.libsdl.org/): both trackpads (position, click and pressure), thumbstick touch, all four back buttons (L4/L5/R4/R5) and grip sense.
* **An OBS Browser Source with real transparency.** No chroma key or green screen is needed.
* **Theme Browser.** Every theme comes with a live preview. Use it in the window, or copy an OBS URL pinned to it.
* **Settings dialog** for the OBS server, controllers and window.
* **Follow mode.** With several controllers connected, VSCView switches to whichever one you are using, and to the theme you last used with that kind of controller. One OBS source covers every game.
* **SDK-style projects.** `dotnet build` works with only the .NET SDK installed.

The original 2015 Steam Controller keeps using VSCView's existing HID decoder, which already reports real trackpad touch positions and both rear grips.

## OBS setup (Browser Source, no chroma key)
1. Start VSCView. Right-click the window and open **Theme Browser…** (or **Theme**) to pick a theme. With follow mode on (the default), just press a button on the controller you are using.
2. Right-click, open **OBS Browser Source**, and choose **Copy URL (follows window theme)**. The default URL is `http://127.0.0.1:47817/`.
3. In OBS, add a source: **+** > **Browser**.
   * **URL**: paste the copied URL.
   * **Width / Height**: the theme size, e.g. `1000` x `760` for the 2026 themes or `995` x `720` for the Steam Controller default theme. You can resize the source in the scene afterwards.
   * Leave **Custom CSS** at its default. The page background is already transparent.
   * Optional: tick **Shutdown source when not visible** so VSCView only renders while the source is on screen.
4. Done. The controller is composited with real alpha. You can minimise the VSCView window, but keep the app running.

URL options:

| Option | Example | Effect |
| --- | --- | --- |
| `theme` | `?theme=steamcontroller2026/graphite/Full.json` | Pin this source to one theme, independent of the window. The path is relative to the `themes` folder. **Copy URL (pinned to current theme)** builds it for you. |
| `fps` | `&fps=30` | Render rate for this source (default 60). |
| `align` | `&align=bottom` | Where the image sits inside a source that has a different aspect ratio (`left`, `right`, `top`, `bottom`). |
| `status` | `&status=1` | Show the connection status (for troubleshooting; hidden by default). |

Several Browser Sources can point at different `theme` URLs at the same time. Every source shows the controller selected in the VSCView window.

How it works: VSCView renders the theme with its own renderer into an off-screen transparent bitmap. A small built-in server streams changed frames as PNGs over a WebSocket, and the page draws them onto a `<canvas>`. Nothing is rendered while no source is connected, and identical frames are not re-sent. The server listens on **127.0.0.1 only**. It is not reachable from your network, and requests with a non-local `Host` or `Origin` are refused.

**Settings…** (or **OBS Browser Source** > **Status...**) shows render/encode timings and the SDL3 status. Disable the server with **OBS Browser Source > Enabled**. To change the port, set `"OverlayPort"` in `settings.json`. A second VSCView instance uses port + 1.

## Controller support notes
* **2026 Steam Controller**: works over USB or the wireless puck, including while Steam is running with Steam Input. SDL3 is set up to touch only this controller: every other HIDAPI driver is disabled, and the XInput, RawInput, WGI, GameInput and DirectInput backends are off, so Steam's virtual Xbox pads are never picked up. It appears in the **Controller** menu as *Steam Controller (2026)*. Motion is not shown for it yet.
* **2015 Steam Controller**: unchanged, via HID. SDL3's own 2015-controller driver is deliberately not used. It does not expose trackpad touch, and it switches the controller back to lizard mode when it closes.

## Building
Requirements: Windows and the [.NET SDK](https://dotnet.microsoft.com/download) (8 or newer). The app itself targets .NET Framework 4.6.2, which is built into Windows 10 and 11.

```
git clone --recursive https://github.com/80sFauxstalgia/vscview-overlay
cd VSCView
dotnet build VSCView.sln -c Release
```

The first build downloads the official SDL3 release (`SDL3-3.4.20-win32-x64.zip` from github.com/libsdl-org/SDL) and checks its SHA-256 before using it. The output is in `VSCView/bin/Release/net462/`.

The 2026 themes are generated from code. To regenerate them, install Pillow (`pip install pillow`) and run `python tools/theme-gen/gen_steamcontroller2026.py`.

## Credits
* **VSCView** and **ExtendInput** by [Nielk1 (John Klein)](https://github.com/Nielk1/VSCView), MIT. This project is a fork, and all the original rendering, theme engine and 2015 Steam Controller support is theirs.
* Original themes by the authors listed below.
* [SDL3](https://www.libsdl.org/), zlib license. It is downloaded at build time and its license ships as `licenses/SDL3.txt`.
* [SDL3-CS](https://github.com/flibitijibibo/SDL3-CS) C# bindings, zlib license, vendored unmodified in `VSCView/ThirdParty/SDL3-CS`.
* The 2026 controller's protocol was cross-checked against SDL's `SDL_hidapi_steam_triton.c` and [Steam-Controller-Gamepad-Viewer by ramonchi5](https://github.com/ramonchi5/Steam-Controller-Gamepad-Viewer-by-Ramonchi_5) (MIT), used as a reference only. No code from it is included.
* Steam and Steam Controller are trademarks of Valve Corporation. This project is unofficial and not endorsed by Valve. The 2026 controller art in this repository is original and drawn from code; no Valve artwork is included.


## Themes
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
