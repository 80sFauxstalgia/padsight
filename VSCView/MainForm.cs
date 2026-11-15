using ExtendInput;
using ExtendInput.Controller;
using ExtendInput.Controls;
using ExtendInput.DeviceProvider;
using Microsoft.Win32;
using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace VSCView
{
    public partial class MainForm : Form
    {
        const int CONTROLLER_CTRICON_WIDTH = 48;//32 + 16;
        const int CONTROLLER_CONICON_WIDTH = 24;//16;
        const int CONTROLLER_ALLICON_HEIGHT = 32;//32;
        const int CONTROLLER_ICON_GAP = 8;//4;

        public static ControllerState state;
        public static SensorCollector sensorData;
        public static int frameTime = (int)(1000 / 60); // 16ms interval => ~62fps

        private bool FirstControllerActivation = true;

        Dictionary<string, ToolStripMenuItem> ThemeMenuItems = new Dictionary<string, ToolStripMenuItem>();

        ControllerData ControllerData;
        IController ActiveController;
        System.Threading.Timer ttimer;

        //List<IControllerFactory> Factory;

        UI ui;

        Settings settings;

        DeviceManager DeviceManager;
        int instanceNumber = 0;

        IconImageManager IconManager;

        Web.OverlayHub overlayHub;
        string currentThemeFile;
        public const int DefaultOverlayPort = 47817;

        public MainForm(int instanceNumber = 0)
        {
            InitializeComponent();
            this.FormBorderStyle = FormBorderStyle.None; // no borders
            this.SetStyle(ControlStyles.ResizeRedraw, true); // this is to avoid visual artifacts

            RegistryKey winLogonKey = Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Services\HidGuardian", false);
            if (winLogonKey != null)
            {
                hIDGuardianWhitelistToolStripMenuItem.Visible = true;
                RegistryKey whitelistKey = Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Services\HidGuardian\Parameters\Whitelist\" + Process.GetCurrentProcess().Id, false);
                hIDGuardianWhitelistToolStripMenuItem.Checked = whitelistKey != null;
            }

            IconManager = new IconImageManager();
            DeviceManager = new DeviceManager();

            ControllerData = new ControllerData();
            state = new ControllerState();
            // 5s lookback for smoothing
            sensorData = new SensorCollector(5, true);

            this.instanceNumber = instanceNumber;

            if (this.instanceNumber > 0)
            {
                this.Text = $"{this.Text} #{(instanceNumber + 1)}";
            }

            LoadThemes();
            LoadSettings();
            InitPanel();
            overlayHub = CreateHub();
            AddOverlayMenu();
            if (File.Exists("ctrl.last"))
            {
                settings.Theme = File.ReadAllText("ctrl.last");
                File.Delete("ctrl.last");
            }
            if(settings.CustomSize)
            {
                this.Width = settings.Width ?? this.Width;
                this.Height = settings.Height ?? this.Height;
            }
            if (!string.IsNullOrWhiteSpace(settings.Theme) && File.Exists(settings.Theme))
            {
                LoadTheme(settings.Theme, true); // we'll just let this task spool off on its own and pray
            }
            if (!string.IsNullOrWhiteSpace(settings.Background))
            {
                try
                {
                    this.BackColor = ColorTranslator.FromHtml(settings.Background);
                }
                catch { }
            }
            tsmiAutoSelectOnlyController.Checked = settings.AutoSelectOnlyController;

            DeviceManager.ControllerAdded += DeviceManager_ControllerAdded;
            DeviceManager.ControllerRemoved += DeviceManager_ControllerRemoved;

//            foreach(IDeviceProvider provider in DeviceManager.GetManualDeviceProviders())
//            {
//                ToolStripItem itm = tsmiManualControllers.DropDownItems.Add(provider.ToString(), null, LoadManualDevice);
//                itm.Tag = provider;
//            }
        }

        private void LoadManualDevice(object sender, EventArgs e)
        {
            IDeviceProvider Provider = null;
            // differentiate between context selection and startup
            if (sender is ToolStripItem)
            {
                ToolStripItem item = (ToolStripItem)sender;
                Provider = (IDeviceProvider)item.Tag;
            }

            if (Provider == null)
                return;

            Provider.ManualTrigger();
        }

        /// <summary>
        /// We need the form loaded first before we can have controllers start to trigger insertion into the menu
        /// </summary>
        /// <param name="sender"></param>
        /// <param name="e"></param>
        private void MainForm_Load(object sender, EventArgs e)
        {
            if (!FirstLoad()) return;
            if (settings.OverlayEnabled ?? true)
                StartOverlayServer();
            LoadControllers(true);
            InitObs();
            RegisterHotkeys();
            BeginInvoke(new Action(AfterStartup));
        }

        #region OBS Browser Source
        ToolStripMenuItem tsmiOverlay;
        ToolStripMenuItem tsmiOverlayEnabled;

        private int OverlayPort => (settings.OverlayPort ?? DefaultOverlayPort) + instanceNumber;

        private void StartOverlayServer()
        {
            if (!overlayHub.Start(OverlayPort))
                MessageBox.Show(this, overlayHub.Error, "OBS Browser Source", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            UpdateOverlayMenu();
        }

        private void AddOverlayMenu()
        {
            tsmiOverlay = new ToolStripMenuItem("OBS Browser Source");
            tsmiOverlayEnabled = new ToolStripMenuItem("Enabled", null, (s, e) =>
            {
                settings.OverlayEnabled = !(settings.OverlayEnabled ?? true);
                SaveSettings();
                if (settings.OverlayEnabled ?? true) StartOverlayServer();
                else { overlayHub.Dispose(); overlayHub = CreateHub(); if (currentThemeFile != null) overlayHub.SetMainTheme(currentThemeFile); }
                UpdateOverlayMenu();
            });
            tsmiOverlay.DropDownItems.Add(new ToolStripMenuItem("Copy URL (follows window theme)", null, (s, e) => CopyText(overlayHub.Url)));
            tsmiOverlay.DropDownItems.Add(new ToolStripMenuItem("Copy URL (pinned to current theme)", null, (s, e) => CopyText(overlayHub.UrlForTheme(currentThemeFile))));
            tsmiOverlay.DropDownItems.Add(new ToolStripMenuItem("Open in browser", null, (s, e) => { try { Process.Start(overlayHub.Url); } catch { } }));
            tsmiOverlay.DropDownItems.Add(new ToolStripMenuItem("Status...", null, (s, e) =>
                MessageBox.Show(this, OverlayStatusText(),
                    "OBS Browser Source", MessageBoxButtons.OK, MessageBoxIcon.Information)));
            tsmiOverlay.DropDownItems.Add(new ToolStripSeparator());
            tsmiOverlay.DropDownItems.Add(tsmiOverlayEnabled);
            cmsMain.Items.Insert(cmsMain.Items.IndexOf(tsmiController) + 1, tsmiOverlay);
            cmsMain.Items.Insert(0, new ToolStripMenuItem("Theme &Browser...", null, (s, e) => ShowThemeBrowser()));
            cmsMain.Items.Insert(cmsMain.Items.IndexOf(tsmiOverlay) + 1, new ToolStripMenuItem("&Settings...", null, (s, e) => ShowSettings()));
            UpdateOverlayMenu();

            followTimer = new System.Windows.Forms.Timer { Interval = 100 };
            followTimer.Tick += (s, e) => FollowTick();
            followTimer.Start();
        }

        private void UpdateOverlayMenu()
        {
            if (tsmiOverlayEnabled == null) return;
            tsmiOverlayEnabled.Checked = settings.OverlayEnabled ?? true;
            tsmiOverlay.ToolTipText = overlayHub.IsRunning ? overlayHub.Url : "Overlay server is off";
        }

        private void CopyText(string text)
        {
            try { Clipboard.SetText(text); } catch { }
        }
        #endregion OBS Browser Source

        #region Settings, theme browser, per-controller themes, follow mode
        /// <summary>Load a theme chosen by the user and report failures instead of dropping them.</summary>
        private async void LoadThemeSafe(string file)
        {
            try { await LoadTheme(file, false); }
            catch (Exception ex)
            {
                MessageBox.Show(this, $"Could not load the theme\n{file}\n\n{ex.Message}", "Theme", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }

        private void ShowThemeBrowser()
        {
            var form = new UiForms.ThemePickerForm(currentThemeFile,
                file => LoadThemeSafe(file),
                file => overlayHub.UrlForTheme(file));
            form.Show(this);
        }

        private void ShowSettings()
        {
            var values = new UiForms.SettingsValues
            {
                OverlayEnabled = settings.OverlayEnabled ?? true,
                OverlayPort = settings.OverlayPort ?? DefaultOverlayPort,
                PortOffset = instanceNumber,
                OverlayFps = settings.OverlayFps ?? 60,
                AutoSelectOnlyController = settings.AutoSelectOnlyController,
                FollowActiveController = settings.FollowActiveController ?? true,
                RememberThemePerController = settings.RememberThemePerController ?? true,
                Background = this.BackColor,
            };
            using (var dlg = new UiForms.SettingsForm(values, OverlayStatusText))
            {
                if (dlg.ShowDialog(this) != DialogResult.OK) return;
            }
            bool restart = values.OverlayEnabled != (settings.OverlayEnabled ?? true)
                        || values.OverlayPort != (settings.OverlayPort ?? DefaultOverlayPort)
                        || values.OverlayFps != (settings.OverlayFps ?? 60);
            settings.OverlayEnabled = values.OverlayEnabled;
            settings.OverlayPort = values.OverlayPort;
            settings.OverlayFps = values.OverlayFps;
            settings.AutoSelectOnlyController = values.AutoSelectOnlyController;
            tsmiAutoSelectOnlyController.Checked = values.AutoSelectOnlyController;
            settings.FollowActiveController = values.FollowActiveController;
            settings.RememberThemePerController = values.RememberThemePerController;
            this.BackColor = values.Background;
            settings.Background = ColorTranslator.ToHtml(this.BackColor);
            SaveSettings();

            if (restart)
            {
                overlayHub.Dispose();
                overlayHub = CreateHub();
                if (currentThemeFile != null) overlayHub.SetMainTheme(currentThemeFile);
                if (settings.OverlayEnabled ?? true) StartOverlayServer();
                // The panel is served by the same server, so follow it to the new port.
                if (panelForm != null && !panelForm.IsDisposed)
                {
                    if (overlayHub.IsRunning) panelForm.Navigate(overlayHub.PanelUrl, $"http://127.0.0.1:{overlayHub.Port}/");
                    else panelForm.Close();
                }
            }
            UpdateOverlayMenu();
            AutoLoadController();
        }

        private string OverlayStatusText()
        {
            string s = overlayHub.IsRunning ? $"Serving {overlayHub.Url}" : ("Server off" + (string.IsNullOrEmpty(overlayHub.Error) ? "" : ": " + overlayHub.Error));
            string stats = overlayHub.StatsText().Trim();
            if (stats.Length > 0) s += Environment.NewLine + stats;
            s += Environment.NewLine + "2026 Steam Controller (SDL3): " + (DeviceManager.SdlStatus ?? "not started");
            return s;
        }

        /// <summary>
        /// The kind of controller, used to remember a theme per kind and to pick a matching default:
        /// DEVICE_SC2026, DEVICE_SC (2015), DEVICE_SC_CHELL, DEVICE_DS5, DEVICE_DS4, DEVICE_XBOX (any XInput pad).
        /// Hardware revisions (e.g. DEVICE_DS4V1/V2) share one kind. Null for an empty receiver slot.
        /// </summary>
        internal static string ControllerKind(IController c)
        {
            string[] codes = c?.ControllerTypeCode;
            if (codes == null) return null;
            foreach (var (code, kind) in KindCodes)
                if (codes.Contains(code)) return kind;
            return codes.FirstOrDefault(t => t != "DEVICE_NONE");
        }

        private static readonly (string code, string kind)[] KindCodes =
        {
            ("DEVICE_SC2026", "DEVICE_SC2026"), ("DEVICE_SC_CHELL", "DEVICE_SC_CHELL"), ("DEVICE_SC", "DEVICE_SC"),
            ("DEVICE_DS5", "DEVICE_DS5"), ("DEVICE_DS4", "DEVICE_DS4"), ("DEVICEXBOX", "DEVICE_XBOX"),
        };

        /// <summary>Which kind of controller a theme file is drawn for (from its family folder), or null for general themes.</summary>
        internal static string ThemeKind(string themeFile)
        {
            if (themeFile == null) return null;
            string full = Path.GetFullPath(themeFile), themes = Path.GetFullPath("themes") + Path.DirectorySeparatorChar;
            if (!full.StartsWith(themes, StringComparison.OrdinalIgnoreCase)) return null;
            string family = full.Substring(themes.Length).Split(Path.DirectorySeparatorChar)[0];
            return ThemeFamilyKinds.TryGetValue(family, out string kind) ? kind : null;
        }

        /// <summary>The theme a controller kind gets: the one the user picked for it, else a built-in default.</summary>
        internal string ThemeForKind(string kind, out bool remembered)
        {
            remembered = false;
            if (kind == null) return null;
            if ((settings.RememberThemePerController ?? true) && settings.ThemeByController != null &&
                settings.ThemeByController.TryGetValue(kind, out string file) && File.Exists(file))
            {
                remembered = true;
                return file;
            }
            return DefaultThemeFor(kind);
        }

        private void RememberThemeForActiveController(string themeFile)
        {
            string kind = ControllerKind(ActiveController);
            if (kind == null || themeFile == null) return;
            if (settings.ThemeByController == null) settings.ThemeByController = new Dictionary<string, string>();
            settings.ThemeByController[kind] = themeFile;
        }

        /// <summary>
        /// Swap the overlay to the right look for the controller now on it: the theme picked for that kind before,
        /// or, when the theme on screen is drawn for a different kind of controller (or none is loaded), the
        /// built-in default for this kind. A general theme the user chose stays as it is.
        /// </summary>
        private void ApplyRememberedTheme()
        {
            if (sceneThemeActive) return; // an OBS scene rule decides the theme for now
            string kind = ControllerKind(ActiveController);
            if (kind == null) return;
            string file = ThemeForKind(kind, out bool remembered);
            if (!remembered)
            {
                string shownKind = ThemeKind(currentThemeFile);
                bool wrongKind = currentThemeFile == null || (shownKind != null && shownKind != kind);
                if (!wrongKind) return;
            }
            if (file == null) return;
            if (currentThemeFile != null && Path.GetFullPath(file).Equals(Path.GetFullPath(currentThemeFile), StringComparison.OrdinalIgnoreCase)) return;
            if (InvokeRequired) BeginInvoke(new Action(() => LoadThemeSafe(file)));
            else LoadThemeSafe(file);
        }

        /// <summary>A built-in theme for a kind of controller, used until the user picks one.</summary>
        internal static string DefaultThemeFor(string kind)
        {
            string[] candidates;
            switch (kind)
            {
                case "DEVICE_SC2026": candidates = new[] { @"themes\steamcontroller2026\realistic\Full.json", @"themes\steamcontroller2026\graphite\Full.json" }; break;
                case "DEVICE_SC": candidates = new[] { @"themes\steamcontroller\realistic\Full.json", @"themes\steamcontroller\graphite\Full.json" }; break;
                case "DEVICE_SC_CHELL": candidates = new[] { @"themes\steamcontrollerchell\default\all.json" }; break;
                case "DEVICE_DS5": candidates = new[] { @"themes\dualsense\default\midnight black\All.json" }; break;
                case "DEVICE_DS4": candidates = new[] { @"themes\dualshock4\default\V2\jet black\all.json" }; break;
                case "DEVICE_XBOX": candidates = new[] { @"themes\xboxwirelesscontroller\default\Xbox One S\XB1 S (Black).json", @"themes\xbox360controller\default\XB360 (Black).json" }; break;
                default: return null;
            }
            return candidates.FirstOrDefault(File.Exists);
        }

        System.Windows.Forms.Timer followTimer;
        readonly HashSet<IController> followReading = new HashSet<IController>();
        readonly Dictionary<IController, DateTime> lastUsed = new Dictionary<IController, DateTime>();

        /// <summary>
        /// Follow mode: keep every connected controller reading and switch the window (and so every OBS source)
        /// to whichever one is being used. The current controller must be idle for 2 s before a switch, so
        /// holding one controller while the other sits on the desk doesn't flap.
        /// </summary>
        private void FollowTick()
        {
            UpdateStatusSnapshot();
            if (!(settings.FollowActiveController ?? true)) return;

            // UI thread only (see PostToUi), so no lock is needed.
            List<IController> present = ControllerMemoHack.Values.Select(v => v.Item1).Where(c => c.IsPresent).ToList();
            // XInput slots include Steam's virtual Xbox pads, which mirror whatever real controller is in use, so
            // they would always "win". Ignore them whenever a controller with its own driver is connected.
            if (present.Any(c => !(c is XInputController)))
                present = present.Where(c => !(c is XInputController)).ToList();
            if (present.Count == 0) return;
            // One controller already on the overlay: nothing to follow. One controller and nothing on the
            // overlay yet: put it there as soon as it's used ("press any button" in the setup).
            if (present.Count == 1 && ActiveController == present[0] && ActiveController.IsPresent) return;

            DateTime now = DateTime.UtcNow;
            foreach (IController c in present)
            {
                if (!followReading.Contains(c) && c != ActiveController)
                {
                    try { c.Initalize(); followReading.Add(c); } catch { }
                }
                ControllerState st = null;
                try { st = c.GetState(); } catch { }
                if (IsInUse(st)) lastUsed[c] = now;
            }

            IController candidate = present.Where(c => c != ActiveController && lastUsed.ContainsKey(c))
                                           .OrderByDescending(c => lastUsed[c]).FirstOrDefault();
            if (candidate == null || (now - lastUsed[candidate]).TotalMilliseconds > 300) return;

            DateTime activeLast = (ActiveController != null && lastUsed.TryGetValue(ActiveController, out var t)) ? t : DateTime.MinValue;
            if (ActiveController != null && ActiveController.IsPresent && (now - activeLast).TotalSeconds < 2) return;

            ActivateController(candidate, deinitializePrevious: false);
        }

        private volatile string statusSnapshot = "{}";

        /// <summary>
        /// UI thread: build the JSON served at /status.json (controllers, SDL, channels, live inputs of the
        /// active controller). Built here so the server thread never touches UI-thread state.
        /// </summary>
        private void UpdateStatusSnapshot()
        {
            try
            {
                var controllers = ControllerMemoHack.Values.Select(v => v.Item1).Select(c => new
                {
                    name = c.Name,
                    kind = ControllerKind(c),
                    present = c.IsPresent,
                    active = c == ActiveController,
                    reading = c == ActiveController || followReading.Contains(c),
                    inputs = (c == ActiveController || followReading.Contains(c)) ? DescribeInputs(SafeState(c)) : null,
                }).ToList();
                var snap = new
                {
                    app = "PadSight",
                    theme = currentThemeFile,
                    followMode = settings.FollowActiveController ?? true,
                    sdl = DeviceManager.SdlStatus,
                    overlay = overlayHub.IsRunning ? overlayHub.Url : null,
                    controllers,
                    channels = overlayHub.ChannelStats(),
                };
                statusSnapshot = JsonConvert.SerializeObject(snap);
                overlayHub.StatusJson = () => statusSnapshot;
            }
            catch (Exception ex) { Debug.WriteLine("status: " + ex.Message); }
        }

        private static ControllerState SafeState(IController c)
        {
            try { return c.GetState(); } catch { return null; }
        }

        /// <summary>Active inputs as "control:key=value" strings (for diagnostics).</summary>
        private static List<string> DescribeInputs(ControllerState s)
        {
            var list = new List<string>();
            if (s?.Controls == null) return list;
            foreach (string k in s.Controls.Keys)
            {
                switch (s.Controls[k])
                {
                    case ControlButton b: if (b.Button0) list.Add(k); break;
                    case ControlButtonPair p: if (p.Left.Button0) list.Add(k + ":l"); if (p.Right.Button0) list.Add(k + ":r"); break;
                    case ControlButtonQuad q:
                        if (q.ButtonN) list.Add(k + ":n"); if (q.ButtonE) list.Add(k + ":e");
                        if (q.ButtonS) list.Add(k + ":s"); if (q.ButtonW) list.Add(k + ":w"); break;
                    case ControlDPad d: if (d.Direction != EDPadDirection.None) list.Add(k + "=" + d.Direction); break;
                    case ControlTriggerPair tr:
                        if (tr.Left.Analog > 0.02f || tr.Left.Stage2) list.Add($"{k}:l={tr.Left.Analog:0.00}{(tr.Left.Stage2 ? "+stage2" : "")}");
                        if (tr.Right.Analog > 0.02f || tr.Right.Stage2) list.Add($"{k}:r={tr.Right.Analog:0.00}{(tr.Right.Stage2 ? "+stage2" : "")}");
                        break;
                    case ControlStick st:
                        if (st.Click || Math.Abs(st.X) > 0.08f || Math.Abs(st.Y) > 0.08f)
                            list.Add($"{k}=({st.X:0.00},{st.Y:0.00}){(st.Click ? "+click" : "")}");
                        break;
                    case ControlTouch tc:
                        for (int i = 0; i < tc.TouchCount; i++)
                            if (tc.Touch[i]) list.Add($"{k}:{i}=({tc.X[i]:0.00},{tc.Y[i]:0.00})");
                        if (tc.Click) list.Add(k + ":click");
                        break;
                    case Input.ControlTouchPressure tp:
                        if (tp.Touch) list.Add($"{k}=({tp.X:0.00},{tp.Y:0.00}) p={tp.Pressure:0.00}");
                        if (tp.Click) list.Add(k + ":click");
                        break;
                }
            }
            return list;
        }

        private static bool IsInUse(ControllerState s)
        {
            if (s?.Controls == null) return false;
            foreach (string k in s.Controls.Keys)
            {
                switch (s.Controls[k])
                {
                    case ControlButton b: if (b.Button0) return true; break;
                    case ControlButtonPair p: if (p.Left.Button0 || p.Right.Button0) return true; break;
                    case ControlButtonQuad q: if (q.ButtonN || q.ButtonE || q.ButtonS || q.ButtonW) return true; break;
                    case ControlDPad d: if (d.Direction != EDPadDirection.None) return true; break;
                    case ControlTriggerPair tr: if (tr.Left.Analog > 0.25f || tr.Right.Analog > 0.25f || tr.Left.Stage2 || tr.Right.Stage2) return true; break;
                    case ControlStick st: if (st.Click || Math.Abs(st.X) > 0.4f || Math.Abs(st.Y) > 0.4f) return true; break;
                    case ControlTouch tc: if (tc.Click || tc.Touch.Any(x => x)) return true; break;
                    case Input.ControlTouchPressure tp: if (tp.Click || tp.Touch) return true; break;
                }
            }
            return false;
        }

        private void ActivateController(IController controller, bool deinitializePrevious)
        {
            if (controller == null || controller == ActiveController) return;
            if (deinitializePrevious && !followReading.Contains(ActiveController)) ActiveController?.DeInitalize();
            ActiveController = controller;
            ControllerData.SetController(ActiveController);
            if (ActiveController is SteamController sc)
                sc.EnableMotion = settings.HackScMotionOn;
            ActiveController.Initalize();
            ui?.InitalizeController();
            overlayHub?.ControllerChanged();
            ApplyRememberedTheme();
        }
        #endregion

        #region Resizeing
        private const int HTLEFT = 10;
        private const int HTRIGHT = 11;
        private const int HTTOP = 12;
        private const int HTTOPLEFT = 13;
        private const int HTTOPRIGHT = 14;
        private const int HTBOTTOM = 15;
        private const int HTBOTTOMLEFT = 16;
        private const int HTBOTTOMRIGHT = 17;

        const int cornerSize = 10; // you can rename this variable if you like

        Rectangle TopRect { get { return new Rectangle(0, 0, this.ClientSize.Width, cornerSize); } }
        Rectangle LeftRect { get { return new Rectangle(0, 0, cornerSize, this.ClientSize.Height); } }
        Rectangle BottomRect { get { return new Rectangle(0, this.ClientSize.Height - cornerSize, this.ClientSize.Width, cornerSize); } }
        Rectangle RightRect { get { return new Rectangle(this.ClientSize.Width - cornerSize, 0, cornerSize, this.ClientSize.Height); } }

        Rectangle TopLeftRect { get { return new Rectangle(0, 0, cornerSize, cornerSize); } }
        Rectangle TopRightRect { get { return new Rectangle(this.ClientSize.Width - cornerSize, 0, cornerSize, cornerSize); } }
        Rectangle BottomLeftRect { get { return new Rectangle(0, this.ClientSize.Height - cornerSize, cornerSize, cornerSize); } }
        Rectangle BottomRightRect { get { return new Rectangle(this.ClientSize.Width - cornerSize, this.ClientSize.Height - cornerSize, cornerSize, cornerSize); } }

        protected override void WndProc(ref Message message)
        {
            if (HandleHotkeyMessage(ref message)) return;
            base.WndProc(ref message);

            if (message.Msg == 0x84) // WM_NCHITTEST
            {
                var cursor = this.PointToClient(Cursor.Position);

                if (TopLeftRect.Contains(cursor)) message.Result = (IntPtr)HTTOPLEFT;
                else if (TopRightRect.Contains(cursor)) message.Result = (IntPtr)HTTOPRIGHT;
                else if (BottomLeftRect.Contains(cursor)) message.Result = (IntPtr)HTBOTTOMLEFT;
                else if (BottomRightRect.Contains(cursor)) message.Result = (IntPtr)HTBOTTOMRIGHT;

                else if (TopRect.Contains(cursor)) message.Result = (IntPtr)HTTOP;
                else if (LeftRect.Contains(cursor)) message.Result = (IntPtr)HTLEFT;
                else if (RightRect.Contains(cursor)) message.Result = (IntPtr)HTRIGHT;
                else if (BottomRect.Contains(cursor)) message.Result = (IntPtr)HTBOTTOM;
            }
        }
        #endregion Resizeing

        private void Render(object stateInfo)
        {
            var state = new ControllerState();
            if (ActiveController != null)
            {
                state = ActiveController.GetState();
                if (ActiveController.HasMotion)
                    sensorData.Update(state);
            }

            if (!this.IsDisposed && this.InvokeRequired && sensorData != null)
            {
                try
                {
                    this.Invoke(new Action(() =>
                    {// force a full repaint
                        this.Invalidate();
                    }));
                }
                catch (ObjectDisposedException e) { /* eat the Disposed exception when exiting */ }
            }
        }

        private string settingsFile;
        private void LoadSettings()
        {
            string filename = "settings.json";
            if (instanceNumber > 0)
                filename = $"settings.{instanceNumber}.json";

            settingsFile = filename;
            if (!File.Exists(filename)) File.Create(filename).Close();
            settings = JsonConvert.DeserializeObject<Settings>(File.ReadAllText(filename)) ?? new Settings();
        }
        private void SaveSettings()
        {
            File.WriteAllText(settingsFile ?? "settings.json", JsonConvert.SerializeObject(settings));
        }
        private void LoadThemes()
        {
            tsmiTheme.DropDownItems.Clear();
            ThemeMenuItems.Clear();

            if (!Directory.Exists("themes")) Directory.CreateDirectory("themes");
            IEnumerable<string> themeParents = Directory.EnumerateFiles("themes", "theme.json", SearchOption.AllDirectories)
                                                        .OrderBy(dr => dr.Split(new char[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar }, StringSplitOptions.RemoveEmptyEntries).Skip(1).FirstOrDefault())
                                                        .ThenBy(dr => (dr.Split(new char[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar }, StringSplitOptions.RemoveEmptyEntries).Skip(2).FirstOrDefault()?.ToLowerInvariant() ?? string.Empty) == "default" ? 0 : 1)
                                                        .ThenBy(dr => dr);
            themeParents = themeParents.Select(dr => Path.GetDirectoryName(dr)).Distinct().ToArray();

            foreach (string themeParent in themeParents)
            {
                string[] PathMiddleParts = themeParent.Split(Path.DirectorySeparatorChar).Reverse().Skip(1).Reverse().Skip(1).ToArray();

                ToolStripMenuItem parentMenuItem = tsmiTheme;
                for (int j = 0; j < PathMiddleParts.Length; j++)
                {
                    string dir_key = string.Join(Path.DirectorySeparatorChar.ToString(), PathMiddleParts.Take(j + 1).ToArray());
                    if (!ThemeMenuItems.ContainsKey(dir_key))
                    {
                        string nameFile = Path.Combine("themes", dir_key, "name.txt");
                        string icon_file = Path.Combine("themes", dir_key, "icon.png");
                        string name = File.Exists(nameFile) ? File.ReadAllText(nameFile).Trim() : null;
                        if (string.IsNullOrWhiteSpace(name))
                            name = PathMiddleParts.Skip(j).First();
                        ThemeMenuItems[dir_key] = new ToolStripMenuItem(name);
                        if (File.Exists(icon_file))
                        {
                            ThemeMenuItems[dir_key].Image = Image.FromFile(icon_file);
                            ThemeMenuItems[dir_key].ImageScaling = ToolStripItemImageScaling.None;
                        }
                        parentMenuItem.DropDownItems.Add(ThemeMenuItems[dir_key]);
                    }
                    parentMenuItem = ThemeMenuItems[dir_key];
                }

                string ThemeName = Path.GetFileName(themeParent);
                try
                {
                    string themeMetaFile = Path.Combine(themeParent, "theme.json");
                    if (File.Exists(themeMetaFile))
                    {
                        ThemeDesc desc = JsonConvert.DeserializeObject<ThemeDesc>(File.ReadAllText(themeMetaFile));
                        if (!string.IsNullOrWhiteSpace(desc.name))
                            ThemeName = desc.name;
                    }
                }
                catch { }

                ToolStripMenuItem itmTop = new ToolStripMenuItem(ThemeName);
                string themeIconFile = Path.Combine(themeParent, "icon.png");
                if (File.Exists(themeIconFile))
                {
                    itmTop.Image = Image.FromFile(themeIconFile);
                    itmTop.ImageScaling = ToolStripItemImageScaling.None;
                }
                parentMenuItem.DropDownItems.Add(itmTop);

                IEnumerable<string> themeFiles = Directory.EnumerateFiles(themeParent, "*.json", SearchOption.TopDirectoryOnly);
                foreach (string themeFile in themeFiles)
                {
                    string ThemeFileName = Path.GetFileNameWithoutExtension(themeFile);

                    if (ThemeFileName.ToLowerInvariant() == "theme")
                        continue;

                    string DisplayName = ThemeFileName;

                    try
                    {
                        ThemeSubDesc desc = JsonConvert.DeserializeObject<ThemeSubDesc>(File.ReadAllText(themeFile));
                        if (!string.IsNullOrWhiteSpace(desc.name))
                            DisplayName = desc.name;
                    }
                    catch { }

                    ToolStripItem itm = new ToolStripMenuItem(DisplayName, null, LoadTheme);
                    itm.Tag = themeFile;
                    itmTop.DropDownItems.Add(itm);
                }
            }
        }

        private void LoadControllers(bool firstload)
        {
            DeviceManager.ScanNow();
        }

        Dictionary<string, (IController, ToolStripItem)> ControllerMemoHack = new Dictionary<string, (IController, ToolStripItem)>();
        // Device events arrive on HID/SDL threads. Everything that touches ControllerMemoHack, the menu or the
        // active controller is marshalled to the UI thread with BeginInvoke (never a blocking Invoke while
        // holding a lock), so the UI thread is the only one that reads or writes that state.
        private void PostToUi(MethodInvoker action)
        {
            try
            {
                if (this.IsDisposed || this.Disposing) return;
                if (this.IsHandleCreated) this.BeginInvoke(action);
                else action();
            }
            catch (ObjectDisposedException) { /* exiting */ }
            catch (InvalidOperationException) { /* handle torn down while exiting */ }
        }

        private void DeviceManager_ControllerAdded(object sender, IController controller)
        {
            {
                PostToUi(delegate
                {
                    string NiceName = controller.Name;
                    {
                        string[] ExtraNameBits = controller.NameDetails;
                        if (ExtraNameBits != null)
                            foreach (string ExtraNameBit in ExtraNameBits)
                                NiceName += "\r\n" + ExtraNameBit;
                    }
                    ToolStripMenuItem itm = new ToolStripMenuItem(NiceName, null, LoadController);
                    tsmiController.DropDownItems.Add(itm);
                    IController c = controller;
                    ControllerMemoHack[c.DeviceHackRef.UniqueKey] = (controller, itm);
                    controller.ControllerMetadataUpdate += (IController ctrl) =>
                    {
                        try
                        {
                            if (this.Created && !this.Disposing && !this.IsDisposed)
                                this.Invoke(new Action(() =>
                                {
                                    string NiceName_ = controller.Name;
                                    {
                                        string[] ExtraNameBits = controller.NameDetails;
                                        if (ExtraNameBits != null)
                                            foreach (string ExtraNameBit in ExtraNameBits)
                                                NiceName_ += "\r\n" + ExtraNameBit;
                                    }
                                    itm.Text = NiceName_;
                                    UpdateIcon(itm);
                                    UpdateAlternateControllers(itm);
                                    AutoLoadController();
                                }));
                        }
                        catch (ObjectDisposedException e) { /* eat the Disposed exception when exiting */ }
                    };
                    itm.Text = NiceName;

                    itm.ImageScaling = ToolStripItemImageScaling.None;
                    itm.Tag = controller;

                    UpdateIcon(itm);
                    UpdateAlternateControllers(itm);

                    // load the first controller in the list if it exists
                    //if (firstload && i == 0 && Controllers[i] != null)
                    //    LoadController(Controllers[i], null);
                    AutoLoadController();
                });
            }
        }

        private void UpdateIcon(ToolStripItem itm)
        {
            Image oldIcon = itm.Image;
            IController controller = (IController)itm.Tag;

            {
                Image ConnectionImg = null;
                Image ControllerImg = null;
                if (controller.ConnectionTypeCode != null)
                    foreach (string conType in controller.ConnectionTypeCode)
                    {
                        Image connectionIcon = IconManager.GetImage(conType);
                        if (connectionIcon != null)
                        {
                            ConnectionImg = connectionIcon;
                            break;
                        }
                    }

                if (controller.ControllerTypeCode != null)
                    foreach (string conType in controller.ControllerTypeCode)
                    {
                        Image controllerIcon = IconManager.GetImage(conType);
                        if(controllerIcon != null)
                        {
                            ControllerImg = controllerIcon;
                            break;
                        }
                    }

                if (ConnectionImg != null || ControllerImg != null)
                {
                    Image Icon = new Bitmap(CONTROLLER_CONICON_WIDTH + CONTROLLER_ICON_GAP + CONTROLLER_CTRICON_WIDTH, CONTROLLER_ALLICON_HEIGHT);
                    Graphics g = Graphics.FromImage(Icon);
                    if (ConnectionImg != null)
                    {
                        Size TargetSize = ConnectionImg.Size;
                        float ratio = 1.0f;
                        if (TargetSize.Width > CONTROLLER_CONICON_WIDTH)
                        {
                            ratio = (1.0f * CONTROLLER_CONICON_WIDTH / TargetSize.Width);
                        }
                        if (TargetSize.Height > CONTROLLER_ALLICON_HEIGHT)
                        {
                            float ratio2 = (1.0f * CONTROLLER_ALLICON_HEIGHT / TargetSize.Height);
                            if (ratio2 < ratio)
                                ratio = ratio2;
                        }
                        TargetSize = new Size((int)(TargetSize.Width * ratio), (int)(TargetSize.Height * ratio));

                        g.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
                        g.DrawImage(ConnectionImg, ((CONTROLLER_CONICON_WIDTH - TargetSize.Width) / 2f), (CONTROLLER_ALLICON_HEIGHT - TargetSize.Height) / 2f, TargetSize.Width, TargetSize.Height);
                    }
                    if (ControllerImg != null)
                    {
                        Size TargetSize = ControllerImg.Size;
                        float ratio = 1.0f;
                        if (TargetSize.Width > CONTROLLER_CTRICON_WIDTH)
                        {
                            ratio = (1.0f * CONTROLLER_CTRICON_WIDTH / TargetSize.Width);
                        }
                        if (TargetSize.Height > CONTROLLER_ALLICON_HEIGHT)
                        {
                            float ratio2 = (1.0f * CONTROLLER_ALLICON_HEIGHT / TargetSize.Height);
                            if (ratio2 < ratio)
                                ratio = ratio2;
                        }
                        TargetSize = new Size((int)(TargetSize.Width * ratio), (int)(TargetSize.Height * ratio));

                        g.DrawImage(ControllerImg, 16 + CONTROLLER_ICON_GAP + ((CONTROLLER_CTRICON_WIDTH - TargetSize.Width) / 2f), (CONTROLLER_ALLICON_HEIGHT - TargetSize.Height) / 2f, TargetSize.Width, TargetSize.Height);
                    }
                    itm.Image = Icon;
                }

                //ConnectionImg?.Dispose();
                //ControllerImg?.Dispose();
            }

            oldIcon?.Dispose();
        }

        private void UpdateAlternateControllers(ToolStripMenuItem itm)
        {
            IController controller = (IController)itm.Tag;

            itm.DropDownItems.Clear();
            if(controller.HasSelectableAlternatives)
            {
                foreach(var kv in controller.Alternates)
                {
                    itm.DropDownItems.Add(kv.Value, null, SetActiveAlternateController).Tag = new Tuple<IController, string>(controller, kv.Key);
                }
            }
        }

        private void SetActiveAlternateController(object sender, EventArgs e)
        {
            // differentiate between context selection and startup
            if (sender is ToolStripItem)
            {
                ToolStripItem item = (ToolStripItem)sender;
                Tuple<IController, string> ctl = (Tuple<IController, string>)item.Tag;
                new Thread(() =>
                {
                    ctl.Item1.SetActiveAlternateController(ctl.Item2);
                }).Start();
            }
        }

        private void DeviceManager_ControllerRemoved(object sender, ExtendInput.DeviceProvider.IDevice e)
        {
            {
                PostToUi(delegate
                {
                    if (ControllerMemoHack.ContainsKey(e.UniqueKey))
                    {
                        IController RemovedController = ControllerMemoHack[e.UniqueKey].Item1;
                        RemovedController.DeInitalize();
                        RemovedController.Dispose();
                        tsmiController.DropDownItems.Remove(ControllerMemoHack[e.UniqueKey].Item2);
                        ControllerMemoHack.Remove(e.UniqueKey);
                        followReading.Remove(RemovedController);
                        lastUsed.Remove(RemovedController);
                        if (ActiveController == RemovedController)
                            ActiveController = null;
                    }
                    AutoLoadController();
                });
            }
        }

        private void LoadController(object sender, EventArgs e)
        {
            if (ActiveController != null)
                { ActiveController.DeInitalize(); followReading.Remove(ActiveController); }

            // differentiate between context selection and startup
            if (sender is ToolStripItem)
            {
                ToolStripItem item = (ToolStripItem)sender;
                ActiveController = (IController)item.Tag;
            }
            else
                ActiveController = (IController)sender;

            ControllerData.SetController(ActiveController);
            if (ActiveController is SteamController)
                (ActiveController as SteamController).EnableMotion = settings.HackScMotionOn;
            ActiveController.Initalize();

            new Thread(() =>
            {
                ActiveController.Identify();
            }).Start();

            ui?.InitalizeController();
            overlayHub?.ControllerChanged();
            ApplyRememberedTheme();
        }

        private void AutoLoadController()
        {
            if (!settings.AutoSelectOnlyController)
                return;

            if (ActiveController != null)
            {
                if (ActiveController.IsPresent)
                    return;
            }

            IController FirstActiveController = null;
            foreach (ToolStripItem item in tsmiController.DropDownItems)
            {
                IController CandidateController = (IController)item.Tag;
                if (CandidateController.IsPresent)
                {
                    if (FirstActiveController != null)
                    {
                        // we found a 2nd present controller, so just give up
                        FirstActiveController = null;
                        break;
                    }
                    FirstActiveController = CandidateController;
                }
            }

            if (FirstActiveController == ActiveController)
                return;

            if (ActiveController != null) { ActiveController.DeInitalize(); followReading.Remove(ActiveController); }
            ActiveController = null;

            if (FirstActiveController == null)
                return;

            ActiveController = FirstActiveController;

            ControllerData.SetController(ActiveController);
            if (ActiveController is SteamController)
                (ActiveController as SteamController).EnableMotion = settings.HackScMotionOn;
            ActiveController.Initalize();

            if (FirstControllerActivation)
                new Thread(() =>
                {
                    ActiveController.Identify();
                }).Start();

            ui?.InitalizeController();
            overlayHub?.ControllerChanged();
            ApplyRememberedTheme();
            FirstControllerActivation = false;
        }

        private async void LoadTheme(object sender, EventArgs e)
        {
            ToolStripItem item = (ToolStripItem)sender;

            await LoadTheme((string)item.Tag, false);
        }

        private async Task LoadTheme(string path, bool initialLoad = false)
        {
            string skinJson = File.ReadAllText(path);

            {
                ThemeFixer.UI ui = JsonConvert.DeserializeObject<ThemeFixer.UI>(skinJson);
                ui.Update();
                skinJson = JsonConvert.SerializeObject(ui, Formatting.Indented);
            }

            UI oldUi = ui;
            ui = new UI(ControllerData, Path.GetDirectoryName(path), skinJson);
            oldUi?.Dispose(); // UI thread only; OnPaint also runs here, so nothing else is using it
            currentThemeFile = path;
            try { overlayHub?.SetMainTheme(path); } catch (Exception ex) { Debug.WriteLine("Overlay theme: " + ex); }
            if (!settings.CustomSize)
            {
                this.Width = ui.Width;
                this.Height = ui.Height;
            }

            if (!initialLoad)
            {
                settings.Theme = path;
                RememberThemeForActiveController(path);
                SaveSettings();
            }

            lblHint1.Hide();
            lblHint2.Hide();

            ttimer?.Dispose();
            ttimer = new System.Threading.Timer(new TimerCallback(Render), null, 0, frameTime);
        }

        #region Drag Anywhere
        private const int WM_NCLBUTTONDOWN = 0xA1;
        private const int HT_CAPTION = 0x2;

        private void MainForm_MouseDown(object sender, MouseEventArgs e)
        {
            if (e.Button == MouseButtons.Left)
            {
                NativeMethods.NativeReleaseCapture();
                NativeMethods.NativeSendMessage(Handle, WM_NCLBUTTONDOWN, HT_CAPTION, (IntPtr)0);
            }
        }
        #endregion Drag Anywhere

        protected override void OnPaint(PaintEventArgs e)
        {
            // Call the OnPaint method of the base class.  
            base.OnPaint(e);

            if (ui != null)
            {
                float ratioWidth = 1.0f * this.Width / ui.Width;
                float ratioHeight = 1.0f * this.Height / ui.Height;
                float ratio = Math.Min(ratioWidth, ratioHeight);

                //Matrix preserve = e.Graphics.Transform;

                e.Graphics.TranslateTransform(ui.Width * (ratioWidth - ratio) / 2, ui.Height * (ratioHeight - ratio) / 2);
                e.Graphics.ScaleTransform(ratio, ratio);

                ui.Paint(e.Graphics);

                //e.Graphics.Transform = preserve;
            }
        }

        private void tsmiExit_Click(object sender, EventArgs e)
        {
            ttimer?.Change(Timeout.Infinite, Timeout.Infinite);
            this.Close();
        }

        private void tsmiReloadThemes_Click(object sender, EventArgs e)
        {
            LoadThemes();
        }

        private void tsmiReloadControllers_Click(object sender, EventArgs e)
        {
            LoadControllers(false);
        }

        private void tsmiAbout_Click(object sender, EventArgs e)
        {
            new About().ShowDialog();
        }

        private void tsmiSetBackgroundColor_Click(object sender, EventArgs e)
        {
            if (colorDialog1.ShowDialog() == DialogResult.OK)
            {
                this.BackColor = colorDialog1.Color;
                settings.Background = ColorTranslator.ToHtml(this.BackColor);
                SaveSettings();
            }
        }

        private void MainForm_FormClosed(object sender, FormClosedEventArgs e)
        {
            ttimer?.Change(Timeout.Infinite, Timeout.Infinite);
            DisposePanel();
            obs?.Dispose();
            overlayHub?.Dispose();
            DeviceManager.Shutdown();
            ControllerMemoHack?.ToList()?.ForEach(dr =>
            {
                dr.Value.Item1.DeInitalize();
                dr.Value.Item1.Dispose();
            });
        }

        private void MinimizeToolStripMenuItem_Click(object sender, EventArgs e)
        {
            this.WindowState = FormWindowState.Minimized;
        }

        private void HIDGuardianWhitelistToolStripMenuItem_Click(object sender, EventArgs e)
        {
            Process.Start(new ProcessStartInfo()
            {
                FileName = System.Reflection.Assembly.GetEntryAssembly().Location,
                Arguments = $"admin {settings.PreviousPid} {Process.GetCurrentProcess().Id}",
                UseShellExecute = true,
                Verb = "runas",
            }).WaitForExit();
            settings.PreviousPid = Process.GetCurrentProcess().Id;
            SaveSettings();
            RegistryKey whitelistKey = Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Services\HidGuardian\Parameters\Whitelist\" + Process.GetCurrentProcess().Id, false);
            hIDGuardianWhitelistToolStripMenuItem.Checked = whitelistKey != null;
        }

        private void TsmiResetWindowSize_Click(object sender, EventArgs e)
        {
            if (ui != null)
            {
                this.Width = ui.Width;
                this.Height = ui.Height;
                settings.CustomSize = false;
                settings.Width = null;
                settings.Height = null;
                SaveSettings();
            }
        }

        private void MainForm_ResizeEnd(object sender, EventArgs e)
        {
            if (ui != null)
                if (ui.Width != this.Width || ui.Height != this.Height)
                {
                    settings.CustomSize = true;
                    settings.Width = this.Width;
                    settings.Height = this.Height;
                }
                else
                {
                    this.Width = ui.Width;
                    this.Height = ui.Height;
                    settings.CustomSize = false;
                    settings.Width = null;
                    settings.Height = null;
                }
            SaveSettings();
        }

        private void tsmiAutoSelectOnlyController_Click(object sender, EventArgs e)
        {
            tsmiAutoSelectOnlyController.Checked = !tsmiAutoSelectOnlyController.Checked;
            settings.AutoSelectOnlyController = tsmiAutoSelectOnlyController.Checked;
            SaveSettings();
            AutoLoadController();
        }

        private void tsmiHackSCMotion_Click(object sender, EventArgs e)
        {
            tsmiHackSCMotion.Checked = !tsmiHackSCMotion.Checked;
            settings.HackScMotionOn = tsmiHackSCMotion.Checked;
            SaveSettings();
        }
    }

    public class NativeMethods
    {
        [DllImport("user32.dll")]
        public static extern IntPtr SendMessage(IntPtr hWnd, int Msg, int wParam, IntPtr lParam);
        [DllImport("user32.dll")]
        private static extern bool ReleaseCapture();

        [DllImport("winmm.dll", EntryPoint = "timeBeginPeriod", SetLastError = true)]
        private static extern uint TimeBeginPeriod(uint delay);
        [DllImport("winmm.dll", EntryPoint = "timeEndPeriod", SetLastError = true)]
        private static extern uint TimeEndPeriod(uint delay);

        public static IntPtr NativeSendMessage(IntPtr hWnd, int Msg, int wParam, IntPtr lParam)
        {
            return SendMessage(hWnd, Msg, wParam, lParam);
        }

        public static bool NativeReleaseCapture()
        {
            return ReleaseCapture();
        }

        public static uint NativeTimeBeginPeriod(int delay)
        {
            return TimeBeginPeriod((uint)delay);
        }

        public static uint NativeTimeEndPeriod(int delay)
        {
            return TimeEndPeriod((uint)delay);
        }
    }
}
