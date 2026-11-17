using Newtonsoft.Json.Linq;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;

namespace VSCView.Obs
{
    /// <summary>One stream PadSight can start or stop: OBS's own stream, or a multistream plugin's target.</summary>
    public sealed class StreamTarget
    {
        public string Key { get; set; }    // "main", "mrtmp:<id>", "aitum:<name>"
        public string Kind { get; set; }   // "main", "mrtmp", "aitum"
        public string Name { get; set; }   // what the plugin calls it (an id for obs-multi-rtmp)
        public bool? Active { get; set; }  // null = the plugin can't report this target's state
        public string Note { get; set; }
    }

    public sealed class StreamDiscovery
    {
        public List<StreamTarget> Targets { get; } = new List<StreamTarget>();
        public bool MultiRtmp { get; set; }        // obs-multi-rtmp hotkeys found
        public int MultiRtmpActive { get; set; }   // obs-multi-rtmp outputs running right now (not per target)
        public bool Aitum { get; set; }            // Aitum Multistream answered
    }

    public sealed class StreamResult
    {
        public string Key { get; set; }
        public bool Ok { get; set; }
        public bool Notice { get; set; }  // ok, but worth keeping on the status line (e.g. "already off" from a refusal)
        public string Message { get; set; }
    }

    /// <summary>
    /// Starts and stops streams through obs-websocket, the way each owner expects:
    ///   * OBS's own stream: StartStream / StopStream.
    ///   * obs-multi-rtmp: its own frontend hotkeys via TriggerHotkeyByName ("obs-multi-rtmp.start.&lt;id&gt;"). Its
    ///     outputs all share the name "multi-output" and need the plugin's own encoder/service setup, so StartOutput
    ///     on them would be ambiguous and unsafe. It reports no per-target state.
    ///   * Aitum Multistream: its vendor requests (get_outputs, start_output, stop_output).
    /// Runs on the server thread (it waits on OBS).
    /// </summary>
    public static class StreamTargets
    {
        public const string MultiRtmpStart = "obs-multi-rtmp.start.";
        public const string MultiRtmpStop = "obs-multi-rtmp.stop.";
        public const string MultiRtmpOutputName = "multi-output";
        public const string AitumVendor = "aitum-multistream";
        public const string AitumOutputPrefix = "aitum_multi_output_";

        public static StreamDiscovery Discover(ObsClient obs)
        {
            var d = new StreamDiscovery();

            JObject st = obs.Request("GetStreamStatus");
            bool reconnecting = (bool?)st["outputReconnecting"] ?? false;
            d.Targets.Add(new StreamTarget
            {
                Key = "main", Kind = "main", Name = "OBS stream",
                Active = (bool?)st["outputActive"] ?? false,
                Note = reconnecting ? "Reconnecting" : null,
            });

            var activeOutputs = new HashSet<string>(StringComparer.Ordinal);
            try
            {
                foreach (JObject o in (JArray)obs.Request("GetOutputList")["outputs"] ?? new JArray())
                {
                    string name = (string)o["outputName"];
                    if (!((bool?)o["outputActive"] ?? false) || name == null) continue;
                    activeOutputs.Add(name);
                    if (name == MultiRtmpOutputName) d.MultiRtmpActive++;
                }
            }
            catch (Exception ex) { Debug.WriteLine("GetOutputList: " + ex.Message); }

            // obs-multi-rtmp: one start hotkey per target, "obs-multi-rtmp.start.<id>" (start_all has no dot).
            try
            {
                var hotkeys = ((JArray)obs.Request("GetHotkeyList")["hotkeys"] ?? new JArray()).Select(h => (string)h).Where(h => h != null).ToList();
                var ids = hotkeys.Where(h => h.StartsWith(MultiRtmpStart, StringComparison.Ordinal))
                    .Select(h => h.Substring(MultiRtmpStart.Length)).Where(IsSafeId).Distinct().ToList();
                d.MultiRtmp = ids.Count > 0;
                foreach (string id in ids)
                    Add(d, new StreamTarget { Key = "mrtmp:" + id, Kind = "mrtmp", Name = id, Active = null });
            }
            catch (Exception ex) { Debug.WriteLine("GetHotkeyList: " + ex.Message); }

            // Aitum Multistream: answers its vendor request only when installed.
            try
            {
                JObject r = obs.Request("CallVendorRequest", new JObject { ["vendorName"] = AitumVendor, ["requestType"] = "get_outputs" });
                JToken data = r["responseData"];
                JArray outs = data as JArray ?? data?["outputs"] as JArray ?? (data as JObject)?.Properties().Select(p => p.Value).OfType<JArray>().FirstOrDefault();
                d.Aitum = true;
                foreach (JToken o in outs ?? new JArray())
                {
                    string name = o.Type == JTokenType.String ? (string)o : (string)o["name"];
                    if (!IsSafeAitumName(name)) continue;
                    Add(d, new StreamTarget
                    {
                        Key = "aitum:" + name, Kind = "aitum", Name = name,
                        Active = activeOutputs.Contains(AitumOutputPrefix + name),
                        Note = o.Type == JTokenType.Object && ((bool?)o["vertical"] ?? false) ? "Vertical" : null,
                    });
                }
            }
            catch (ObsRequestException) { } // vendor not installed
            catch (Exception ex) { Debug.WriteLine("Aitum get_outputs: " + ex.Message); }

            return d;
        }

