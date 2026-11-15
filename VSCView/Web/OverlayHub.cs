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

        public int DefaultFps { get; set; } = 60;
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
            server = new OverlayServer(port, Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "wwwroot"), ChannelForQuery);
            return server.Start();
        }

        public string Url => $"http://127.0.0.1:{Port}/";

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
            OverlayChannel ch = GetOrCreate("main", DefaultFps);
            ch.SetUi(LoadUi(themeFile, controllerData));
        }

        /// <summary>Called when the window's controller changes; trail/peak state is per UI so rebuild bindings.</summary>
        public void ControllerChanged()
        {
            // UI objects resolve Flee variable types per controller; reload so expressions bind to the new controls.
            lock (channels)
                foreach (var kv in channels)
                {
                    string file = kv.Key == "main" ? mainThemeFile : ThemeFileFromKey(kv.Key);
                    if (file != null) kv.Value.SetUi(LoadUi(file, controllerData));
                }
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
            if (q.TryGetValue("fps", out string f) && int.TryParse(f, out int fv)) fps = fv;

            if (!q.TryGetValue("theme", out string theme) || string.IsNullOrWhiteSpace(theme))
            {
                if (fps == DefaultFps) return GetOrCreate("main", fps);
                // main theme at a different rate
                string key = $"main@{fps}";
                bool created;
                OverlayChannel c = GetOrCreate(key, fps, out created);
                if (created && mainThemeFile != null) c.SetUi(LoadUi(mainThemeFile, controllerData));
                return c;
            }

            string file = ResolveThemeFile(theme);
            if (file == null) return null;
            {
                string key = $"theme:{RelativeThemePath(file)}@{fps}";
                OverlayChannel c = GetOrCreate(key, fps, out bool created);
                if (created) c.SetUi(LoadUi(file, controllerData));
                return c;
            }
        }

        private OverlayChannel GetOrCreate(string key, int fps) => GetOrCreate(key, fps, out _);

        private OverlayChannel GetOrCreate(string key, int fps, out bool created)
        {
            lock (channels)
            {
                if (channels.TryGetValue(key, out var ch)) { created = false; return ch; }
                ch = new OverlayChannel(key, fps, true);
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
