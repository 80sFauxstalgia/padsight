using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Windows.Forms;
using VSCView.Obs;
using VSCView.Web;

namespace VSCView
{
    /// <summary>
    /// The OBS link (obs-websocket): add a correctly sized source, a theme per scene, hide on chosen scenes,
    /// show only while live or recording, and fix sources that point at an old port. Plus two global hotkeys
    /// (hide/show the overlay, next controller) that also work from a Stream Deck.
    /// </summary>
    public partial class MainForm
    {
        private ObsClient obs;
        private bool manualHidden;
        private bool sceneThemeActive;
        private string themeBeforeSceneRule;

        /// <summary>Overlay ports PadSight uses (default plus one per extra instance), to recognise its own sources.</summary>
        private static bool IsPadSightPort(int port) => port >= DefaultOverlayPort && port < DefaultOverlayPort + 100;

        private void InitObs()
        {
            obs = new ObsClient();
            obs.StatusChanged += () => PostToUi(UpdateOverlayVisibility);
            obs.ProgramSceneChanged += scene => PostToUi(() => OnProgramScene(scene));
            obs.OutputsChanged += (s, r) => PostToUi(UpdateOverlayVisibility);
            if (settings.ObsEnabled == true) StartObs();
        }

        private void StartObs()
        {
            obs.Start(settings.ObsHost, settings.ObsPort ?? 4455, ObsPassword.Unprotect(settings.ObsPasswordProtected));
        }

        private void StopObs()
        {
            obs?.Stop();
            sceneThemeActive = false;
            UpdateOverlayVisibility();
        }

        /// <summary>UI thread. Combines the hide hotkey and the OBS rules into one visible/hidden state.</summary>
        private void UpdateOverlayVisibility()
        {
            if (overlayHub == null) return;
            overlayHub.Visible = HiddenReason() == null;
        }

        private string HiddenReason()
        {
            if (manualHidden) return "Hidden with the hotkey or the panel";
            if (obs?.Status != ObsClient.ObsStatus.Connected) return null; // rules need OBS; never hide blindly
            if (settings.ObsHideScenes != null && obs.ProgramScene != null && settings.ObsHideScenes.Contains(obs.ProgramScene))
                return $"Hidden on the scene \"{obs.ProgramScene}\"";
            if (settings.ObsOnlyWhenLive == true && !obs.Streaming && !obs.Recording)
                return "Hidden until you go live or record";
            return null;
        }

        private void OnProgramScene(string scene)
        {
            string key = null;
            if (scene != null) settings.ObsSceneThemes?.TryGetValue(scene, out key);
            string file = key == null ? null : overlayHub.ThemeFile(key);
            if (file != null)
            {
                if (!sceneThemeActive) themeBeforeSceneRule = currentThemeFile;
                sceneThemeActive = true;
                if (!SameFile(file, currentThemeFile)) LoadThemeQuiet(file);
            }
            else if (sceneThemeActive)
            {
                sceneThemeActive = false;
                if (themeBeforeSceneRule != null && File.Exists(themeBeforeSceneRule)) LoadThemeQuiet(themeBeforeSceneRule);
                ApplyRememberedTheme();
            }
            UpdateOverlayVisibility();
        }

        private static bool SameFile(string a, string b) =>
            a != null && b != null && Path.GetFullPath(a).Equals(Path.GetFullPath(b), StringComparison.OrdinalIgnoreCase);

        /// <summary>Load a theme for a scene rule without remembering it as the user's pick.</summary>
        private async void LoadThemeQuiet(string file)
        {
            try { await LoadTheme(file, true); }
            catch (Exception ex) { Debug.WriteLine("Scene theme: " + ex.Message); }
        }

