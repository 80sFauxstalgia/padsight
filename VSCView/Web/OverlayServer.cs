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
                catch { if (!running) return; continue; }
                new Thread(() => Handle(client)) { IsBackground = true, Name = "Overlay client" }.Start();
            }
        }

        private void Handle(TcpClient client)
        {
            client.NoDelay = true;
            NetworkStream stream = client.GetStream();
            bool keepOpen = false;
            try
            {
                stream.ReadTimeout = 5000;
                if (!TryReadRequest(stream, out string method, out string target, out var headers))
                    return;

                string host = headers.TryGetValue("host", out var h) ? h : "";
                if (!IsLoopbackHost(host))
                {
                    WriteSimple(stream, 403, "Forbidden", "text/plain", Encoding.UTF8.GetBytes("Forbidden"));
                    return;
                }

                string path = target, query = "";
                int q = target.IndexOf('?');
                if (q >= 0) { path = target.Substring(0, q); query = target.Substring(q + 1); }
                path = Uri.UnescapeDataString(path);

                if (method != "GET")
                {
                    WriteSimple(stream, 405, "Method Not Allowed", "text/plain", Encoding.UTF8.GetBytes("GET only"));
                    return;
                }

                if (path == "/ws")
                {
                    if (!headers.TryGetValue("sec-websocket-key", out string key) ||
                        !(headers.TryGetValue("upgrade", out string up) && up.Equals("websocket", StringComparison.OrdinalIgnoreCase)))
                    {
                        WriteSimple(stream, 400, "Bad Request", "text/plain", Encoding.UTF8.GetBytes("WebSocket upgrade required"));
                        return;
                    }
                    if (headers.TryGetValue("origin", out string origin) && origin != "null" && !IsLoopbackOrigin(origin))
                    {
                        WriteSimple(stream, 403, "Forbidden", "text/plain", Encoding.UTF8.GetBytes("Forbidden origin"));
                        return;
                    }

                    OverlayChannel channel = channelForQuery(query);
                    if (channel == null)
                    {
                        WriteSimple(stream, 404, "Not Found", "text/plain", Encoding.UTF8.GetBytes("Unknown theme"));
                        return;
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
                    var ws = new WebSocketClient(client, stream);
                    channel.Attach(ws);
                    return;
                }

                if (path == "/" || path == "") path = "/overlay.html";
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
                default: type = "application/octet-stream"; break;
            }
            WriteSimple(stream, 200, "OK", type, File.ReadAllBytes(full));
        }

        private static void WriteSimple(Stream stream, int code, string reason, string type, byte[] body)
        {
            byte[] head = Encoding.ASCII.GetBytes(
                $"HTTP/1.1 {code} {reason}\r\nContent-Type: {type}\r\nContent-Length: {body.Length}\r\n" +
                "Cache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n");
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
        private volatile bool closed;

        public event Action<WebSocketClient> Closed;
        public bool IsClosed => closed;

        public WebSocketClient(TcpClient client, Stream stream)
        {
            this.client = client;
            this.stream = stream;
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
            if (closed) return;
            closed = true;
            wake.Set();
            try { stream.Dispose(); } catch { }
            try { client.Close(); } catch { }
            Closed?.Invoke(this);
        }
    }
}
