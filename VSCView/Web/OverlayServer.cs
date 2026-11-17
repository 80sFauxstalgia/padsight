using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace VSCView.Web
{
    /// <summary>
    /// Minimal HTTP + WebSocket server for the OBS Browser Source.
    ///
    /// It listens on 127.0.0.1 only (a raw loopback socket, not http.sys), rejects requests whose Host
    /// header is not a loopback name (DNS-rebinding guard), serves static files from wwwroot, and pushes
    /// rendered overlay frames (transparent PNG) to WebSocket clients on /ws.
    /// </summary>
    public sealed class OverlayServer : IDisposable
    {
        private const string WsGuid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

        private readonly string webRoot;
        private readonly Func<string, OverlayChannel> channelForQuery;

        /// <summary>Optional JSON for GET /status.json (controllers, SDL status, channel stats).</summary>
        public Func<string> StatusJson { get; set; }

        /// <summary>Control panel API (<c>/api/...</c>). Called only after the key and Origin checks pass.</summary>
        public Func<ApiRequest, ApiResponse> Api { get; set; }

        /// <summary>Per-install key the control panel must send in <c>X-Panel-Key</c>.</summary>
        public string ApiKey { get; set; }

        /// <summary>Idle preview PNG for a theme path under themes/ (GET /preview?theme=...). Null when unknown.</summary>
        public Func<string, byte[]> Preview { get; set; }
        private TcpListener listener;
        private Thread acceptThread;
        private volatile bool running;

        public int Port { get; }
        public string Error { get; private set; }
        public bool IsRunning => running;

        public OverlayServer(int port, string webRoot, Func<string, OverlayChannel> channelForQuery)
        {
            Port = port;
            this.webRoot = Path.GetFullPath(webRoot);
            this.channelForQuery = channelForQuery;
        }

        public bool Start()
        {
            try
            {
                listener = new TcpListener(IPAddress.Loopback, Port);
                listener.Server.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ExclusiveAddressUse, true);
                listener.Start();
            }
            catch (Exception ex)
            {
                Error = $"Could not listen on 127.0.0.1:{Port}: {ex.Message}";
                Debug.WriteLine(Error);
                listener = null;
                return false;
            }
            running = true;
            acceptThread = new Thread(AcceptLoop) { IsBackground = true, Name = "Overlay HTTP" };
            acceptThread.Start();
            return true;
        }

        public void Dispose()
        {
            running = false;
            try { listener?.Stop(); } catch { }
        }

        private void AcceptLoop()
        {
            while (running)
            {
                TcpClient client;
                try { client = listener.AcceptTcpClient(); }
                catch { if (!running) return; Thread.Sleep(100); continue; }

                // Local-only, but still don't let anything spawn unbounded threads.
                if (Interlocked.Increment(ref connections) > MaxConnections)
                {
                    Interlocked.Decrement(ref connections);
                    try { client.Close(); } catch { }
                    continue;
                }
                new Thread(() =>
                {
                    bool handedOff = false;
                    try { handedOff = Handle(client); }
                    finally { if (!handedOff) Interlocked.Decrement(ref connections); } // WebSockets release on close
                })
                { IsBackground = true, Name = "Overlay client" }.Start();
            }
        }

        private const int MaxConnections = 32;
        private int connections;

        /// <summary>Handles one request. Returns true when the connection was handed to a WebSocket client.</summary>
        private bool Handle(TcpClient client)
        {
            client.NoDelay = true;
            NetworkStream stream = client.GetStream();
            bool keepOpen = false;
            try
            {
                stream.WriteTimeout = 5000; // a stalled reader can't pin a send thread forever
                stream.ReadTimeout = 5000;
                if (!TryReadRequest(stream, out string method, out string target, out var headers))
                    return false;

                string host = headers.TryGetValue("host", out var h) ? h : "";
                if (!IsLoopbackHost(host))
                {
                    WriteSimple(stream, 403, "Forbidden", "text/plain", Encoding.UTF8.GetBytes("Forbidden"));
                    return false;
                }

                string path = target, query = "";
                int q = target.IndexOf('?');
                if (q >= 0) { path = target.Substring(0, q); query = target.Substring(q + 1); }
                path = Uri.UnescapeDataString(path);

                if (path.StartsWith("/api/", StringComparison.Ordinal))
                {
                    HandleApi(stream, method, path, query, headers);
                    return false;
                }

                if (method != "GET")
                {
                    WriteSimple(stream, 405, "Method Not Allowed", "text/plain", Encoding.UTF8.GetBytes("GET only"));
                    return false;
                }

                if (path == "/preview")
                {
                    string theme = null;
                    foreach (string part in query.Split('&'))
                        if (part.StartsWith("theme=", StringComparison.Ordinal))
                            theme = Uri.UnescapeDataString(part.Substring(6).Replace('+', ' '));
                    byte[] png = theme == null ? null : Preview?.Invoke(theme);
                    if (png == null) WriteSimple(stream, 404, "Not Found", "text/plain", Encoding.UTF8.GetBytes("Unknown theme"));
                    else WriteSimple(stream, 200, "OK", "image/png", png);
                    return false;
                }

                if (path == "/ws")
                {
                    if (!headers.TryGetValue("sec-websocket-key", out string key) ||
                        !(headers.TryGetValue("upgrade", out string up) && up.Equals("websocket", StringComparison.OrdinalIgnoreCase)))
                    {
                        WriteSimple(stream, 400, "Bad Request", "text/plain", Encoding.UTF8.GetBytes("WebSocket upgrade required"));
                        return false;
                    }
                    // Browsers always send Origin. Only our own page (served from this port) may connect; "null"
                    // (sandboxed iframes, data: URLs) is refused. A missing Origin means a non-browser local tool.
                    if (headers.TryGetValue("origin", out string origin) && !IsLoopbackOrigin(origin))
                    {
                        WriteSimple(stream, 403, "Forbidden", "text/plain", Encoding.UTF8.GetBytes("Forbidden origin"));
                        return false;
                    }

                    OverlayChannel channel;
                    try { channel = channelForQuery(query); }
                    catch (Exception ex)
                    {
                        WriteSimple(stream, 500, "Internal Server Error", "text/plain", Encoding.UTF8.GetBytes("Theme failed to load: " + ex.Message));
                        return false;
                    }
                    if (channel == null)
                    {
                        WriteSimple(stream, 404, "Not Found", "text/plain", Encoding.UTF8.GetBytes("Unknown theme"));
                        return false;
                    }

                    string accept;
                    using (var sha = SHA1.Create())
                        accept = Convert.ToBase64String(sha.ComputeHash(Encoding.ASCII.GetBytes(key.Trim() + WsGuid)));
                    byte[] resp = Encoding.ASCII.GetBytes(
                        "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
                        $"Sec-WebSocket-Accept: {accept}\r\n\r\n");
                    stream.Write(resp, 0, resp.Length);
                    stream.ReadTimeout = Timeout.Infinite;

                    keepOpen = true;
                    var ws = new WebSocketClient(client, stream) { IsPreview = ("&" + query + "&").Contains("&preview=1&") };
                    ws.Closed += _ => Interlocked.Decrement(ref connections);
                    channel.Attach(ws); // subscribes to Closed before the socket threads start
                    ws.Start();
                    return true;
                }

                if (path == "/status.json")
                {
                    string json = StatusJson?.Invoke() ?? "{}";
                    WriteSimple(stream, 200, "OK", "application/json; charset=utf-8", Encoding.UTF8.GetBytes(json));
                    return false;
                }

                if (path == "/" || path == "") path = "/overlay.html";
                else if (path == "/panel")
                {
                    // Relative links in the panel need the trailing slash; the fragment (key) survives a redirect.
                    byte[] r = Encoding.ASCII.GetBytes("HTTP/1.1 301 Moved Permanently\r\nLocation: /panel/\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
                    stream.Write(r, 0, r.Length);
                    return false;
                }
                else if (path.EndsWith("/")) path += "index.html";
                ServeStatic(stream, path);
            }
            catch (Exception ex)
            {
                Debug.WriteLine("Overlay HTTP: " + ex.Message);
            }
            finally
            {
                if (!keepOpen)
                {
                    try { stream.Dispose(); } catch { }
                    try { client.Close(); } catch { }
                }
            }
            return keepOpen;
        }

        private const int MaxBody = 64 * 1024;

        /// <summary>
        /// /api/*: the Origin (when a browser sends one) must be this server, the key must match, and a POST must
        /// be JSON. A cross-site page can't set the key header or a JSON content type without a CORS preflight,
        /// which this server never answers, so the browser blocks it before anything runs.
        /// </summary>
        private void HandleApi(Stream stream, string method, string path, string query, Dictionary<string, string> headers)
        {
            ApiResponse res;
            if (headers.TryGetValue("origin", out string origin) && !IsLoopbackOrigin(origin))
                res = ApiResponse.Error(403, "Forbidden origin");
            else if (Api == null || !PanelKey.Matches(ApiKey, headers.TryGetValue("x-panel-key", out string k) ? k : null))
                res = ApiResponse.Error(401, "Missing or wrong panel key. Open the panel from the app or its tray icon.");
            else if (method != "GET" && method != "POST")
                res = ApiResponse.Error(405, "GET or POST only");
            else if (method == "POST" && !(headers.TryGetValue("content-type", out string ct) && ct.StartsWith("application/json", StringComparison.OrdinalIgnoreCase)))
                res = ApiResponse.Error(415, "JSON only");
            else
            {
                string body = "";
                if (method == "POST")
                {
                    int len = headers.TryGetValue("content-length", out string cl) && int.TryParse(cl, out int n) ? n : 0;
                    if (len < 0 || len > MaxBody)
                    {
                        WriteJson(stream, ApiResponse.Error(413, "Body too large"));
                        return;
                    }
                    byte[] buf = new byte[len];
                    int off = 0;
                    while (off < len)
                    {
                        int r = stream.Read(buf, off, len - off);
                        if (r <= 0) return;
                        off += r;
                    }
                    body = Encoding.UTF8.GetString(buf);
                }
                var q = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                foreach (string part in (query ?? "").Split('&'))
                {
                    if (part.Length == 0) continue;
                    int eq = part.IndexOf('=');
                    q[Uri.UnescapeDataString((eq < 0 ? part : part.Substring(0, eq)).Replace('+', ' '))] =
                        eq < 0 ? "" : Uri.UnescapeDataString(part.Substring(eq + 1).Replace('+', ' '));
                }
                try { res = Api(new ApiRequest { Method = method, Path = path, Query = q, Body = body }) ?? ApiResponse.Error(404, "Unknown API"); }
                // The text may carry an OBS error comment (scenes, add-source and fix-port all call OBS): filter it like
                // every other message from OBS before the panel shows it.
                catch (Exception ex) { res = ApiResponse.Error(500, VSCView.Obs.StreamTargets.SafeText(ex.Message)); }
            }
            WriteJson(stream, res);
        }

        private static void WriteJson(Stream stream, ApiResponse res)
        {
            string reason = res.Code == 200 ? "OK" : res.Code == 401 ? "Unauthorized" : res.Code == 403 ? "Forbidden" :
                            res.Code == 404 ? "Not Found" : res.Code >= 500 ? "Internal Server Error" : "Bad Request";
            WriteSimple(stream, res.Code, reason, "application/json; charset=utf-8", Encoding.UTF8.GetBytes(res.Json ?? "{}"));
        }

        private void ServeStatic(Stream stream, string path)
        {
            string rel = path.TrimStart('/').Replace('/', Path.DirectorySeparatorChar);
            string full = Path.GetFullPath(Path.Combine(webRoot, rel));
            if (!full.StartsWith(webRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) || !File.Exists(full))
            {
                WriteSimple(stream, 404, "Not Found", "text/plain", Encoding.UTF8.GetBytes("Not found"));
                return;
            }
            string type;
            switch (Path.GetExtension(full).ToLowerInvariant())
            {
                case ".html": type = "text/html; charset=utf-8"; break;
                case ".js": type = "text/javascript; charset=utf-8"; break;
                case ".css": type = "text/css; charset=utf-8"; break;
                case ".png": type = "image/png"; break;
                case ".svg": type = "image/svg+xml"; break;
                case ".ico": type = "image/x-icon"; break;
                case ".json": type = "application/json; charset=utf-8"; break;
                default: type = "application/octet-stream"; break;
            }
            // The control panel gets a strict policy: its own scripts only, no third-party loads, no framing by
            // other sites. (The OBS overlay page keeps its inline script, so it gets only the framing rule.)
            string extra = "X-Frame-Options: SAMEORIGIN\r\n";
            if (path.StartsWith("/panel/", StringComparison.Ordinal))
                extra += "Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
                         "img-src 'self' data: blob:; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'\r\n" +
                         "Referrer-Policy: no-referrer\r\n";
            WriteSimple(stream, 200, "OK", type, File.ReadAllBytes(full), extra);
        }

        private static void WriteSimple(Stream stream, int code, string reason, string type, byte[] body, string extraHeaders = "")
        {
            byte[] head = Encoding.ASCII.GetBytes(
                $"HTTP/1.1 {code} {reason}\r\nContent-Type: {type}\r\nContent-Length: {body.Length}\r\n" +
                "Cache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n" + extraHeaders + "Connection: close\r\n\r\n");
            stream.Write(head, 0, head.Length);
            stream.Write(body, 0, body.Length);
            stream.Flush();
        }

        private static bool TryReadRequest(Stream stream, out string method, out string target, out Dictionary<string, string> headers)
        {
            method = target = null;
            headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var buf = new List<byte>(1024);
            int b;
            // read until CRLFCRLF, max 16 KiB
            while ((b = stream.ReadByte()) >= 0)
            {
                buf.Add((byte)b);
                int n = buf.Count;
                if (n >= 4 && buf[n - 4] == '\r' && buf[n - 3] == '\n' && buf[n - 2] == '\r' && buf[n - 1] == '\n') break;
                if (n > 16384) return false;
            }
            string text = Encoding.ASCII.GetString(buf.ToArray());
            string[] lines = text.Split(new[] { "\r\n" }, StringSplitOptions.None);
            if (lines.Length < 1) return false;
            string[] first = lines[0].Split(' ');
            if (first.Length < 3) return false;
            method = first[0];
            target = first[1];
            for (int i = 1; i < lines.Length; i++)
            {
                int c = lines[i].IndexOf(':');
                if (c > 0) headers[lines[i].Substring(0, c).Trim()] = lines[i].Substring(c + 1).Trim();
            }
            return true;
        }

        private bool IsLoopbackHost(string host)
        {
            return host == $"127.0.0.1:{Port}" || host.Equals($"localhost:{Port}", StringComparison.OrdinalIgnoreCase) ||
                   host == "127.0.0.1" || host.Equals("localhost", StringComparison.OrdinalIgnoreCase);
        }

        private bool IsLoopbackOrigin(string origin)
        {
            return origin == $"http://127.0.0.1:{Port}" || origin.Equals($"http://localhost:{Port}", StringComparison.OrdinalIgnoreCase);
        }
    }

    /// <summary>One connected WebSocket. Sends latest-frame-wins so a slow client never builds a backlog.</summary>
    public sealed class WebSocketClient : IDisposable
    {
        private readonly TcpClient client;
        private readonly Stream stream;
        private readonly object gate = new object();
        private readonly AutoResetEvent wake = new AutoResetEvent(false);
        private byte[] pendingBinary;
        private string pendingText;
        private int closedFlag;
        private bool closed => Volatile.Read(ref closedFlag) != 0;

        public event Action<WebSocketClient> Closed;
        public bool IsClosed => closed;

        /// <summary>True for the control panel's own preview (<c>?preview=1</c>), so it isn't counted as an OBS source.</summary>
        public bool IsPreview { get; set; }

        public WebSocketClient(TcpClient client, Stream stream)
        {
            this.client = client;
            this.stream = stream;
        }

        /// <summary>Start the socket threads. Call after subscribing to <see cref="Closed"/>.</summary>
        public void Start()
        {
            new Thread(SendLoop) { IsBackground = true, Name = "WS send" }.Start();
            new Thread(ReceiveLoop) { IsBackground = true, Name = "WS receive" }.Start();
        }

        public void SendFrame(byte[] png)
        {
            if (closed) return;
            lock (gate) pendingBinary = png;
            wake.Set();
        }

        public void SendText(string text)
        {
            if (closed) return;
            lock (gate) pendingText = text;
            wake.Set();
        }

        private void SendLoop()
        {
            try
            {
                while (!closed)
                {
                    wake.WaitOne(1000);
                    string text; byte[] bin;
                    lock (gate)
                    {
                        text = pendingText; pendingText = null;
                        bin = pendingBinary; pendingBinary = null;
                    }
                    if (text != null) WriteFrame(0x1, Encoding.UTF8.GetBytes(text));
                    if (bin != null) WriteFrame(0x2, bin);
                }
            }
            catch { }
            Dispose();
        }

        private void ReceiveLoop()
        {
            // We only care about close/ping from the client. Client frames are masked (RFC 6455).
            try
            {
                var hdr = new byte[14];
                while (!closed)
                {
                    if (!ReadExactly(hdr, 0, 2)) break;
                    int opcode = hdr[0] & 0x0F;
                    bool masked = (hdr[1] & 0x80) != 0;
                    long len = hdr[1] & 0x7F;
                    if (len == 126) { if (!ReadExactly(hdr, 0, 2)) break; len = (hdr[0] << 8) | hdr[1]; }
                    else if (len == 127) { if (!ReadExactly(hdr, 0, 8)) break; len = 0; for (int i = 0; i < 8; i++) len = (len << 8) | hdr[i]; }
                    if (len > 65536) break;
                    byte[] mask = new byte[4];
                    if (masked && !ReadExactly(mask, 0, 4)) break;
                    byte[] payload = new byte[len];
                    if (len > 0 && !ReadExactly(payload, 0, (int)len)) break;
                    if (masked) for (int i = 0; i < payload.Length; i++) payload[i] ^= mask[i & 3];

                    if (opcode == 0x8) { try { WriteFrame(0x8, new byte[0]); } catch { } break; } // close
                    if (opcode == 0x9) WriteFrame(0xA, payload);                                   // ping -> pong
                }
            }
            catch { }
            Dispose();
        }

        private bool ReadExactly(byte[] buf, int off, int count)
        {
            while (count > 0)
            {
                int r = stream.Read(buf, off, count);
                if (r <= 0) return false;
                off += r; count -= r;
            }
            return true;
        }

        private readonly object writeLock = new object();
        private void WriteFrame(int opcode, byte[] payload)
        {
            lock (writeLock)
            {
                int n = payload.Length;
                byte[] head;
                if (n < 126) head = new byte[] { (byte)(0x80 | opcode), (byte)n };
                else if (n <= 0xFFFF) head = new byte[] { (byte)(0x80 | opcode), 126, (byte)(n >> 8), (byte)n };
                else
                {
                    head = new byte[10];
                    head[0] = (byte)(0x80 | opcode); head[1] = 127;
                    for (int i = 0; i < 8; i++) head[9 - i] = (byte)((long)n >> (8 * i));
                }
                stream.Write(head, 0, head.Length);
                stream.Write(payload, 0, n);
                stream.Flush();
            }
        }

        public void Dispose()
        {
            if (Interlocked.Exchange(ref closedFlag, 1) != 0) return; // Closed fires exactly once
            wake.Set();
            try { stream.Dispose(); } catch { }
            try { client.Close(); } catch { }
            Closed?.Invoke(this);
        }
    }
}
