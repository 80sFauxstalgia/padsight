# Third-party notices

PadSight ships the components below next to `PadSight.exe`. Each license text is in the `licenses/` folder of the release. The About dialog also shows them, on its "Third-party licenses" tab.

| Component | Version | License | File in `licenses/` |
| --- | --- | --- | --- |
| [VSCView](https://github.com/Nielk1/VSCView) and [ExtendInput](https://github.com/Nielk1/ExtendInput), by John Klein | upstream | MIT | `VCSView.txt` |
| [SDL3](https://www.libsdl.org/) (`SDL3.dll`, official release) | 3.4.20 | zlib | `SDL3.txt` |
| [SDL3-CS](https://github.com/flibitijibibo/SDL3-CS) bindings (compiled in) | c42d07e | zlib | `SDL3-CS.txt` |
| [Flee](https://github.com/mparlak/Flee) | 1.2.2 | LGPL (unmodified, dynamically linked) | `Flee.txt` |
| [HidSharp](https://www.zer7.com/software/hidsharp) | 2.1.0 | Apache-2.0 | `HidSharp.txt` |
| [SharpDX](https://github.com/sharpdx/SharpDX) and SharpDX.XInput | 4.2.0 | MIT | `SharpDX.txt` |
| [NAudio](https://github.com/naudio/NAudio) | 1.10.0 | Ms-PL | `NAudio.txt` |
| [Microsoft Edge WebView2 SDK](https://www.nuget.org/packages/Microsoft.Web.WebView2) (`Microsoft.Web.WebView2.*.dll`, `WebView2Loader.dll`); the WebView2 runtime itself is part of Windows | 1.0.2903.40 | BSD-3-Clause | `WebView2.txt` |
| [Newtonsoft.Json](https://www.newtonsoft.com/json) | 13.0.3 | MIT | `Newtonsoft.Json.txt` |
| .NET packages: System.Memory, System.Buffers, System.Numerics.Vectors, System.Runtime.CompilerServices.Unsafe, System.ValueTuple, System.Reflection, System.Resources.Extensions, System.Security.AccessControl, System.Security.Principal.Windows, Microsoft.Win32.Registry | various | MIT | `dotnet-packages.txt` |

## Artwork

Every image PadSight ships is listed here, by theme folder under `themes/`, with where it comes from. Each theme's `theme.json` names its author too.

### Made for PadSight (Talaria Software LLC, MIT, like the rest of this repository)
| Folder | Images | Exact source |
| --- | --- | --- |
| `steamcontroller2026/graphite`, `steamcontroller2026/vaporwave` | 72 | Drawn by `tools/theme-gen/gen_steamcontroller2026.py` (Python + Pillow) from geometric shapes, with coordinates written in the script. The script reads no input images; it only re-opens its own output to make the theme icons. |
| `steamcontroller2026/realistic` | 42 | Rendered by `tools/blender/render_sc2026.py` with `sc_common.py` and `sc_shared.py` in Blender (Cycles). Procedural geometry, node-built materials, area lights and a gradient world; no external models, textures, HDRIs or font files. Printed labels use Blender's built-in text font, and only the rendered pixels are shipped. |
| `steamcontroller/graphite`, `steamcontroller/vaporwave` | 70 | Drawn by `tools/theme-gen/gen_steamcontroller2015.py`, sharing the drawing code of the 2026 script. |
| `steamcontroller/realistic` | 34 | Rendered by `tools/blender/render_sc2015.py`, same pipeline as the 2026 Realistic theme. |
| `steamcontroller2026/icon.png`, `icons/DEVICE_SC2026.png` | 2 | Downscaled from the generated 2026 Graphite theme by `gen_steamcontroller2026.py`. |
| `padsight.ico`, `wwwroot/panel/logo.svg` | 2 | The PadSight logo: drawn by `tools/theme-gen/gen_app_icon.py` and hand-written SVG. |

None of these is traced from, or contains, any Valve photo, render, artwork or logo.

### From VSCView (MIT, credited to their authors as in upstream)
These themes were contributed to [Nielk1/VSCView](https://github.com/Nielk1/VSCView) and are distributed under its MIT license. They're flat drawings of the controllers, with no photo or render pixels. Some show the manufacturer's logo or button symbols as printed on the controller.

| Folder | Author(s) |
| --- | --- |
| `steamcontroller/default` (Black, White), `steamcontroller/al2009man` (Diagnostic) | Al. Lopez (AL2009man) |
| `steamcontroller/ahmemon` (Buh-Lack) | ahMEmon |
| `steamcontroller/docteurcontroller` | Docteur Controller. Its stick-cap sprite was a shaded render; PadSight ships a flat redraw instead. |
| `steamcontroller/greyminimal` | CriticalComposer. Its stick-cap sprite was a shaded render; PadSight ships a flat redraw instead. It also uses seven flat sprites (button glows, gyro shading) by Nielk1 that upstream keeps in the Classic theme, copied into this folder. |
| `steamcontroller/ishmobile` (Line Art) | Ishmobile |
| `steamcontroller/sorafirestorm` (Line Art Invert) | Sora Firestorm and Ishmobile |
| `steamcontroller/rambletan` (Black Stencil, Outline 2018, Outline 2019) | RambleTan; the gyro shading sprites are by Nielk1 |
| `steamdeck/default` | Al. Lopez (AL2009man) |
| `dualsense/default` | Al. Lopez (AL2009man) |
| `dualshock4/default` (V1, V2), `dualshock4/al2009man` (PlayStation 20th Anniversary) | Al. Lopez (AL2009man) |
| `xboxwirelesscontroller/default`, `xboxwirelesscontroller/motion` | Al. Lopez (AL2009man) |
| `xbox360controller/default` | Al. Lopez (AL2009man) |
| `nintendoswitchprocontroller/default`, `nintendoswitchjoycon/default` | Al. Lopez (AL2009man) |
| `general/arcadestick` | Al. Lopez (AL2009man) |
| `icons/` (connection and device icons, except `DEVICE_SC2026.png`), family `icon.png` files | VSCView (Nielk1, Al. Lopez) |
| `Resources/Nielk1_eyes_128.png` (About dialog) | John "Nielk1" Klein |

### Upstream themes not included
These VSCView themes aren't shipped, because they're built on manufacturer product photos or press renders, or on game artwork:
- **Built on Valve's Steam Controller press render:** `steamcontroller/classic`, `glass` (Devieus Glass), `ahmemon/ah_nom_inal` (ahNOMinal 2), `white cerberus` (8BitCerberus), `nielk1/firesale`.
- **Built on a product photo:** `steamcontrollerchell/default`.
- **Photo of unknown origin:** `nielk1/cat paws`.
- **Game artwork or branding:** `general/genshin_impact`, plus `dualshock4/al2009man/dmc5` and `xboxwirelesscontroller/al2009man/dmc5` (Devil May Cry 5).
- **CC BY-SA 3.0 derivative:** `xbox360controller/al2009man/Wikimedia`, adapted from the Wikimedia Commons file "360 controller.svg". It would need its own attribution and share-alike terms.

### Trademarks
Steam, Steam Controller and Steam Deck are trademarks of Valve Corporation. PlayStation, DualShock and DualSense are trademarks of Sony Interactive Entertainment. Xbox is a trademark of Microsoft. Nintendo Switch and Joy-Con are trademarks of Nintendo. Bluetooth is a trademark of Bluetooth SIG. They appear in some community themes and icons only to identify the controllers. PadSight is unofficial and not affiliated with or endorsed by any of these companies.