        #region OBS API
        private object ObsState()
        {
            return new
            {
                enabled = settings.ObsEnabled == true,
                status = obs?.Status.ToString() ?? "Off",
                error = obs?.Error,
                host = settings.ObsHost ?? "127.0.0.1",
                port = settings.ObsPort ?? 4455,
                hasPassword = !string.IsNullOrEmpty(settings.ObsPasswordProtected),
                version = obs?.ObsVersion,
                scene = obs?.ProgramScene,
                streaming = obs?.Streaming ?? false,
                streamsVersion = obs?.StreamsVersion ?? 0,
                recording = obs?.Recording ?? false,
                visible = overlayHub?.Visible ?? true,
                hiddenReason = HiddenReason(),
                manualHidden,
                rules = new
                {
                    sceneThemes = settings.ObsSceneThemes ?? new Dictionary<string, string>(),
                    hideScenes = settings.ObsHideScenes ?? new List<string>(),
                    onlyWhenLive = settings.ObsOnlyWhenLive == true,
                },
                hotkeys = new { toggle = settings.HotkeyToggle, next = settings.HotkeyNext, errors = hotkeyErrors },
            };
        }

        /// <summary>POST /api/obs/connect {enabled, host, port, password?}. The password is never sent back.</summary>
        private ApiResponse ApiObsConnect(JObject b)
        {
            string oldHost = settings.ObsHost ?? "127.0.0.1";
            int oldPort = settings.ObsPort ?? 4455;
            int? newPort = b["port"] != null ? (int?)b["port"] : null;
            if (b["host"] != null)
            {
                if (!NormalizeObsAddress((string)b["host"], out string host, out int? pastedPort, out string error))
                    return ApiResponse.Error(400, error);
                settings.ObsHost = host == "127.0.0.1" ? null : host;
                if (pastedPort != null) newPort = pastedPort; // "ws://192.168.1.5:4455" carries its own port
            }
            if (newPort != null)
            {
                if (newPort < 1 || newPort > 65535) return ApiResponse.Error(400, "The port must be between 1 and 65535 (OBS uses 4455 unless you changed it).");
                settings.ObsPort = newPort;
            }
            // A saved password belongs to the OBS it was entered for. Never answer another host's challenge with
            // it (a hostile server could brute-force the hash offline): a new address needs the password again.
            bool moved = !string.Equals(settings.ObsHost ?? "127.0.0.1", oldHost, StringComparison.OrdinalIgnoreCase) || (settings.ObsPort ?? 4455) != oldPort;
            if (moved && b["password"] == null) settings.ObsPasswordProtected = null;
            if (b["password"] != null) settings.ObsPasswordProtected = ObsPassword.Protect((string)b["password"]);
            if (b["forgetPassword"] != null && (bool)b["forgetPassword"]) settings.ObsPasswordProtected = null;
            if (b["enabled"] != null) settings.ObsEnabled = (bool)b["enabled"];
            SaveSettings();
            if (settings.ObsEnabled == true) StartObs(); else StopObs();
            return ApiResponse.Ok(JsonConvert.SerializeObject(new { obs = ObsState() }));
        }

        /// <summary>
        /// Accepts what people paste from OBS's "Show Connect Info": a bare host or IP, "host:port", or a full
        /// "ws://host:port/" server URL. Returns the host alone, plus the port when one was included.
        /// </summary>
        internal static bool NormalizeObsAddress(string input, out string host, out int? port, out string error)
        {
            host = "127.0.0.1"; port = null; error = null;
            string s = (input ?? "").Trim();
            if (s.Length == 0) return true; // empty = this PC
            if (!s.Contains("://")) s = "ws://" + s;
            if (!Uri.TryCreate(s, UriKind.Absolute, out Uri u) || !(u.Scheme == "ws" || u.Scheme == "wss" || u.Scheme == "http" || u.Scheme == "https")
                || string.IsNullOrEmpty(u.Host) || !string.IsNullOrEmpty(u.UserInfo) || (u.AbsolutePath != "/" && u.AbsolutePath != ""))
            {
                error = "That doesn't look like an address. Use 127.0.0.1 when OBS runs on this PC, or the other PC's IP address, e.g. 192.168.1.20.";
                return false;
            }
            host = u.Host.Trim('[', ']');
            if (!u.IsDefaultPort) port = u.Port;
            return true;
        }

