using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace VSCView.Web
{
    /// <summary>
    /// Wires the overlay server to VSCView: one "main" channel that mirrors whatever theme the window shows,
    /// plus optional per-URL channels (<c>?theme=steamcontroller2026/default/Full.json</c>) so several OBS
    /// sources can show different themes at once. All channels read the window's active controller.
    /// </summary>
    public sealed class OverlayHub : IDisposable
    {
        private readonly ControllerData controllerData;
        private readonly Dictionary<string, OverlayChannel> channels = new Dictionary<string, OverlayChannel>(StringComparer.OrdinalIgnoreCase);
        private readonly string themesRoot;
        private string mainThemeFile;
        private OverlayServer server;

        private int defaultFps = 60;
        public int DefaultFps { get => defaultFps; set => defaultFps = ClampFps(value); }
        public int Port => server?.Port ?? 0;
        public string Error => server?.Error;
        public bool IsRunning => server?.IsRunning ?? false;

        public OverlayHub(ControllerData controllerData)
        {
            this.controllerData = controllerData;
            themesRoot = Path.GetFullPath("themes");
        }

        public bool Start(int port)
        {
            server?.Dispose();
            server = new OverlayServer(port, Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "wwwroot"), ChannelForQuery)
            {
                StatusJson = () => StatusJson?.Invoke() ?? "{}",
                Api = req => Api?.Invoke(req),
                ApiKey = ApiKey,
                Preview = PreviewPng,
            };
            return server.Start();
        }

        public string Url => $"http://127.0.0.1:{Port}/";

        /// <summary>Supplied by the window: a JSON snapshot for /status.json.</summary>
        public Func<string> StatusJson { get; set; }

        /// <summary>Supplied by the window: the control panel API (key and Origin are checked by the server).</summary>
        public Func<ApiRequest, ApiResponse> Api { get; set; }

        /// <summary>Per-install control panel key. Set before <see cref="Start"/>.</summary>
        public string ApiKey
        {
            get => apiKey;
            set { apiKey = value; if (server != null) server.ApiKey = value; } // takes effect immediately
        }
        private string apiKey;

        /// <summary>Control panel address; the key travels in the fragment, which browsers never send to a server.</summary>
        public string PanelUrl => $"{Url}panel/#k={ApiKey}";

        private readonly Dictionary<string, byte[]> previews = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase);
        private readonly object previewLock = new object();

        /// <summary>Idle render of a theme (no controller attached), cached. Null for unknown or broken themes.</summary>
        public byte[] PreviewPng(string rel)
        {
            string file = ResolveThemeFile(rel ?? "");
            if (file == null) return null;
            lock (previewLock)
            {
                if (previews.TryGetValue(file, out byte[] cached)) return cached;
                byte[] png = null;
                try
                {
                    using (UI ui = LoadUi(file, new ControllerData()))
                    using (var bmp = new System.Drawing.Bitmap(Math.Max(1, ui.Width), Math.Max(1, ui.Height), System.Drawing.Imaging.PixelFormat.Format32bppArgb))
                    {
                        using (var g = System.Drawing.Graphics.FromImage(bmp))
                        {
                            g.Clear(System.Drawing.Color.Transparent);
                            ui.Paint(g);
                        }
                        using (var ms = new MemoryStream())
                        {
                            bmp.Save(ms, System.Drawing.Imaging.ImageFormat.Png);
                            png = ms.ToArray();
                        }
                    }
                }
                catch (Exception ex) { System.Diagnostics.Debug.WriteLine($"Preview {rel}: {ex.Message}"); }
                if (previews.Count > 200) previews.Clear();
                previews[file] = png;
                return png;
            }
        }

        /// <summary>Theme path relative to themes/ with forward slashes (as used in URLs), or null.</summary>
        public string ThemeKey(string themeFile) => RelativeThemePath(themeFile);

        /// <summary>Full path of a URL theme path, or null if it isn't a theme layout inside themes/.</summary>
        public string ThemeFile(string rel) => ResolveThemeFile(rel ?? "");

        public List<object> ChannelStats()
        {
            return Snapshot().Select(ch => (object)new
            {
                key = ch.Key, clients = ch.ClientCount, obs = ch.ExternalClientCount, fps = ch.Fps,
                renderMs = Math.Round(ch.AvgRenderMs, 2), pngMs = Math.Round(ch.AvgEncodeMs, 2),
                sent = ch.FramesSent, unchanged = ch.FramesSkipped,
            }).ToList();
        }

        /// <summary>Theme-specific URL for the theme currently shown in the window.</summary>
        public string UrlForTheme(string themeFile)
        {
            string rel = RelativeThemePath(themeFile);
            return rel == null ? Url : $"{Url}?theme={Uri.EscapeDataString(rel)}";
        }

        /// <summary>Called by the window whenever it loads a theme.</summary>
        public void SetMainTheme(string themeFile)
        {
            mainThemeFile = themeFile;
            var main = GetOrCreate("main", DefaultFps, () => LoadUi(themeFile, controllerData), out bool created);
            if (!created) main.SetUi(LoadUi(themeFile, controllerData));
            // every "follows the window" channel, whatever its frame rate
            foreach (var ch in Snapshot().Where(c => c.Key.StartsWith("main@")))
                TryReload(ch, themeFile);
        }

        /// <summary>Called when the window's controller changes; trail/peak state is per UI so rebuild bindings.</summary>
        public void ControllerChanged()
        {
            // UI objects resolve Flee variable types per controller; reload so expressions bind to the new controls.
            foreach (var ch in Snapshot())
                TryReload(ch, ch.Key == "main" ? mainThemeFile : ThemeFileFromKey(ch.Key));
        }

        private void TryReload(OverlayChannel ch, string file)
        {
            if (file == null) return;
            try { ch.SetUi(LoadUi(file, controllerData)); }
            catch (Exception ex) { System.Diagnostics.Debug.WriteLine($"Overlay: could not load {file}: {ex.Message}"); }
        }

        private List<OverlayChannel> Snapshot()
        {
            lock (channels) return channels.Values.ToList();
        }

        public string StatsText()
        {
            var sb = new StringBuilder();
            lock (channels)
                foreach (var ch in channels.Values)
                    sb.AppendLine($"{ch.Key}: {ch.ClientCount} client(s), {ch.Fps} fps target, render {ch.AvgRenderMs:0.0} ms, png {ch.AvgEncodeMs:0.0} ms, sent {ch.FramesSent}, unchanged {ch.FramesSkipped}");
            return sb.ToString();
        }

        private OverlayChannel ChannelForQuery(string query)
        {
            var q = ParseQuery(query);
            int fps = DefaultFps;
            if (q.TryGetValue("fps", out string f) && int.TryParse(f, out int fv)) fps = ClampFps(fv);

            if (!q.TryGetValue("theme", out string theme) || string.IsNullOrWhiteSpace(theme))
            {
                if (fps == DefaultFps) return GetOrCreate("main", fps, null, out _);
                // the window's theme at a different rate
                string main = mainThemeFile;
                return GetOrCreate($"main@{fps}", fps, main == null ? (Func<UI>)null : () => LoadUi(main, controllerData), out _);
            }

            string file = ResolveThemeFile(theme);
            if (file == null) return null;
            return GetOrCreate($"theme:{RelativeThemePath(file)}@{fps}", fps, () => LoadUi(file, controllerData), out _);
        }

        /// <summary>Only a few frame rates, so URLs can't create unbounded channels (each has a render thread).</summary>
        private static int ClampFps(int fps)
        {
            int[] allowed = { 10, 15, 20, 24, 30, 48, 50, 60, 75, 90, 120 };
            return allowed.OrderBy(a => Math.Abs(a - fps)).First();
        }

        private const int MaxChannels = 12;

        /// <summary>
        /// Get a channel, creating it if needed. The UI is built before the channel is published, so a broken theme
        /// never leaves an empty channel behind. Idle channels are disposed when the limit is reached.
        /// </summary>
        private OverlayChannel GetOrCreate(string key, int fps, Func<UI> createUi, out bool created)
        {
            lock (channels)
                if (channels.TryGetValue(key, out var existing)) { created = false; return existing; }

            UI ui = createUi?.Invoke(); // may throw (bad theme): nothing has been registered yet
            lock (channels)
            {
                if (channels.TryGetValue(key, out var raced)) { ui?.Dispose(); created = false; return raced; }
                if (channels.Count >= MaxChannels)
                {
                    foreach (var idle in channels.Values.Where(c => c.Key != "main" && c.ClientCount == 0).ToList())
                    {
                        channels.Remove(idle.Key);
                        idle.Dispose();
                    }
                    if (channels.Count >= MaxChannels) { ui?.Dispose(); throw new InvalidOperationException("Too many overlay channels"); }
                }
                var ch = new OverlayChannel(key, ClampFps(fps), true);
                if (ui != null) ch.SetUi(ui);
                channels[key] = ch;
                created = true;
                return ch;
            }
        }

        private string ThemeFileFromKey(string key)
        {
            if (key.StartsWith("main@")) return mainThemeFile;
            if (!key.StartsWith("theme:")) return null;
            string rel = key.Substring(6);
            int at = rel.LastIndexOf('@');
            if (at >= 0) rel = rel.Substring(0, at);
            return ResolveThemeFile(rel);
        }

        /// <summary>Resolve a URL theme path to a .json file inside the themes folder (no traversal outside it).</summary>
        private string ResolveThemeFile(string rel)
        {
            rel = rel.Replace('/', Path.DirectorySeparatorChar).TrimStart(Path.DirectorySeparatorChar);
            if (!rel.EndsWith(".json", StringComparison.OrdinalIgnoreCase)) return null;
            string full = Path.GetFullPath(Path.Combine(themesRoot, rel));
            if (!full.StartsWith(themesRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) return null;
            if (Path.GetFileName(full).Equals("theme.json", StringComparison.OrdinalIgnoreCase)) return null;
            return File.Exists(full) ? full : null;
        }

        private string RelativeThemePath(string themeFile)
        {
            if (themeFile == null) return null;
            string full = Path.GetFullPath(themeFile);
            if (!full.StartsWith(themesRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) return null;
            return full.Substring(themesRoot.Length + 1).Replace(Path.DirectorySeparatorChar, '/');
        }

        /// <summary>Same pipeline the window uses: ThemeFixer upgrade, then a fresh UI instance.</summary>
        public static UI LoadUi(string themeFile, ControllerData data)
        {
            string json = File.ReadAllText(themeFile);
            ThemeFixer.UI fixer = JsonConvert.DeserializeObject<ThemeFixer.UI>(json);
            fixer.Update();
            json = JsonConvert.SerializeObject(fixer, Formatting.Indented);
            // Relative theme dir, exactly like the window, so "\"-prefixed image paths resolve the same way.
            string dir = Path.GetDirectoryName(themeFile);
            string cwd = Path.GetFullPath(".") + Path.DirectorySeparatorChar;
            if (dir.StartsWith(cwd, StringComparison.OrdinalIgnoreCase)) dir = dir.Substring(cwd.Length);
            var ui = new UI(data, dir, json);
            ui.InitalizeController();
            return ui;
        }

        private static Dictionary<string, string> ParseQuery(string query)
        {
            var d = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (string part in (query ?? "").Split('&'))
            {
                if (part.Length == 0) continue;
                int eq = part.IndexOf('=');
                string k = Uri.UnescapeDataString((eq < 0 ? part : part.Substring(0, eq)).Replace('+', ' '));
                string v = eq < 0 ? "" : Uri.UnescapeDataString(part.Substring(eq + 1).Replace('+', ' '));
                d[k] = v;
            }
            return d;
        }

        public void Dispose()
        {
            server?.Dispose();
            lock (channels)
            {
                foreach (var ch in channels.Values) ch.Dispose();
                channels.Clear();
            }
        }
    }
}
