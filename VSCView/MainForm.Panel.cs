using ExtendInput.Controller;
using ExtendInput.Controls;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using VSCView.Web;

namespace VSCView
{
    /// <summary>
    /// The web control panel: its JSON API (served by the overlay server, key-protected), the WebView2 window
    /// that hosts it, and the tray icon. The panel is the main interface; the classic borderless window is
    /// an optional desktop preview.
    /// </summary>
    public partial class MainForm
    {
        public const string ProductName = "PadSight";

        NotifyIcon tray;
        ToolStripMenuItem trayPreview;
        UiForms.PanelForm panelForm;
        bool startHidden;
        bool startupDone;
        bool loadRan;
        bool trayHintShown;

        /// <summary>Called from the constructor once settings are loaded.</summary>
        private void InitPanel()
        {
            if (string.IsNullOrEmpty(settings.PanelKey))
            {
                settings.PanelKey = PanelKey.Generate();
                SaveSettings();
            }
            // Existing users (a theme was already chosen in the classic window) keep that window by default.
            if (settings.ShowPreviewWindow == null)
                settings.ShowPreviewWindow = !string.IsNullOrWhiteSpace(settings.Theme);
            startHidden = !(settings.ShowPreviewWindow ?? false);
            Input.SdlSteamController.MotionEnabled = settings.Gyro2026 ?? true;
            AppIcon = LoadAppIcon();
            if (AppIcon != null) this.Icon = AppIcon;
            InitTray();
        }

        internal static Icon AppIcon { get; private set; }

        private static Icon LoadAppIcon()
        {
            try { return Icon.ExtractAssociatedIcon(Assembly.GetEntryAssembly().Location); } catch { return null; }
        }

        private Web.OverlayHub CreateHub()
        {
            return new Web.OverlayHub(ControllerData)
            {
                DefaultFps = settings.OverlayFps ?? 60,
                ApiKey = settings.PanelKey,
                Api = HandleApi,
                Visible = HiddenReason() == null,
            };
        }

        /// <summary>Start hidden when the desktop preview window is off, but still run the window's startup.</summary>
        protected override void SetVisibleCore(bool value)
        {
            if (value && startHidden && !startupDone)
            {
                startupDone = true;
                if (!IsHandleCreated) CreateHandle();
                base.SetVisibleCore(false);
                OnLoad(EventArgs.Empty); // Form only raises Load when first shown
                return;
            }
            base.SetVisibleCore(value);
        }

        /// <summary>Guard: Load can be raised twice when the window starts hidden and is shown later.</summary>
        private bool FirstLoad()
        {
            if (loadRan) return false;
            loadRan = true;
            return true;
        }

        private void AfterStartup()
        {
            if (settings.OpenPanelOnStart ?? true) OpenPanel();
        }

        #region Tray
        private void InitTray()
        {
            trayPreview = new ToolStripMenuItem("Desktop preview window", null, (s, e) => SetPreviewWindow(!(settings.ShowPreviewWindow ?? false)));
            var menu = new ContextMenuStrip();
            menu.Items.Add(new ToolStripMenuItem($"Open {ProductName}", null, (s, e) => OpenPanel()) { Font = new Font(menu.Font, FontStyle.Bold) });
            menu.Items.Add(new ToolStripMenuItem("Copy OBS URL", null, (s, e) => CopyText(overlayHub.Url)));
            menu.Items.Add(trayPreview);
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(new ToolStripMenuItem("Exit", null, (s, e) => ExitApp()));
            menu.Opening += (s, e) => trayPreview.Checked = settings.ShowPreviewWindow ?? false;

            tray = new NotifyIcon
            {
                Icon = AppIcon ?? SystemIcons.Application,
                Text = ProductName,
                ContextMenuStrip = menu,
                Visible = true,
            };
            tray.MouseClick += (s, e) => { if (e.Button == MouseButtons.Left) OpenPanel(); };
        }

        private void ExitApp()
        {
            ttimer?.Change(Timeout.Infinite, Timeout.Infinite);
            Close();
        }

        private void SetPreviewWindow(bool show)
        {
            settings.ShowPreviewWindow = show;
            SaveSettings();
            if (show) { Show(); WindowState = FormWindowState.Normal; Activate(); }
            else Hide();
        }

        private void DisposePanel()
        {
            try { panelForm?.Close(); } catch { }
            panelForm = null;
            if (tray != null) { tray.Visible = false; tray.Dispose(); tray = null; }
        }
        #endregion