        /// <summary>POST /api/obs/rules {sceneThemes?, hideScenes?, onlyWhenLive?}.</summary>
        private ApiResponse ApiObsRules(JObject b)
        {
            if (b["sceneThemes"] is JObject st)
            {
                var map = new Dictionary<string, string>();
                foreach (var p in st.Properties())
                {
                    string key = (string)p.Value;
                    if (!string.IsNullOrEmpty(key) && overlayHub.ThemeFile(key) == null) return ApiResponse.Error(400, "Unknown theme " + key);
                    if (!string.IsNullOrEmpty(key)) map[p.Name] = key;
                }
                settings.ObsSceneThemes = map;
            }
            if (b["hideScenes"] is JArray hs) settings.ObsHideScenes = hs.Select(x => (string)x).Where(x => !string.IsNullOrEmpty(x)).Distinct().ToList();
            if (b["onlyWhenLive"] != null) settings.ObsOnlyWhenLive = (bool)b["onlyWhenLive"];
            SaveSettings();
            if (obs?.Status == ObsClient.ObsStatus.Connected) OnProgramScene(obs.ProgramScene);
            UpdateOverlayVisibility();
            return ApiResponse.Ok(JsonConvert.SerializeObject(new { obs = ObsState() }));
        }

        /// <summary>GET /api/obs/scenes: scene names plus every PadSight Browser Source in OBS (server thread).</summary>
        private ApiResponse ApiObsScenes()
        {
            var scenes = obs.Request("GetSceneList");
            var names = ((JArray)scenes["scenes"] ?? new JArray())
                .OrderByDescending(s => (int?)s["sceneIndex"] ?? 0) // OBS lists bottom-up; show them in the UI's order
                .Select(s => (string)s["sceneName"]).ToList();

            var sources = new List<object>();
            var inputs = obs.Request("GetInputList", new JObject { ["inputKind"] = "browser_source" });
            foreach (JObject input in (JArray)inputs["inputs"] ?? new JArray())
            {
                string name = (string)input["inputName"];
                JObject set;
                try { set = obs.Request("GetInputSettings", new JObject { ["inputName"] = name })["inputSettings"] as JObject; }
                catch { continue; }
                string url = (string)set?["url"];
                if (!IsPadSightUrl(url, out int port)) continue;
                sources.Add(new
                {
                    name, url,
                    width = (int?)set["width"], height = (int?)set["height"],
                    portOk = port == overlayHub.Port,
                });
            }
            return ApiResponse.Ok(JsonConvert.SerializeObject(new { scenes = names, current = obs.ProgramScene, sources }));
        }

        /// <summary>A PadSight overlay URL: loopback, a PadSight port, and the overlay page itself.</summary>
        private static bool IsPadSightUrl(string url, out int port)
        {
            port = 0;
            if (!Uri.TryCreate(url ?? "", UriKind.Absolute, out Uri u) || u.Scheme != Uri.UriSchemeHttp || !string.IsNullOrEmpty(u.UserInfo)) return false;
            if (!(u.Host == "127.0.0.1" || u.Host.Equals("localhost", StringComparison.OrdinalIgnoreCase))) return false;
            if (!(u.AbsolutePath == "/" || u.AbsolutePath == "/overlay.html")) return false;
            port = u.Port;
            return IsPadSightPort(port);
        }

        private static readonly Regex SourceNameRx = new Regex(@"^[\p{L}\p{N} _\-\.\(\)]{1,64}$");