        // A plugin can list the same name twice; the first one wins, so a duplicate never breaks every action.
        private static void Add(StreamDiscovery d, StreamTarget t)
        {
            if (!d.Targets.Any(x => x.Key == t.Key)) d.Targets.Add(t);
        }

        // These two match the stream-key pattern the panel API accepts (MainForm.Obs.cs StreamKeyRx), so every target
        // discovered here can also be saved in prefs. obs-multi-rtmp ids are decimal strings: ASCII only, never anything
        // that could change the hotkey name's meaning.
        internal static bool IsSafeId(string id) =>
            !string.IsNullOrEmpty(id) && id.Length <= 64 && id.All(c => (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '_');

        internal static bool IsSafeAitumName(string name) =>
            !string.IsNullOrEmpty(name) && name.Length <= 128 && IsPlainText(name);

        /// <summary>
        /// Text shown to the user as a name: no C0 or C1 control characters, no DEL, and no bidirectional-text controls,
        /// which can make a name read differently from what it is (e.g. in the go-live confirm).
        /// </summary>
        internal static bool IsPlainText(string s) => s.All(c => c >= 0x20 && !(c >= 0x7F && c <= 0x9F) && !IsBidiControl(c));

        internal static bool IsBidiControl(char c) =>
            (c >= '\u202A' && c <= '\u202E') || (c >= '\u2066' && c <= '\u2069') || c == '\u200E' || c == '\u200F' || c == '\u061C';

        public const string SkippedNotLive = "Skipped: OBS's own stream isn't live, so nothing else was started";

        /// <summary>
        /// Start or stop the given targets. Start: OBS's own stream first (plugins that share its encoder need it live);
        /// if it fails or doesn't go live in time, no plugin target is started. Stop: plugin targets first, then OBS's own
        /// stream. The caller holds the stream-operation lock, so a Stop never runs in the middle of a Start.
        /// </summary>
        public static List<StreamResult> Run(ObsClient obs, StreamDiscovery d, bool start, IList<string> keys, int mainWaitMs = 15000)
        {
            var byKey = new Dictionary<string, StreamTarget>();
            foreach (var t in d.Targets) if (!byKey.ContainsKey(t.Key)) byKey[t.Key] = t;
            var chosen = keys.Distinct().Where(byKey.ContainsKey).Select(k => byKey[k]).ToList();
            var results = new List<StreamResult>();
            StreamTarget main = chosen.FirstOrDefault(t => t.Kind == "main");
            var plugins = chosen.Where(t => t.Kind != "main").ToList();

            if (start && main != null)
            {
                StreamResult r = StartMain(obs, main, mainWaitMs);
                results.Add(r);
                if (!r.Ok)
                {
                    results.AddRange(plugins.Select(t => new StreamResult { Key = t.Key, Ok = false, Message = SkippedNotLive }));
                    return results;
                }
            }
            foreach (var t in plugins)
            {
                results.Add(RunPlugin(obs, t, start));
                Thread.Sleep(150); // let each plugin settle; avoids a burst of simultaneous connects
            }
            if (!start && main != null) results.Add(StopMain(obs, main));
            return results;
        }

        private static StreamResult StartMain(ObsClient obs, StreamTarget t, int waitMs)
        {
            if (t.Active == true) return new StreamResult { Key = t.Key, Ok = true, Message = "Already live" };
            try
            {
                obs.Request("StartStream");
                var end = DateTime.UtcNow.AddMilliseconds(waitMs);
                while (DateTime.UtcNow < end)
                {
                    if ((bool?)obs.Request("GetStreamStatus")["outputActive"] == true) return new StreamResult { Key = t.Key, Ok = true, Message = "Live" };
                    Thread.Sleep(300);
                }
                return new StreamResult
                {
                    Key = t.Key, Ok = false,
                    Message = $"OBS hasn't confirmed it's live after {waitMs / 1000} s. It may still go live, so watch OBS; stop it there or here if you don't want it.",
                };
            }
            catch (Exception ex) { return new StreamResult { Key = t.Key, Ok = false, Message = Describe(ex) }; }
        }

        // Always asks OBS, even when the list said "off": the stream may be connecting, and a stop the user confirmed
        // must not be skipped on stale state. OBS answers OutputNotRunning (501) when it really is off.
        private static StreamResult StopMain(ObsClient obs, StreamTarget t)
        {
            try { obs.Request("StopStream"); return new StreamResult { Key = t.Key, Ok = true, Message = "Stopping" }; }
            catch (ObsRequestException ex) when (ex.Code == 501) { return new StreamResult { Key = t.Key, Ok = true, Message = "Already off" }; }
            catch (Exception ex) { return new StreamResult { Key = t.Key, Ok = false, Message = Describe(ex) }; }
        }

        private static StreamResult RunPlugin(ObsClient obs, StreamTarget t, bool start)
        {
            // Start skips what is already live. Stop is always sent: an output that is still connecting reads as off, and a
            // stop the user confirmed must not be skipped on that.
            if (start && t.Active == true) return new StreamResult { Key = t.Key, Ok = true, Message = "Already live" };
            try
            {
                if (t.Kind == "mrtmp")
                {
                    obs.Request("TriggerHotkeyByName", new JObject { ["hotkeyName"] = (start ? MultiRtmpStart : MultiRtmpStop) + t.Name });
                    // The plugin skips targets that are disabled in its dock, and reports nothing back.
                    return new StreamResult
                    {
                        Key = t.Key, Ok = true,
                        Message = start ? "Start sent; obs-multi-rtmp doesn't confirm, check the live count" : "Stop sent; obs-multi-rtmp doesn't confirm, check the live count",
                    };
                }
                if (t.Kind == "aitum")
                {
                    string refusal;
                    try
                    {
                        JObject r = obs.Request("CallVendorRequest", new JObject
                        {
                            ["vendorName"] = AitumVendor,
                            ["requestType"] = start ? "start_output" : "stop_output",
                            ["requestData"] = new JObject { ["name"] = t.Name },
                        });
                        // obs-websocket reports a vendor request as successful whenever the vendor answered; the vendor's
                        // own refusal (if any) is inside responseData, e.g. {"success": false, "error": "..."}.
                        refusal = VendorRefusal(r?["responseData"] as JObject);
                    }
                    catch (ObsRequestException ex) { refusal = ex.Message; }
                    if (refusal == null) return new StreamResult { Key = t.Key, Ok = true, Message = start ? "Starting" : "Stopping" };
                    // Only a stop of an output that OBS's own output list also shows as off, refused with a "not running"
                    // answer, counts as done; it is still shown on the status line, since the answer came from a refusal.
                    if (!start && t.Active == false && SaysNotRunning(refusal))
                        return new StreamResult { Key = t.Key, Ok = true, Notice = true, Message = "Already off (Aitum said it isn't running)" };
                    return new StreamResult { Key = t.Key, Ok = false, Message = "Aitum refused: " + refusal };
                }
                return new StreamResult { Key = t.Key, Ok = false, Message = "Unknown kind of stream" };
            }
            catch (Exception ex) { return new StreamResult { Key = t.Key, Ok = false, Message = Describe(ex) }; }
        }

        /// <summary>The vendor's own failure inside responseData, or null when it reports none.</summary>
        internal static string VendorRefusal(JObject data)
        {
            if (data == null) return null;
            JToken success = data["success"] ?? data["ok"];
            bool hasFlag = success != null && success.Type == JTokenType.Boolean;
            if (hasFlag && (bool)success) return null; // an explicit success wins, whatever message comes with it
            // Without a success flag, only an "error" field counts as a refusal; "message"/"reason" may just describe success.
            JToken reason = hasFlag ? (data["error"] ?? data["message"] ?? data["reason"]) : data["error"];
            if (!hasFlag && reason == null) return null;
            string text = reason != null && reason.Type == JTokenType.String ? (string)reason : null;
            if (string.IsNullOrEmpty(text)) return "no reason given";
            return text.Length > 200 ? text.Substring(0, 200) : text;
        }

        // Narrow on purpose: only an answer that says the output isn't running may turn a refused stop into "Already off".
        // (The exact wording of Aitum's refusal is still to be confirmed against a real OBS.)
        internal static bool SaysNotRunning(string message)
        {
            string m = (message ?? "").ToLowerInvariant();
            return m.Contains("not running") || m.Contains("isn't running") || m.Contains("not active") || m.Contains("not started");
        }

        private static string Describe(Exception ex) => ex.Message;
    }
}
