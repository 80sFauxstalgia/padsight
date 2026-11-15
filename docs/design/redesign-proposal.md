# Redesign proposal (for approval before the main build)

Status: **proposal**. Nothing here is built yet. Mockups are on a private design canvas (link shared with Griff).
"Padsight" is used in the mockups as a stand-in for whichever name is picked.

## 1. UX audit of today's app (new-user walkthrough)

**Install / first run**
1. The download is a zip of about 1,240 files. Nothing says which one to run, and `ThemeFixer.exe` sits next to `VSCView.exe`.
2. First launch shows a small borderless box with two grey hints ("Right Click for Context Menu", "Click and Drag to Move"). There's no title bar, no taskbar context and no indication of what the app is for.
3. SmartScreen warns, because the binaries are unsigned. Nothing in the app explains that.

**Connecting a controller**
4. Controllers are only visible under right-click › Controller. A 2015 dongle shows as four identical "Valve Steam Controller Dongle" entries, and the empty slots look the same as the live one.
5. With Steam running, Steam's virtual Xbox pads appear as extra XInput controllers. A new user can't tell which entry is the real controller.
6. "Auto Select Only Controller" is off by default, and when several devices exist it silently does nothing. Follow mode fixes the logic but is invisible in the UI.
7. There's no feedback that input is arriving, short of picking a theme and watching it move.

**Picking a theme**
8. The Theme menu is a deep cascade (family › author › variant › layout file). Names such as "1 All", "4 No Gyro (Compact)" or "H10 Theme Debug" mean nothing to users, and there are no previews in the menu. The new Theme Browser helps, but it's a secondary window.
9. Themes aren't filtered by controller, so it's easy to pick a DualShock theme for a Steam Controller.
10. Theme size (which OBS needs) is shown nowhere except the Theme Browser footer.

**Adding to OBS**
11. The OBS URL hides under right-click › OBS Browser Source › Copy URL. Width and height must be looked up separately, and the README is the only place the steps are written down.
12. There's no confirmation that OBS actually connected. The window shows no "on air" state; that's only in a Status dialog or `/status.json`.
13. The legacy chroma-key workflow ("Set Background Color") sits next to the new transparent workflow with no explanation of which to use.

**Settings and troubleshooting**
14. Settings are split between context-menu toggles (Auto Select, motion hack, HidGuardian) and the Settings dialog. Some options appear in both places.
15. Errors are mostly silent: a missing SDL3.dll, a busy port or a bad theme only appear in a dialog or in the status endpoint.
16. Nothing explains controller states such as asleep, receiver missing, or Steam Input interference.

**Look and feel**
17. It uses default WinForms chrome with 2018-era icons. Fonts and colours are inconsistent between the main window, dialogs and the browser overlay.

## 2. UI technology: recommendation

| Option | Look we can reach | Effort | Maintenance | Download |
| --- | --- | --- | --- | --- |
| **Web control panel in a WebView2 window (recommended)** | Anything CSS can do: the mockups as drawn, with animation | Medium: HTML/CSS/JS plus a small JSON API on the existing server | One UI technology for the panel *and* the overlay | +~0.5 MB (WebView2 SDK); the runtime is built into Windows 10/11 |
| WPF (.NET Framework) | Good, with effort (custom templates) | Medium–high | XAML styling is verbose; second UI stack next to the web overlay | No change |
| WinUI 3 | Modern Fluent look, not easily "sci-fi HUD" | High: needs a move to .NET 8+ and the Windows App SDK | Young platform, packaging friction | +30–60 MB unless self-contained trimming works |
| Avalonia | Good, cross-platform | High: rewrite UI; new dependency | Healthy project; another stack | +20–40 MB |

**Why web + WebView2:**
- The app already runs a local web server, and the OBS overlay is already a web page, so the look is designed once.
- **The same panel doubles as an OBS dock.** OBS's *Custom Browser Docks* can host it, so streamers can control everything without leaving OBS. No other option gets that for free.
- The download stays small, and WinForms remains only as the host window, plus a tray icon.
- **Requirement:** the control API must be protected, because any website could otherwise send requests to 127.0.0.1. The panel gets a per-install random key in its URL, every write needs that key plus a matching `Origin`, and the read-only overlay stays as it is.
- **Fallback:** if the WebView2 runtime is missing (rare on Windows 10), the panel opens in the default browser.