        /// <summary>
        /// POST /api/obs/add-source {scene, name, url, width, height}. Only ever creates a Browser Source that points
        /// at this PadSight's own overlay, so the API can't be used to put arbitrary web pages into OBS.
        /// </summary>
        private ApiResponse ApiObsAddSource(JObject b)
        {
            string scene = (string)b["scene"], name = ((string)b["name"] ?? "PadSight").Trim(), url = (string)b["url"];
            int width = (int?)b["width"] ?? 0, height = (int?)b["height"] ?? 0;
            if (string.IsNullOrEmpty(scene)) return ApiResponse.Error(400, "Choose a scene");
            if (!SourceNameRx.IsMatch(name)) return ApiResponse.Error(400, "Use letters, numbers, spaces and - _ . ( ) in the source name");
            if (!IsPadSightUrl(url, out int port) || port != overlayHub.Port) return ApiResponse.Error(400, "Only PadSight's own overlay URL can be added");
            if (width < 16 || height < 16 || width > 8192 || height > 8192) return ApiResponse.Error(400, "Width and height must be between 16 and 8192");
            int fps = Math.Max(10, Math.Min(120, settings.OverlayFps ?? 60));
            var data = new JObject
            {
                ["sceneName"] = scene,
                ["inputName"] = name,
                ["inputKind"] = "browser_source",
                ["inputSettings"] = new JObject
                {
                    ["url"] = url, ["width"] = width, ["height"] = height,
                    ["fps_custom"] = true, ["fps"] = fps,
                    ["shutdown"] = true,       // "Shutdown source when not visible": no rendering off screen
                    ["reroute_audio"] = false,
                },
                ["sceneItemEnabled"] = true,
            };
            try { obs.Request("CreateInput", data); }
            catch (ObsRequestException ex) when (ex.Code == 601) // ResourceAlreadyExists
            { return ApiResponse.Error(409, $"OBS already has a source called \"{name}\". Pick another name."); }
            return ApiResponse.Ok(JsonConvert.SerializeObject(new { added = name, scene }));
        }

        /// <summary>POST /api/obs/fix-port {name}: point one PadSight source at this instance's current port.</summary>
        private ApiResponse ApiObsFixPort(JObject b)
        {
            string name = (string)b["name"];
            JObject set = obs.Request("GetInputSettings", new JObject { ["inputName"] = name })["inputSettings"] as JObject;
            string url = (string)set?["url"];
            if (!IsPadSightUrl(url, out _)) return ApiResponse.Error(400, "That source isn't a PadSight overlay");
            var ub = new UriBuilder(url) { Host = "127.0.0.1", Port = overlayHub.Port };
            obs.Request("SetInputSettings", new JObject { ["inputName"] = name, ["inputSettings"] = new JObject { ["url"] = ub.Uri.AbsoluteUri } });
            return ApiResponse.Ok(JsonConvert.SerializeObject(new { fixedSource = name, url = ub.Uri.AbsoluteUri }));
        }

        #region Stream control
        private static readonly Regex StreamKeyRx = new Regex(@"^(main|mrtmp:[A-Za-z0-9_\-]{1,64}|aitum:[^\x00-\x1F\x7F-\x9F\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]{1,128})\z");
        private static readonly Regex ComboNameRx = new Regex(@"^[\p{L}\p{N} _\-]{1,32}\z");
        private static readonly Regex StreamTypeRx = new Regex(@"^[\p{L}\p{N} _\-\.]{1,24}\z");
        // One start or stop at a time: a Stop sent while a Start waits for OBS must see the real state afterwards,
        // not "everything off" followed by the Start bringing everything live.
        private static readonly System.Threading.SemaphoreSlim streamOpLock = new System.Threading.SemaphoreSlim(1, 1);

        private object StreamPrefsView() => new
        {
            prefs = settings.StreamPrefs ?? new Dictionary<string, StreamPref>(),
            combos = settings.StreamCombos ?? new Dictionary<string, List<string>>(),
        };

