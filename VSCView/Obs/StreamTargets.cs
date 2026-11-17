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
                    d.Targets.Add(new StreamTarget { Key = "mrtmp:" + id, Kind = "mrtmp", Name = id, Active = null });
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
                    if (string.IsNullOrEmpty(name) || name.Length > 128) continue;
                    d.Targets.Add(new StreamTarget
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

        // obs-multi-rtmp ids are decimal strings; accept a little more, never anything that could change the hotkey name's meaning.
        private static bool IsSafeId(string id) => id.Length > 0 && id.Length <= 64 && id.All(c => char.IsLetterOrDigit(c) || c == '-' || c == '_');

        /// <summary>
        /// Start or stop the given targets. Start: OBS's own stream first (plugins that share its encoder need it live),
        /// then each plugin target. Stop: plugin targets first, then OBS's own stream.
        /// </summary>
        public static List<StreamResult> Run(ObsClient obs, StreamDiscovery d, bool start, IList<string> keys, int mainWaitMs = 15000)
        {
            var byKey = d.Targets.ToDictionary(t => t.Key);
            var chosen = keys.Distinct().Select(k => byKey[k]).ToList();
            var results = new List<StreamResult>();
            StreamTarget main = chosen.FirstOrDefault(t => t.Kind == "main");
            var plugins = chosen.Where(t => t.Kind != "main").ToList();

            if (start && main != null) results.Add(StartMain(obs, main, mainWaitMs));
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
                return new StreamResult { Key = t.Key, Ok = false, Message = "OBS hasn't gone live yet. Check OBS for an error." };
            }
            catch (Exception ex) { return new StreamResult { Key = t.Key, Ok = false, Message = Describe(ex) }; }
        }

        private static StreamResult StopMain(ObsClient obs, StreamTarget t)
        {
            if (t.Active == false) return new StreamResult { Key = t.Key, Ok = true, Message = "Already off" };
            try { obs.Request("StopStream"); return new StreamResult { Key = t.Key, Ok = true, Message = "Stopping" }; }
            catch (Exception ex) { return new StreamResult { Key = t.Key, Ok = false, Message = Describe(ex) }; }
        }

        private static StreamResult RunPlugin(ObsClient obs, StreamTarget t, bool start)
        {
            if (t.Active == start) return new StreamResult { Key = t.Key, Ok = true, Message = start ? "Already live" : "Already off" };
            try
            {
                if (t.Kind == "mrtmp")
                {
                    obs.Request("TriggerHotkeyByName", new JObject { ["hotkeyName"] = (start ? MultiRtmpStart : MultiRtmpStop) + t.Name });
                    // The plugin skips targets that are disabled in its dock, and reports nothing back.
                    return new StreamResult { Key = t.Key, Ok = true, Message = start ? "Start sent (obs-multi-rtmp doesn't confirm)" : "Stop sent" };
                }
                if (t.Kind == "aitum")
                {
                    obs.Request("CallVendorRequest", new JObject
                    {
                        ["vendorName"] = AitumVendor,
                        ["requestType"] = start ? "start_output" : "stop_output",
                        ["requestData"] = new JObject { ["name"] = t.Name },
                    });
                    return new StreamResult { Key = t.Key, Ok = true, Message = start ? "Starting" : "Stopping" };
                }
                return new StreamResult { Key = t.Key, Ok = false, Message = "Unknown kind of stream" };
            }
            catch (Exception ex) { return new StreamResult { Key = t.Key, Ok = false, Message = Describe(ex) }; }
        }

        private static string Describe(Exception ex) => ex.Message;
    }
}
