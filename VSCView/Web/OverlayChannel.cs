using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Threading;

namespace VSCView.Web
{
    /// <summary>
    /// Renders one theme with VSCView's own renderer into a transparent bitmap at a fixed rate and
    /// pushes changed frames (PNG with alpha) to every attached WebSocket client.
    /// Nothing is rendered while no client is connected, and identical frames are not re-sent.
    /// </summary>
    public sealed class OverlayChannel : IDisposable
    {
        private readonly object uiLock = new object();
        private readonly List<WebSocketClient> clients = new List<WebSocketClient>();
        private UI ui;
        private Bitmap bitmap;
        private byte[] lastPng;
        private ulong lastHash;
        private volatile bool running = true;
        private readonly Thread thread;

        public string Key { get; }
        public int Fps { get; }
        public bool OwnsUi { get; }

        // stats (render thread only writes)
        public double AvgRenderMs { get; private set; }
        public double AvgEncodeMs { get; private set; }
        public long FramesSent { get; private set; }
        public long FramesSkipped { get; private set; }
        public int ClientCount { get { lock (clients) return clients.Count; } }

        public OverlayChannel(string key, int fps, bool ownsUi)
        {
            Key = key;
            Fps = Math.Max(1, Math.Min(120, fps));
            OwnsUi = ownsUi;
            thread = new Thread(RenderLoop) { IsBackground = true, Name = "Overlay render " + key, Priority = ThreadPriority.AboveNormal };
            thread.Start();
        }

        /// <summary>Swap in a freshly constructed UI (never share a UI with the window: trailpads keep per-instance history).</summary>
        public void SetUi(UI newUi)
        {
            UI old;
            lock (uiLock)
            {
                old = ui;
                ui = newUi;
                lastHash = 0;
                lastPng = null;
                bitmap?.Dispose();
                bitmap = null;
            }
            old?.Dispose();
            Broadcast(MetaJson());
        }

        public void Attach(WebSocketClient ws)
        {
            ws.Closed += c => { lock (clients) clients.Remove(c); };
            lock (clients) clients.Add(ws);
            ws.SendText(MetaJson());
            byte[] png = lastPng;
            if (png != null) ws.SendFrame(png);
        }

        private string MetaJson()
        {
            UI u = ui;
            return u == null
                ? "{\"type\":\"meta\",\"width\":0,\"height\":0}"
                : $"{{\"type\":\"meta\",\"width\":{u.Width},\"height\":{u.Height},\"fps\":{Fps}}}";
        }

        private void Broadcast(string text)
        {
            WebSocketClient[] list;
            lock (clients) list = clients.ToArray();
            foreach (var c in list) c.SendText(text);
        }

        private void RenderLoop()
        {
            var clock = Stopwatch.StartNew();
            double frameMs = 1000.0 / Fps;
            double next = 0;
            while (running)
            {
                WebSocketClient[] list;
                lock (clients) list = clients.ToArray();
                if (list.Length == 0 || ui == null)
                {
                    Thread.Sleep(50);
                    next = clock.Elapsed.TotalMilliseconds;
                    continue;
                }

                double now = clock.Elapsed.TotalMilliseconds;
                if (now < next)
                {
                    int wait = (int)(next - now);
                    if (wait > 1) Thread.Sleep(wait - 1); else Thread.Sleep(0);
                    continue;
                }
                next += frameMs;
                if (now - next > frameMs * 4) next = now + frameMs; // fell far behind; don't spiral

                try { RenderOnce(list); }
                catch (Exception ex) { Debug.WriteLine("Overlay render: " + ex); Thread.Sleep(250); }
            }
        }

        private unsafe void RenderOnce(WebSocketClient[] list)
        {
            byte[] png = null;
            lock (uiLock)
            {
                if (ui == null) return;
                long t0 = Stopwatch.GetTimestamp();
                if (bitmap == null || bitmap.Width != ui.Width || bitmap.Height != ui.Height)
                {
                    bitmap?.Dispose();
                    bitmap = new Bitmap(Math.Max(1, ui.Width), Math.Max(1, ui.Height), PixelFormat.Format32bppArgb);
                }
                using (Graphics g = Graphics.FromImage(bitmap))
                {
                    g.Clear(Color.Transparent);
                    ui.Paint(g);
                }

                // Hash raw pixels; only encode + send when something changed.
                ulong hash = 14695981039346656037UL;
                var data = bitmap.LockBits(new Rectangle(0, 0, bitmap.Width, bitmap.Height), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
                try
                {
                    for (int y = 0; y < data.Height; y++)
                    {
                        ulong* row = (ulong*)((byte*)data.Scan0 + (long)y * data.Stride);
                        int n = data.Width / 2;
                        for (int x = 0; x < n; x++) { hash ^= row[x]; hash *= 1099511628211UL; }
                    }
                }
                finally { bitmap.UnlockBits(data); }
                long t1 = Stopwatch.GetTimestamp();
                AvgRenderMs = AvgRenderMs * 0.95 + (t1 - t0) * 1000.0 / Stopwatch.Frequency * 0.05;

                if (hash == lastHash && lastPng != null)
                {
                    FramesSkipped++;
                    return;
                }
                lastHash = hash;

                using (var ms = new MemoryStream(64 * 1024))
                {
                    bitmap.Save(ms, ImageFormat.Png);
                    png = ms.ToArray();
                }
                long t2 = Stopwatch.GetTimestamp();
                AvgEncodeMs = AvgEncodeMs * 0.95 + (t2 - t1) * 1000.0 / Stopwatch.Frequency * 0.05;
                lastPng = png;
            }
            foreach (var c in list) c.SendFrame(png);
            FramesSent++;
        }

        public void Dispose()
        {
            running = false;
            thread.Join(1000);
            WebSocketClient[] list;
            lock (clients) list = clients.ToArray();
            foreach (var c in list) c.Dispose();
            lock (uiLock)
            {
                ui?.Dispose();
                ui = null;
                bitmap?.Dispose();
                bitmap = null;
            }
        }
    }
}