        /// <summary>GET /api/obs/streams: every stream PadSight can start or stop, plus the saved labels, types and combos (server thread).</summary>
        private ApiResponse ApiObsStreams()
        {
            if (obs?.Status != ObsClient.ObsStatus.Connected) return ApiResponse.Error(409, "Link PadSight to OBS first");
            StreamDiscovery d = StreamTargets.Discover(obs);
            return ApiResponse.Ok(JsonConvert.SerializeObject(new
            {
                targets = d.Targets.Select(t => new { key = t.Key, kind = t.Kind, name = t.Name, active = t.Active, note = t.Note }),
                multiRtmp = d.MultiRtmp, multiRtmpActive = d.MultiRtmpActive, aitum = d.Aitum,
                outputListOk = d.OutputListOk, obsSlow = d.ObsSlow,
                version = obs.StreamsVersion,
                saved = StreamPrefsView(),
            }));
        }

        /// <summary>
        /// POST /api/obs/streams/action {op: "start"|"stop", targets: [keys], confirm: true}. Going live is public and stopping
        /// ends a broadcast, so the call must carry confirm: true (the panel asks the user first). Server thread.
        /// </summary>
        private ApiResponse ApiObsStreamAction(JObject b)
        {
            if (obs?.Status != ObsClient.ObsStatus.Connected) return ApiResponse.Error(409, "Link PadSight to OBS first");
            if (b["confirm"]?.Type != JTokenType.Boolean || !(bool)b["confirm"]) return ApiResponse.Error(400, "Starting or stopping a stream needs confirm: true");
            string op = (string)b["op"];
            if (op != "start" && op != "stop") return ApiResponse.Error(400, "op must be start or stop");
            if (!(b["targets"] is JArray arr) || arr.Count == 0 || arr.Count > 50 || arr.Any(x => x.Type != JTokenType.String))
                return ApiResponse.Error(400, "Choose at least one stream");
            var keys = arr.Select(x => (string)x).Distinct().ToList();
            if (keys.Any(k => !StreamKeyRx.IsMatch(k))) return ApiResponse.Error(400, "Unknown stream key");
            // A Stop waits longer than the worst-case Start (a 45 s deadline for discovery and the plugin starts, plus at
            // most two OBS calls already in flight at about 10 s each: about 65 s), so a confirmed Stop queued behind a
            // slow Start still runs instead of being refused.
            if (!streamOpLock.Wait(op == "stop" ? 90000 : 30000))
                return ApiResponse.Error(409, "Another start or stop is still running. Try again in a moment.");
            var results = new List<StreamResult>();
            try
            {
                // One deadline for the whole operation; a stop's own OBS stream is never skipped (see StreamTargets.Run).
                DateTime deadline = DateTime.UtcNow.AddSeconds(op == "start" ? 45 : 60);
                StreamDiscovery d = StreamTargets.Discover(obs); // fresh, inside the lock: the true state after any earlier action
                var known = new HashSet<string>(d.Targets.Select(t => t.Key));
                var unknown = keys.Where(k => !known.Contains(k)).ToList();
                // A start refuses streams OBS doesn't list. A stop never refuses as a whole: it stops every stream OBS
                // does list (OBS's own stream included) and reports the missing ones as failed, because a plugin that
                // didn't answer this time, or a renamed output, must not keep the rest live.
                if (unknown.Count > 0 && op == "start") return ApiResponse.Error(400, "OBS doesn't have these streams (any more): " + string.Join(", ", unknown));
                results.AddRange(StreamTargets.Run(obs, d, op == "start", keys.Where(known.Contains).ToList(), deadline));
                results.AddRange(unknown.Select(k => new StreamResult
                {
                    Key = k, Ok = false,
                    Message = d.ObsSlow
                        ? "Not stopped: OBS is slow to answer, so this stream couldn't be checked. Check it in OBS."
                        : "OBS doesn't list this stream right now, so it wasn't stopped. Check it in OBS.",
                }));
            }
            finally { streamOpLock.Release(); }
            Debug.WriteLine($"Stream {op}: " + string.Join("; ", results.Select(r => $"{r.Key} {(r.Ok ? "ok" : "failed")} {r.Message}")));
            return ApiResponse.Ok(JsonConvert.SerializeObject(new
            {
                op,
                results = results.Select(r => new { key = r.Key, ok = r.Ok, message = r.Message, notice = r.Notice }),
            }));
        }