        #region Panel window
        internal void OpenPanel()
        {
            if (!overlayHub.IsRunning)
            {
                MessageBox.Show(this, $"The {ProductName} panel needs the local server, which is not running.\n\n{overlayHub.Error}",
                    ProductName, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            if (panelForm != null && !panelForm.IsDisposed)
            {
                if (panelForm.WindowState == FormWindowState.Minimized) panelForm.WindowState = FormWindowState.Normal;
                panelForm.Show();
                panelForm.Activate();
                return;
            }
            if (!UiForms.PanelForm.RuntimeAvailable())
            {
                // Rare on Windows 10/11: fall back to the default browser.
                try { Process.Start(overlayHub.PanelUrl); } catch { }
                return;
            }
            panelForm = new UiForms.PanelForm(overlayHub.PanelUrl, $"http://127.0.0.1:{overlayHub.Port}/", AppIcon);
            panelForm.FormClosed += (s, e) =>
            {
                panelForm = null;
                if (!Visible && tray != null && !trayHintShown)
                {
                    trayHintShown = true;
                    tray.ShowBalloonTip(4000, ProductName, $"{ProductName} keeps running in the tray, so OBS still gets the overlay. Right-click the tray icon to exit.", ToolTipIcon.Info);
                }
            };
            panelForm.Show();
        }
        #endregion

        #region API
        /// <summary>Server thread. Everything that touches app state runs on the UI thread.</summary>
        private ApiResponse HandleApi(ApiRequest req)
        {
            string route = req.Method + " " + req.Path;
            switch (route)
            {
                case "GET /api/state": return ApiResponse.Ok(OnUi(BuildPanelState));
                case "GET /api/themes": return ApiResponse.Ok(JsonConvert.SerializeObject(new { themes = ThemeList(true) }));
                case "POST /api/theme": return OnUi(() => ApiSetTheme(Body(req)));
                case "POST /api/controller": return OnUi(() => ApiSetController(Body(req)));
                case "POST /api/identify": return OnUi(() => ApiIdentify(Body(req)));
                case "POST /api/settings": return OnUi(() => ApiSettings(Body(req)));
                case "POST /api/open": return OnUi(() => ApiOpen(Body(req)));
                case "POST /api/rotate-key": return OnUi(ApiRotateKey);
                case "POST /api/visibility": return OnUi(() => ApiVisibility(Body(req)));
                case "POST /api/hotkeys": return OnUi(() => ApiHotkeys(Body(req)));
                case "POST /api/obs/connect": return OnUi(() => ApiObsConnect(Body(req)));
                case "POST /api/obs/rules": return OnUi(() => ApiObsRules(Body(req)));
                // These wait on OBS, so they run on the server thread, never the UI thread.
                case "GET /api/obs/scenes": return ApiObsScenes();
                case "POST /api/obs/add-source": return ApiObsAddSource(Body(req));
                case "POST /api/obs/fix-port": return ApiObsFixPort(Body(req));
                case "POST /api/obs/outputs": return ApiObsOutputs(Body(req));
                default: return ApiResponse.Error(404, "Unknown API " + route);
            }
        }

        private static JObject Body(ApiRequest req)
        {
            try { return string.IsNullOrWhiteSpace(req.Body) ? new JObject() : JObject.Parse(req.Body); }
            catch { throw new ArgumentException("Body is not valid JSON"); }
        }

        /// <summary>Run on the UI thread and wait (bounded, so a busy UI can't pin server threads forever).</summary>
        private T OnUi<T>(Func<T> f)
        {
            if (!InvokeRequired) return f();
            IAsyncResult ar = BeginInvoke(f);
            if (!ar.AsyncWaitHandle.WaitOne(3000)) throw new TimeoutException("The app is busy; try again.");
            return (T)EndInvoke(ar);
        }

        private ApiResponse ApiSetTheme(JObject b)
        {
            string file = overlayHub.ThemeFile((string)b["theme"]);
            if (file == null) return ApiResponse.Error(404, "Unknown theme");
            LoadThemeSafe(file);
            return ApiResponse.Ok(BuildPanelState());
        }

        private IController ControllerById(string id) =>
            id != null && ControllerMemoHack.TryGetValue(id, out var v) ? v.Item1 : null;

        private ApiResponse ApiSetController(JObject b)
        {
            IController c = ControllerById((string)b["id"]);
            if (c == null) return ApiResponse.Error(404, "That controller is no longer connected");
            if (c != ActiveController) LoadController(c, EventArgs.Empty);
            return ApiResponse.Ok(BuildPanelState());
        }

        private ApiResponse ApiIdentify(JObject b)
        {
            IController c = ControllerById((string)b["id"]);
            if (c == null) return ApiResponse.Error(404, "That controller is no longer connected");
            new Thread(() => { try { c.Identify(); } catch { } }) { IsBackground = true }.Start();
            return ApiResponse.Ok("{}");
        }

        private ApiResponse ApiSettings(JObject b)
        {
            bool restart = false;
            if (b["followMode"] != null) settings.FollowActiveController = (bool)b["followMode"];
            if (b["rememberThemePerController"] != null) settings.RememberThemePerController = (bool)b["rememberThemePerController"];
            if (b["autoSelect"] != null)
            {
                settings.AutoSelectOnlyController = (bool)b["autoSelect"];
                tsmiAutoSelectOnlyController.Checked = settings.AutoSelectOnlyController;
            }
            if (b["openPanelOnStart"] != null) settings.OpenPanelOnStart = (bool)b["openPanelOnStart"];
            if (b["gyro2026"] != null)
            {
                settings.Gyro2026 = (bool)b["gyro2026"];
                Input.SdlSteamController.MotionEnabled = settings.Gyro2026.Value;
            }
            if (b["gyro2015"] != null)
            {
                // The 2015 controller only sends motion after a settings write; it's re-applied on (re)initialise.
                settings.HackScMotionOn = (bool)b["gyro2015"];
                tsmiHackSCMotion.Checked = settings.HackScMotionOn;
                if (ActiveController is SteamController sc)
                {
                    sc.EnableMotion = settings.HackScMotionOn;
                    try { sc.DeInitalize(); sc.Initalize(); } catch (Exception ex) { Debug.WriteLine("SC motion: " + ex.Message); }
                }
            }
            if (b["setupDone"] != null) settings.SetupDone = (bool)b["setupDone"];
            if (b["accent"] != null)
            {
                string a = (string)b["accent"];
                settings.Accent = a != null && System.Text.RegularExpressions.Regex.IsMatch(a, "^#[0-9a-fA-F]{6}$") ? a : null;
            }
            if (b["overlayFps"] != null)
            {
                int fps = (int)b["overlayFps"];
                if (fps != (settings.OverlayFps ?? 60)) { settings.OverlayFps = fps; restart = true; }
            }
            SaveSettings();
            if (b["previewWindow"] != null) SetPreviewWindow((bool)b["previewWindow"]);
            if (restart)
            {
                // Only the render rate changes: keep the server (and this panel's connection) up.
                overlayHub.DefaultFps = settings.OverlayFps ?? 60;
                if (currentThemeFile != null) overlayHub.SetMainTheme(currentThemeFile);
            }
            AutoLoadController();
            return ApiResponse.Ok(BuildPanelState());
        }

        /// <summary>
        /// New panel key. The old one (and every dock URL that contains it, e.g. saved in OBS's settings)
        /// stops working at once. Only an already-authorised caller can ask, and only it gets the new key.
        /// </summary>
        private ApiResponse ApiRotateKey()
        {
            settings.PanelKey = PanelKey.Generate();
            SaveSettings();
            overlayHub.ApiKey = settings.PanelKey;
            if (panelForm != null && !panelForm.IsDisposed)
                panelForm.Navigate(overlayHub.PanelUrl, $"http://127.0.0.1:{overlayHub.Port}/");
            return ApiResponse.Ok(JsonConvert.SerializeObject(new { key = settings.PanelKey }));
        }

        private ApiResponse ApiOpen(JObject b)
        {
            switch ((string)b["what"])
            {
                case "advanced-settings": BeginInvoke(new Action(ShowSettings)); break;
                case "about": BeginInvoke(new Action(() => new About().ShowDialog())); break;
                case "themes-folder":
                    try { Process.Start("explorer.exe", "\"" + Path.GetFullPath("themes") + "\""); } catch { }
                    break;
                case "theme-docs":
                    string docs = Path.GetFullPath("THEMEENGINE.md");
                    if (File.Exists(docs)) try { Process.Start(docs); } catch { }
                    break;
                case "rescan": LoadControllers(false); break;
                default: return ApiResponse.Error(400, "Unknown target");
            }
            return ApiResponse.Ok("{}");
        }
        #endregion

        #region State
        /// <summary>Theme family folder -> the kind of controller it draws (see ControllerKind).</summary>
        private static readonly Dictionary<string, string> ThemeFamilyKinds = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["steamcontroller"] = "DEVICE_SC",
            ["steamcontroller2026"] = "DEVICE_SC2026",
            ["steamcontrollerchell"] = "DEVICE_SC_CHELL",
            ["dualshock4"] = "DEVICE_DS4",
            ["dualsense"] = "DEVICE_DS5",
            ["xbox360controller"] = "DEVICE_XBOX",
            ["xboxwirelesscontroller"] = "DEVICE_XBOX",
            ["nintendoswitchprocontroller"] = "DEVICE_SWITCH",
            ["nintendoswitchjoycon"] = "DEVICE_SWITCH",
            ["steamdeck"] = "DEVICE_DECK",
        };

        private static readonly (string code, string label)[] KindLabels =
        {
            ("DEVICE_SC2026", "Steam Controller (2026)"),
            ("DEVICE_SC_CHELL", "Steam Controller (Chell prototype)"),
            ("DEVICE_SC", "Steam Controller (2015)"),
            ("DEVICE_DS5", "DualSense"),
            ("DEVICE_DS4", "DualShock 4"),
            ("DEVICEXBOX", "Xbox controller"),
            ("DEVICE_GAMEPAD", "Gamepad"),
        };

        private static string KindLabel(IController c)
        {
            string[] codes = c.ControllerTypeCode;
            if (codes != null)
                foreach (var k in KindLabels) if (codes.Contains(k.code)) return k.label;
            // An empty slot on a 2015 wireless receiver reports no device type yet.
            if (c.ConnectionTypeCode?.Contains("CONNECTION_DONGLE_SC") == true) return "Steam Controller (2015)";
            return "Controller";
        }

        private sealed class ThemeInfo
        {
            public string key, family, theme, variant, author, kind;
            public int width, height;
        }

        private List<ThemeInfo> themeListCache;
        private DateTime themeListTime;

        private List<ThemeInfo> ThemeList(bool refresh)
        {
            if (!refresh && themeListCache != null && (DateTime.UtcNow - themeListTime).TotalSeconds < 30) return themeListCache;
            var list = new List<ThemeInfo>();
            foreach (var t in UiForms.ThemeCatalog.Load())
            {
                string key = overlayHub.ThemeKey(t.File);
                if (key == null) continue;
                int w = 0, h = 0;
                try
                {
                    var j = JObject.Parse(File.ReadAllText(t.File));
                    w = j["width"]?.Value<int>() ?? 0;
                    h = j["height"]?.Value<int>() ?? 0;
                }
                catch { }
                string familyDir = key.Split('/')[0];
                list.Add(new ThemeInfo
                {
                    key = key, family = t.Family, theme = t.Theme, variant = t.Variant, author = t.Author,
                    kind = ThemeFamilyKinds.TryGetValue(familyDir, out string fk) ? fk : null,
                    width = w, height = h,
                });
            }
            themeListCache = list;
            themeListTime = DateTime.UtcNow;
            return list;
        }

        /// <summary>UI thread: everything the panel shows, polled about 10 times a second.</summary>
        private string BuildPanelState()
        {
            DateTime now = DateTime.UtcNow;
            var controllers = ControllerMemoHack.Values.Select(v => v.Item1).Select(c =>
            {
                bool reading = c == ActiveController || followReading.Contains(c);
                ControllerState st = reading ? SafeState(c) : null;
                bool active = reading && IsInUse(st);
                if (active) lastUsed[c] = now;
                double? idleMs = lastUsed.TryGetValue(c, out var t) ? (now - t).TotalMilliseconds : (double?)null;
                return new
                {
                    id = c.DeviceHackRef?.UniqueKey,
                    name = c.Name,
                    details = c.NameDetails,
                    kinds = c.ControllerTypeCode,
                    kindLabel = KindLabel(c),
                    kind = ControllerKind(c),
                    theme = ThemeSummary(c),
                    connection = c.ConnectionTypeCode?.FirstOrDefault(),
                    xinput = c is XInputController,
                    present = c.IsPresent,
                    selected = c == ActiveController,
                    reading,
                    inUse = idleMs != null && idleMs < 2000,
                    motion = c.HasMotion,
                    live = st == null ? null : LiveInputs(st),
                };
            }).ToList();

            object theme = null;
            string themeKey = overlayHub.ThemeKey(currentThemeFile);
            if (themeKey != null)
                theme = (object)ThemeList(false).FirstOrDefault(o => o.key == themeKey) ?? new { key = themeKey };

            var channels = overlayHub.ChannelStats();
            int sources = 0;
            foreach (var ch in channels) sources += (int)ch.GetType().GetProperty("obs").GetValue(ch);

            var state = new
            {
                app = ProductName,
                version = Assembly.GetExecutingAssembly().GetName().Version.ToString(3),
                instance = instanceNumber,
                server = new { running = overlayHub.IsRunning, port = overlayHub.Port, error = overlayHub.Error, url = overlayHub.Url },
                sdl = DeviceManager.SdlStatus,
                settings = new
                {
                    followMode = settings.FollowActiveController ?? true,
                    rememberThemePerController = settings.RememberThemePerController ?? true,
                    autoSelect = settings.AutoSelectOnlyController,
                    overlayFps = settings.OverlayFps ?? 60,
                    openPanelOnStart = settings.OpenPanelOnStart ?? true,
                    previewWindow = settings.ShowPreviewWindow ?? false,
                    setupDone = settings.SetupDone ?? false,
                    accent = settings.Accent,
                    gyro2026 = settings.Gyro2026 ?? true,
                    gyro2015 = settings.HackScMotionOn,
                    overlayPort = settings.OverlayPort ?? DefaultOverlayPort,
                },
                theme,
                controllers,
                overlay = new { sources, channels },
                obs = ObsState(),
            };
            return JsonConvert.SerializeObject(state);
        }

        /// <summary>The theme this controller gets on the overlay (picked for its kind, or the default).</summary>
        private object ThemeSummary(IController c)
        {
            string file = ThemeForKind(ControllerKind(c), out bool remembered);
            string key = overlayHub.ThemeKey(file);
            if (key == null) return null;
            ThemeInfo t = ThemeList(false).FirstOrDefault(o => o.key == key);
            return new { key, name = t == null ? key : $"{t.theme} · {t.variant}", remembered };
        }

        /// <summary>Live values for the panel's controller cards (sticks, triggers, pads, pressed buttons).</summary>
        private static object LiveInputs(ControllerState s)
        {
            var sticks = new Dictionary<string, object>();
            var triggers = new Dictionary<string, object>();
            var pads = new Dictionary<string, object>();
            var pressed = new List<string>();
            object motion = null;
            if (s?.Controls != null)
            {
                foreach (string k in s.Controls.Keys)
                {
                    switch (s.Controls[k])
                    {
                        case ControlStick st:
                            sticks[k] = new { x = Math.Round(st.X, 3), y = Math.Round(st.Y, 3), click = st.Click };
                            break;
                        case ControlTriggerPair tr:
                            triggers[k] = new { l = Math.Round(tr.Left.Analog, 3), r = Math.Round(tr.Right.Analog, 3), l2 = tr.Left.Stage2, r2 = tr.Right.Stage2 };
                            break;
                        case ControlTouch tc:
                            {
                                int i = Enumerable.Range(0, tc.TouchCount).FirstOrDefault(n => tc.Touch[n]);
                                bool touching = tc.TouchCount > 0 && tc.Touch[i];
                                pads[k] = new { touch = touching, x = touching ? Math.Round(tc.X[i], 3) : 0, y = touching ? Math.Round(tc.Y[i], 3) : 0, p = 0.0, click = tc.Click };
                            }
                            break;
                        case ControlMotion mo:
                            // Angular velocity in deg/s (raw counts are 16.4 per deg/s, as on the 2015 controller).
                            motion = new { x = Math.Round(mo.AngularVelocityX / 16.4, 1), y = Math.Round(mo.AngularVelocityY / 16.4, 1), z = Math.Round(mo.AngularVelocityZ / 16.4, 1) };
                            break;
                        case Input.ControlTouchPressure tp:
                            pads[k] = new { touch = tp.Touch, x = Math.Round(tp.X, 3), y = Math.Round(tp.Y, 3), p = Math.Round(tp.Pressure, 3), click = tp.Click };
                            break;
                    }
                }
                foreach (string p in DescribeInputs(s))
                {
                    // Buttons only; analog values are drawn from the dictionaries above.
                    if (p.Contains("=(") || p.StartsWith("triggers")) continue;
                    pressed.Add(p);
                }
            }
            return new { sticks, triggers, pads, pressed, motion };
        }
        #endregion
    }
}
