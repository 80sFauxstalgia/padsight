using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace VSCView.UiForms
{
    /// <summary>
    /// Hosts the web control panel in WebView2 (the Edge runtime built into Windows 10/11). The panel only ever
    /// shows pages from the app's own local server; every other link opens in the default browser.
    /// </summary>
    public sealed class PanelForm : Form
    {
        private readonly WebView2 web = new WebView2();
        private string url;
        private string origin;
        private bool ready;

        public PanelForm(string url, string origin, Icon icon)
        {
            this.url = url;
            this.origin = origin;
            Text = MainForm.ProductName;
            if (icon != null) Icon = icon;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(1280, 820);
            MinimumSize = new Size(720, 520);
            BackColor = Color.FromArgb(7, 11, 22);

            web.Dock = DockStyle.Fill;
            web.DefaultBackgroundColor = BackColor;
            Controls.Add(web);
            Load += async (s, e) =>
            {
                try { await InitAsync(); }
                catch (Exception ex)
                {
                    // Runtime present but unusable (policy, broken install): fall back to the default browser.
                    Debug.WriteLine("WebView2: " + ex);
                    OpenExternal(this.url, allowLocal: true);
                    Close();
                }
            };
        }

        [System.Runtime.InteropServices.DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

        /// <summary>Dark title bar to match the panel (Windows 10 20H1+ and 11; ignored elsewhere).</summary>
        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            try
            {
                int on = 1;
                if (DwmSetWindowAttribute(Handle, 20, ref on, sizeof(int)) != 0) // DWMWA_USE_IMMERSIVE_DARK_MODE
                    DwmSetWindowAttribute(Handle, 19, ref on, sizeof(int));      // pre-20H1 value
            }
            catch { }
        }

        /// <summary>True when the WebView2 runtime is installed (it ships with Windows 11 and current Windows 10).</summary>
        public static bool RuntimeAvailable()
        {
            try { return !string.IsNullOrEmpty(CoreWebView2Environment.GetAvailableBrowserVersionString()); }
            catch { return false; }
        }

        private async System.Threading.Tasks.Task InitAsync()
        {
            // Browser profile under %LOCALAPPDATA%, not next to the exe (the app folder may be read-only).
            string dataDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), MainForm.ProductName, "WebView2");
            var env = await CoreWebView2Environment.CreateAsync(null, dataDir);
            await web.EnsureCoreWebView2Async(env);
            CoreWebView2 core = web.CoreWebView2;
            core.Settings.AreDevToolsEnabled = Debugger.IsAttached;
            core.Settings.AreDefaultContextMenusEnabled = Debugger.IsAttached;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.IsPasswordAutosaveEnabled = false;
            core.Settings.IsGeneralAutofillEnabled = false;
            core.Settings.AreBrowserAcceleratorKeysEnabled = Debugger.IsAttached; // no F5/Ctrl+P etc. in the app window
            core.NewWindowRequested += (s, e) => { e.Handled = true; OpenExternal(e.Uri); };
            core.NavigationStarting += (s, e) =>
            {
                if (!IsOwnUrl(e.Uri, origin))
                {
                    e.Cancel = true;
                    OpenExternal(e.Uri);
                }
            };
            core.DocumentTitleChanged += (s, e) =>
            {
                string t = core.DocumentTitle;
                Text = string.IsNullOrWhiteSpace(t) || t.StartsWith("http", StringComparison.OrdinalIgnoreCase) ? MainForm.ProductName : t;
            };
            ready = true;
            core.Navigate(url);
        }

        /// <summary>
        /// True only for pages on the app's own server. Compares the parsed scheme, host and port, never a string
        /// prefix: "http://127.0.0.1:47817@evil.example/" starts with the origin but its host is evil.example
        /// (the "127.0.0.1:47817" part is user info), so URLs with any user info are refused outright.
        /// </summary>
        public static bool IsOwnUrl(string target, string origin)
        {
            if (!Uri.TryCreate(target, UriKind.Absolute, out Uri u) || !Uri.TryCreate(origin, UriKind.Absolute, out Uri o)) return false;
            return u.Scheme == Uri.UriSchemeHttp
                && string.IsNullOrEmpty(u.UserInfo)
                && string.Equals(u.Host, o.Host, StringComparison.OrdinalIgnoreCase)
                && u.Port == o.Port;
        }

        /// <summary>Point the panel at a new address (the server moved to another port).</summary>
        public void Navigate(string newUrl, string newOrigin)
        {
            url = newUrl;
            origin = newOrigin;
            if (ready) web.CoreWebView2.Navigate(url);
        }

        /// <summary>Only web links leave the app; anything else (file:, custom schemes) is dropped.</summary>
        private static void OpenExternal(string target, bool allowLocal = false)
        {
            if (!Uri.TryCreate(target, UriKind.Absolute, out Uri u)) return;
            if (u.Scheme != Uri.UriSchemeHttps && !(u.Scheme == Uri.UriSchemeHttp && (allowLocal || !u.IsLoopback))) return;
            try { Process.Start(u.AbsoluteUri); } catch { }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) web.Dispose();
            base.Dispose(disposing);
        }
    }
}