        /// <summary>POST /api/obs/streams/prefs {targets?: {key: {label, type}}, combos?: {name: [keys]}}. Replaces what it's given.</summary>
        private ApiResponse ApiObsStreamPrefs(JObject b)
        {
            // Validate everything first; nothing is saved unless the whole request is valid.
            Dictionary<string, StreamPref> map = null;
            Dictionary<string, List<string>> combos = null;
            if (b["targets"] is JObject tp)
            {
                map = new Dictionary<string, StreamPref>();
                if (tp.Count > 100) return ApiResponse.Error(400, "Too many streams");
                foreach (var p in tp.Properties())
                {
                    if (!StreamKeyRx.IsMatch(p.Name)) return ApiResponse.Error(400, "Unknown stream key");
                    string label = ((string)p.Value?["label"] ?? "").Trim(), type = ((string)p.Value?["type"] ?? "").Trim();
                    if (label.Length > 40 || !StreamTargets.IsPlainText(label)) return ApiResponse.Error(400, "Keep stream names to 40 plain characters");
                    if (type.Length > 0 && !StreamTypeRx.IsMatch(type)) return ApiResponse.Error(400, "Use a short word for the type, e.g. Twitch");
                    if (label.Length > 0 || type.Length > 0) map[p.Name] = new StreamPref { Label = label.Length > 0 ? label : null, Type = type.Length > 0 ? type : null };
                }
            }
            if (b["combos"] is JObject cp)
            {
                if (cp.Count > 12) return ApiResponse.Error(400, "Up to 12 saved combinations");
                combos = new Dictionary<string, List<string>>();
                foreach (var p in cp.Properties())
                {
                    string name = p.Name.Trim();
                    if (!ComboNameRx.IsMatch(name)) return ApiResponse.Error(400, "Name combinations with letters, numbers, spaces, - and _ (up to 32)");
                    if (!(p.Value is JArray keys) || keys.Count == 0 || keys.Count > 50 || keys.Any(k => k.Type != JTokenType.String || !StreamKeyRx.IsMatch((string)k)))
                        return ApiResponse.Error(400, $"\"{name}\" needs at least one stream");
                    combos[name] = keys.Select(k => (string)k).Distinct().ToList();
                }
            }
            if (map != null) settings.StreamPrefs = map;
            if (combos != null) settings.StreamCombos = combos;
            SaveSettings();
            return ApiResponse.Ok(JsonConvert.SerializeObject(new { saved = StreamPrefsView() }));
        }
        #endregion

        private ApiResponse ApiVisibility(JObject b)
        {
            if (b["hidden"] != null) manualHidden = (bool)b["hidden"];
            UpdateOverlayVisibility();
            return ApiResponse.Ok(JsonConvert.SerializeObject(new { obs = ObsState() }));
        }
        #endregion

        #region Global hotkeys
        // RegisterHotKey works system-wide (in games too) and from Stream Deck "hotkey" buttons.
        [DllImport("user32.dll", SetLastError = true)] private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint mods, uint vk);
        [DllImport("user32.dll")] private static extern bool UnregisterHotKey(IntPtr hWnd, int id);
        private const int WM_HOTKEY = 0x0312, HK_TOGGLE = 0x5001, HK_NEXT = 0x5002;
        private const uint MOD_ALT = 1, MOD_CONTROL = 2, MOD_SHIFT = 4, MOD_WIN = 8, MOD_NOREPEAT = 0x4000;
        private Dictionary<string, string> hotkeyErrors = new Dictionary<string, string>();

