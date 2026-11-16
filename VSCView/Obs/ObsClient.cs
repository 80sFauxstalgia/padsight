using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.WebSockets;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace VSCView.Obs
{
    /// <summary>
    /// Minimal obs-websocket v5 client (OBS 28+): connects, authenticates, sends requests and raises the events
    /// PadSight uses (program scene changes, stream and record state). Reconnects by itself while enabled.
    /// The password is only held in memory here; it's stored encrypted by <see cref="ObsPassword"/>.
    /// </summary>
    public sealed class ObsClient : IDisposable
    {
        // Event subscription bits (obs-websocket protocol): Scenes = 1 << 2, Outputs = 1 << 6.
        private const int EventSubscriptions = (1 << 2) | (1 << 6);

        public enum ObsStatus { Off, Connecting, Connected, WrongPassword, Unreachable }

        private readonly object gate = new object();
        private readonly ConcurrentDictionary<string, TaskCompletionSource<JObject>> pending = new ConcurrentDictionary<string, TaskCompletionSource<JObject>>();
        private CancellationTokenSource cts;
        private ClientWebSocket socket;
        private volatile bool handshakeDone; // handshake done on the current socket
        private readonly SemaphoreSlim sendLock = new SemaphoreSlim(1, 1);

        public string Host { get; private set; } = "127.0.0.1";
        public int Port { get; private set; } = 4455;
        private string password;

        public ObsStatus Status { get; private set; } = ObsStatus.Off;
        public string Error { get; private set; }
        public string ObsVersion { get; private set; }

        /// <summary>Program scene changed (scene name).</summary>
        public event Action<string> ProgramSceneChanged;
        /// <summary>Streaming or recording started or stopped (streaming, recording).</summary>
        public event Action<bool, bool> OutputsChanged;
        /// <summary>Connected, disconnected, or the password was refused.</summary>
        public event Action StatusChanged;

        public bool Streaming { get; private set; }
        public bool Recording { get; private set; }
        public string ProgramScene { get; private set; }

        /// <summary>(Re)start the connection loop with these settings. Null password = no authentication.</summary>
        public void Start(string host, int port, string password)
        {
            Stop();
            Host = string.IsNullOrWhiteSpace(host) ? "127.0.0.1" : host.Trim();
            Port = port > 0 && port < 65536 ? port : 4455;
            this.password = password;
            cts = new CancellationTokenSource();
            var token = cts.Token;
            Task.Run(() => RunAsync(token));
        }

        public void Stop()
        {
            try { cts?.Cancel(); } catch { }
            cts = null;
            handshakeDone = false;
            var old = socket;
            if (old != null && old.State == WebSocketState.Open)
            {
                // Polite close on disconnect, bounded so the UI never waits long.
                try { old.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "", CancellationToken.None).Wait(500); } catch { }
            }
            try { socket?.Abort(); } catch { }
            socket = null;
            FailPending("Disconnected");
            SetStatus(ObsStatus.Off, null);
        }

        public void Dispose() => Stop();

        private void SetStatus(ObsStatus s, string error)
        {
            bool changed = Status != s || Error != error;
            Status = s;
            Error = error;
            if (changed) try { StatusChanged?.Invoke(); } catch (Exception ex) { Debug.WriteLine("OBS status handler: " + ex); }
        }

        private async Task RunAsync(CancellationToken token)
        {
            int backoff = 1000;
            while (!token.IsCancellationRequested)
            {
                handshakeDone = false;
                SetStatus(ObsStatus.Connecting, null);
                var ws = new ClientWebSocket();
                ws.Options.KeepAliveInterval = TimeSpan.FromSeconds(20);
                socket = ws;
                bool authFailed = false;
                try
                {
                    using (var connectTimeout = CancellationTokenSource.CreateLinkedTokenSource(token))
                    {
                        connectTimeout.CancelAfter(5000);
                        var target = new UriBuilder("ws", Host, Port).Uri; // also brackets IPv6 addresses
                        await ws.ConnectAsync(target, connectTimeout.Token).ConfigureAwait(false);
                    }
                    JObject hello = await ReceiveAsync(ws, token).ConfigureAwait(false);
                    if ((int?)hello?["op"] != 0) throw new IOException("Not an obs-websocket server");
                    ObsVersion = (string)hello["d"]?["obsWebSocketVersion"];

                    var identify = new JObject { ["rpcVersion"] = 1, ["eventSubscriptions"] = EventSubscriptions };
                    JToken auth = hello["d"]?["authentication"];
                    if (auth != null)
                    {
                        if (string.IsNullOrEmpty(password)) { authFailed = true; throw new IOException("OBS asks for a password"); }
                        identify["authentication"] = AuthString(password, (string)auth["salt"], (string)auth["challenge"]);
                    }
                    await SendAsync(ws, new JObject { ["op"] = 1, ["d"] = identify }, token).ConfigureAwait(false);

                    JObject identified;
                    try { identified = await ReceiveAsync(ws, token).ConfigureAwait(false); }
                    catch (WebSocketException) when (ws.CloseStatus.HasValue) { identified = null; }
                    if ((int?)identified?["op"] != 2)
                    {
                        // obs-websocket closes with 4009 (AuthenticationFailed) on a wrong password.
                        authFailed = (int?)ws.CloseStatus == 4009 || auth != null;
                        throw new IOException(authFailed ? "OBS refused the password" : "OBS closed the connection: " + ws.CloseStatusDescription);
                    }

                    // Read the current scene and outputs first, so "Connected" never shows with an unknown scene.
                    handshakeDone = true;
                    backoff = 3000; // if this session drops (OBS restarting), give it a moment before the first retry
                    var readLoop = ReadLoopAsync(ws, token);
                    await RefreshStateAsync().ConfigureAwait(false);
                    SetStatus(ObsStatus.Connected, null);
                    await readLoop.ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (token.IsCancellationRequested) { break; }
                catch (Exception ex)
                {
                    Debug.WriteLine("OBS: " + ex.Message);
                    if (authFailed)
                    {
                        SetStatus(ObsStatus.WrongPassword, ex.Message);
                        try { ws.Abort(); } catch { }
                        FailPending("Disconnected");
                        break; // retrying a wrong password helps nobody; wait for a new one
                    }
                    SetStatus(ObsStatus.Unreachable, ex is WebSocketException || ex is IOException || ex is OperationCanceledException
                        ? $"OBS isn't answering on {Host}:{Port}. Is OBS running, with its WebSocket server on?"
                        : ex.Message);
                }
                finally
                {
                    handshakeDone = false;
                    try { ws.Abort(); } catch { }
                    FailPending("Disconnected");
                }
                try { await Task.Delay(backoff, token).ConfigureAwait(false); } catch { break; }
                backoff = Math.Min(backoff * 2, 10000);
            }
        }

        /// <summary>obs-websocket v5 auth: base64(sha256(base64(sha256(password + salt)) + challenge)).</summary>
        public static string AuthString(string password, string salt, string challenge)
        {
            using (var sha = SHA256.Create())
            {
                string secret = Convert.ToBase64String(sha.ComputeHash(Encoding.UTF8.GetBytes(password + salt)));
                return Convert.ToBase64String(sha.ComputeHash(Encoding.UTF8.GetBytes(secret + challenge)));
            }
        }

        private async Task RefreshStateAsync()
        {
            try
            {
                JObject scene = await RequestAsync("GetCurrentProgramScene").ConfigureAwait(false);
                ProgramScene = (string)scene?["currentProgramSceneName"] ?? (string)scene?["sceneName"];
                JObject stream = await RequestAsync("GetStreamStatus").ConfigureAwait(false);
                JObject record = await RequestAsync("GetRecordStatus").ConfigureAwait(false);
                Streaming = (bool?)stream?["outputActive"] ?? false;
                Recording = (bool?)record?["outputActive"] ?? false;
                ProgramSceneChanged?.Invoke(ProgramScene);
                OutputsChanged?.Invoke(Streaming, Recording);
            }
            catch (Exception ex) { Debug.WriteLine("OBS refresh: " + ex.Message); }
        }

        private async Task ReadLoopAsync(ClientWebSocket ws, CancellationToken token)
        {
            while (!token.IsCancellationRequested && ws.State == WebSocketState.Open)
            {
                JObject msg = await ReceiveAsync(ws, token).ConfigureAwait(false);
                if (msg == null) break;
                int op = (int?)msg["op"] ?? -1;
                JObject d = msg["d"] as JObject;
                if (op == 7 && d != null) // RequestResponse
                {
                    string id = (string)d["requestId"];
                    if (id != null && pending.TryRemove(id, out var tcs))
                    {
                        bool ok = (bool?)d["requestStatus"]?["result"] ?? false;
                        if (ok) tcs.TrySetResult(d["responseData"] as JObject ?? new JObject());
                        else tcs.TrySetException(new ObsRequestException((string)d["requestType"], (int?)d["requestStatus"]?["code"] ?? 0,
                            (string)d["requestStatus"]?["comment"]));
                    }
                }
                else if (op == 5 && d != null) // Event
                {
                    try { HandleEvent((string)d["eventType"], d["eventData"] as JObject); }
                    catch (Exception ex) { Debug.WriteLine("OBS event: " + ex); }
                }
            }
            throw new IOException("OBS closed the connection");
        }

        private void HandleEvent(string type, JObject data)
        {
            switch (type)
            {
                case "CurrentProgramSceneChanged":
                    ProgramScene = (string)data?["sceneName"];
                    ProgramSceneChanged?.Invoke(ProgramScene);
                    break;
                case "StreamStateChanged":
                    Streaming = (bool?)data?["outputActive"] ?? false;
                    OutputsChanged?.Invoke(Streaming, Recording);
                    break;
                case "RecordStateChanged":
                    Recording = (bool?)data?["outputActive"] ?? false;
                    OutputsChanged?.Invoke(Streaming, Recording);
                    break;
            }
        }

        /// <summary>Send a request and wait for its response data (throws <see cref="ObsRequestException"/> on failure).</summary>
        public async Task<JObject> RequestAsync(string type, JObject data = null, int timeoutMs = 5000)
        {
            ClientWebSocket ws = socket;
            if (ws == null || !handshakeDone) throw new InvalidOperationException("Not connected to OBS");
            string id = Guid.NewGuid().ToString("N");
            var tcs = new TaskCompletionSource<JObject>(TaskCreationOptions.RunContinuationsAsynchronously);
            pending[id] = tcs;
            var d = new JObject { ["requestType"] = type, ["requestId"] = id };
            if (data != null) d["requestData"] = data;
            await SendAsync(ws, new JObject { ["op"] = 6, ["d"] = d }, CancellationToken.None).ConfigureAwait(false);
            var done = await Task.WhenAny(tcs.Task, Task.Delay(timeoutMs)).ConfigureAwait(false);
            if (done != tcs.Task)
            {
                pending.TryRemove(id, out _);
                throw new TimeoutException($"OBS didn't answer {type}");
            }
            return await tcs.Task.ConfigureAwait(false);
        }

        /// <summary>Synchronous wrapper for callers on the UI or server thread.</summary>
        public JObject Request(string type, JObject data = null, int timeoutMs = 5000)
        {
            try { return Task.Run(() => RequestAsync(type, data, timeoutMs)).GetAwaiter().GetResult(); }
            catch (AggregateException ex) when (ex.InnerException != null) { throw ex.InnerException; }
        }

        private void FailPending(string why)
        {
            foreach (var kv in pending)
                if (pending.TryRemove(kv.Key, out var tcs)) tcs.TrySetException(new IOException(why));
        }

        private async Task SendAsync(ClientWebSocket ws, JObject msg, CancellationToken token)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(msg.ToString(Formatting.None));
            await sendLock.WaitAsync(token).ConfigureAwait(false);
            try { await ws.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, token).ConfigureAwait(false); }
            finally { sendLock.Release(); }
        }

        private static async Task<JObject> ReceiveAsync(ClientWebSocket ws, CancellationToken token)
        {
            var buffer = new byte[16 * 1024];
            using (var ms = new MemoryStream())
            {
                while (true)
                {
                    WebSocketReceiveResult r = await ws.ReceiveAsync(new ArraySegment<byte>(buffer), token).ConfigureAwait(false);
                    if (r.MessageType == WebSocketMessageType.Close)
                    {
                        // Answer OBS's close (e.g. it restarts its WebSocket server) instead of dropping the socket,
                        // so OBS never waits on PadSight during shutdown. Bounded, and best effort.
                        try
                        {
                            using (var t = new CancellationTokenSource(1000))
                                await ws.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "", t.Token).ConfigureAwait(false);
                        }
                        catch { }
                        return null;
                    }
                    ms.Write(buffer, 0, r.Count);
                    if (ms.Length > 4 * 1024 * 1024) throw new IOException("OBS message too large");
                    if (r.EndOfMessage) break;
                }
                return JObject.Parse(Encoding.UTF8.GetString(ms.ToArray()));
            }
        }
    }

    public sealed class ObsRequestException : Exception
    {
        public int Code { get; }
        public ObsRequestException(string request, int code, string comment)
            : base($"OBS refused {request}: {(string.IsNullOrEmpty(comment) ? "error " + code : comment)}") { Code = code; }
    }

    /// <summary>The OBS WebSocket password, encrypted for the current Windows user (DPAPI).</summary>
    public static class ObsPassword
    {
        private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("PadSight.obs-websocket");

        public static string Protect(string password)
        {
            if (string.IsNullOrEmpty(password)) return null;
            byte[] data = ProtectedData.Protect(Encoding.UTF8.GetBytes(password), Entropy, DataProtectionScope.CurrentUser);
            return Convert.ToBase64String(data);
        }

        public static string Unprotect(string stored)
        {
            if (string.IsNullOrEmpty(stored)) return null;
            try { return Encoding.UTF8.GetString(ProtectedData.Unprotect(Convert.FromBase64String(stored), Entropy, DataProtectionScope.CurrentUser)); }
            catch { return null; } // another Windows user or a copied settings file: ask again
        }
    }
}