## 3. Proposed design (see mockups)

- **First-run setup, 3 steps:** connect a controller with live detection, choose a look, add it to OBS. It can be skipped, and reopened from Help.
- **Home:**
  - status strip: overlay on air and how many OBS sources, OBS link, follow mode;
  - controller cards with live sticks, pads, triggers and buttons, plus state (in use / standby / asleep);
  - the overlay exactly as OBS sees it;
  - one big **Copy OBS URL** and **Add to OBS for me**.
- **Themes:**
  - gallery with real previews, filtered to "my controllers" by default;
  - human names, size and author on each card;
  - **Use** and **Copy pinned URL** on each card;
  - "make your own" entry point.
- **OBS:** automatic add via obs-websocket, manual steps with copy fields, per-source overlay options, OBS-aware features, dock URL.
- **Help & status:** every controller, overlay and OBS state has plain wording and a next action; "Copy diagnostics" for bug reports.
- **Visual language:** deep navy, thin cyan rules, monospace labels, corner brackets; Space Grotesk / Inter / JetBrains Mono. The accent colour is a setting, with the vaporwave palette as a preset.

## 4. OBS-specific features (Griff asked)

**Without OBS access** (URL options, per Browser Source):
- fade out after N seconds idle, fade back in on input;
- opacity;
- part of the controller to show (whole / pads and sticks / back buttons);
- theme pinned or following the app; frame rate; anchor.

**With obs-websocket** (optional; the password is stored encrypted with Windows DPAPI):
- *Add to OBS* creates the Browser Source at the correct size, with "Shutdown source when not visible" on;
- theme per scene (e.g. "Rocket League" uses the 2015 theme, "Expedition 33" uses the 2026 one);
- hide the overlay on break scenes ("Starting soon", "BRB");
- optional: show only while recording or live;
- OBS hotkeys and Stream Deck actions (switch controller, toggle overlay);
- reports when a source points to an old port, and fixes it.

**OBS dock:** the control panel inside OBS via Custom Browser Docks.

**Extra sources (later):**
- an input-history ticker (recent presses, fighting-game style);
- a stick/pad trail layer.

## 5. Name options

All checked on GitHub (repository name search) and the web on 2026-11-15. "Steam" is avoided because it's Valve's trademark.

| Name | GitHub | Web | Notes |
| --- | --- | --- | --- |
| **Padsight** | no repos | no product found | Short and clear ("see your pad"). Top pick. |
| **Thumbsight** | one empty repo | no product found | About thumbs and sticks; slightly long. |
| **Padglass** | no repos | no product found | HUD-glass feel. Similar-sounding "GlassPad" is an on-screen *touch* controller for Windows, so there's some confusion risk. |
| **PadHUD** | no exact repo | no product found | Descriptive, but generic and hard to trademark. |
| **Trackglass** | one empty repo | only glass-industry apps | Nods to the Steam Controller trackpads; less obvious for other pads. |

Ruled out as taken or confusing in the same niche: GlassPad, PadScope, InputGlow, InputScope, Ghostpad, Holopad, Padlight.

**Credit wording:**
- About and README: "Based on VSCView by Nielk1 (John Klein), MIT".
- LICENSE keeps "Copyright (c) 2018-2021 John Klein", with "Copyright (c) 2026 Talaria Software LLC" added.
- Each theme keeps its author credit.

## 6. Build plan once approved

1. JSON control API with key/Origin protection, plus the WebView2 host window and tray icon.
2. Panel screens in this order: Home, Themes, OBS, Help, Setup.
3. obs-websocket client: add source, scene rules, hotkeys.
4. URL overlay options: idle fade, opacity, crop.
5. Rename (assembly, window titles, installer zip, README); keep the old `VSCView.exe` settings import.
6. Screenshots, README, release workflow, then CTO chat's approval card.

Generated art: none needed. All controller art is drawn by our own scripts, so no PixelLab use.