        private void RegisterHotkeys()
        {
            if (!IsHandleCreated) return;
            UnregisterHotKey(Handle, HK_TOGGLE);
            UnregisterHotKey(Handle, HK_NEXT);
            hotkeyErrors = new Dictionary<string, string>();
            TryRegister(HK_TOGGLE, "toggle", settings.HotkeyToggle);
            TryRegister(HK_NEXT, "next", settings.HotkeyNext);
        }

        private void TryRegister(int id, string which, string combo)
        {
            if (string.IsNullOrWhiteSpace(combo)) return;
            if (!ParseHotkey(combo, out uint mods, out uint vk)) { hotkeyErrors[which] = "Not a valid key combination"; return; }
            if (!RegisterHotKey(Handle, id, mods | MOD_NOREPEAT, vk)) hotkeyErrors[which] = "Another program already uses this combination";
        }

        /// <summary>"Ctrl+Alt+F9" -> modifiers + virtual key. At least one modifier unless it's F13-F24.</summary>
        internal static bool ParseHotkey(string combo, out uint mods, out uint vk)
        {
            mods = 0; vk = 0;
            foreach (string raw in combo.Split('+'))
            {
                string part = raw.Trim();
                switch (part.ToLowerInvariant())
                {
                    case "ctrl": case "control": mods |= MOD_CONTROL; continue;
                    case "alt": mods |= MOD_ALT; continue;
                    case "shift": mods |= MOD_SHIFT; continue;
                    case "win": mods |= MOD_WIN; continue;
                }
                if (vk != 0 || !Enum.TryParse(part, true, out Keys key)) return false;
                if (part.Length == 1 && char.IsDigit(part[0])) key = Keys.D0 + (part[0] - '0');
                vk = (uint)key;
            }
            bool bigF = vk >= (uint)Keys.F13 && vk <= (uint)Keys.F24;
            return vk != 0 && (mods != 0 || bigF);
        }

        private ApiResponse ApiHotkeys(JObject b)
        {
            foreach (var (field, apply) in new (string, Action<string>)[] { ("toggle", v => settings.HotkeyToggle = v), ("next", v => settings.HotkeyNext = v) })
            {
                if (b[field] == null) continue;
                string v = ((string)b[field] ?? "").Trim();
                if (v.Length > 0 && !ParseHotkey(v, out _, out _)) return ApiResponse.Error(400, $"\"{v}\" isn't a usable combination. Use a modifier, e.g. Ctrl+Alt+F9.");
                apply(v.Length == 0 ? null : v);
            }
            SaveSettings();
            RegisterHotkeys();
            return ApiResponse.Ok(JsonConvert.SerializeObject(new { obs = ObsState() }));
        }

        private bool HandleHotkeyMessage(ref Message m)
        {
            if (m.Msg != WM_HOTKEY) return false;
            int id = m.WParam.ToInt32();
            if (id == HK_TOGGLE) { manualHidden = !manualHidden; UpdateOverlayVisibility(); }
            else if (id == HK_NEXT) NextController();
            return true;
        }

        /// <summary>Put the next connected controller on the overlay (Steam's virtual pads skipped when a real one is there).</summary>
        private void NextController()
        {
            var present = ControllerMemoHack.Values.Select(v => v.Item1).Where(c => c.IsPresent).ToList();
            if (present.Any(c => !(c is ExtendInput.Controller.XInputController)))
                present = present.Where(c => !(c is ExtendInput.Controller.XInputController)).ToList();
            if (present.Count == 0) return;
            int i = present.IndexOf(ActiveController);
            var next = present[(i + 1) % present.Count];
            if (next != ActiveController) LoadController(next, EventArgs.Empty);
        }
        #endregion
    }
}
