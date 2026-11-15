using System;
using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;

namespace VSCView.UiForms
{
    /// <summary>Values edited by <see cref="SettingsForm"/>.</summary>
    public sealed class SettingsValues
    {
        public bool OverlayEnabled { get; set; }
        public int OverlayPort { get; set; }
        public int OverlayFps { get; set; }
        public bool AutoSelectOnlyController { get; set; }
        public bool RememberThemePerController { get; set; }
        public bool FollowActiveController { get; set; }
        public Color Background { get; set; }
    }

    public sealed class SettingsForm : Form
    {
        private readonly CheckBox chkOverlay = new CheckBox { Text = "Run the OBS Browser Source server", AutoSize = true };
        private readonly NumericUpDown numPort = new NumericUpDown { Minimum = 1024, Maximum = 65535, Width = 90 };
        private readonly NumericUpDown numFps = new NumericUpDown { Minimum = 10, Maximum = 120, Width = 90 };
        private readonly TextBox txtUrl = new TextBox { ReadOnly = true, Width = 300 };
        private readonly Label lblStatus = new Label { AutoSize = true, MaximumSize = new Size(470, 0) };
        private readonly CheckBox chkAuto = new CheckBox { Text = "Automatically select the controller when only one is connected", AutoSize = true };
        private readonly CheckBox chkFollow = new CheckBox { Text = "Switch to whichever controller is being used", AutoSize = true };
        private readonly CheckBox chkRemember = new CheckBox { Text = "Remember a theme for each kind of controller", AutoSize = true };
        private readonly Button btnColor = new Button { Text = "Window background…", AutoSize = true };
        private readonly Panel swatch = new Panel { Width = 24, Height = 24, BorderStyle = BorderStyle.FixedSingle };
        private readonly Timer refresh = new Timer { Interval = 1000 };
        private readonly Func<string> statusText;

        public SettingsValues Values { get; }

        public SettingsForm(SettingsValues values, Func<string> statusText)
        {
            Values = values;
            this.statusText = statusText;

            Text = "Settings";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            AutoSize = true;
            AutoSizeMode = AutoSizeMode.GrowAndShrink;
            Font = SystemFonts.MessageBoxFont;
            Padding = new Padding(10);

            var root = new FlowLayoutPanel { FlowDirection = FlowDirection.TopDown, AutoSize = true, WrapContents = false, Dock = DockStyle.Fill };

            // --- OBS
            var obs = Group("OBS Browser Source (transparent, no chroma key)");
            var obsBody = Stack();
            obsBody.Controls.Add(chkOverlay);
            obsBody.Controls.Add(Row(new Label { Text = "Port", AutoSize = true, Margin = new Padding(0, 6, 6, 0) }, numPort,
                                     new Label { Text = "Frame rate", AutoSize = true, Margin = new Padding(18, 6, 6, 0) }, numFps,
                                     new Label { Text = "fps", AutoSize = true, Margin = new Padding(3, 6, 0, 0) }));
            var copy = new Button { Text = "Copy", AutoSize = true };
            copy.Click += (s, e) => { try { Clipboard.SetText(txtUrl.Text); } catch { } };
            var open = new Button { Text = "Open", AutoSize = true };
            open.Click += (s, e) => { try { Process.Start(txtUrl.Text); } catch { } };
            obsBody.Controls.Add(Row(new Label { Text = "URL", AutoSize = true, Margin = new Padding(0, 6, 6, 0) }, txtUrl, copy, open));
            obsBody.Controls.Add(new Label
            {
                AutoSize = true,
                MaximumSize = new Size(470, 0),
                ForeColor = SystemColors.GrayText,
                Text = "In OBS: Sources → + → Browser → paste the URL, set the width/height to the theme size. " +
                       "The server only listens on 127.0.0.1 (this PC). Port/frame rate changes apply after OK."
            });
            obsBody.Controls.Add(lblStatus);
            obs.Controls.Add(obsBody);
            root.Controls.Add(obs);

            // --- controllers
            var ctl = Group("Controllers");
            var ctlBody = Stack();
            ctlBody.Controls.Add(chkAuto);
            ctlBody.Controls.Add(chkFollow);
            ctlBody.Controls.Add(chkRemember);
            ctlBody.Controls.Add(new Label
            {
                AutoSize = true,
                MaximumSize = new Size(470, 0),
                ForeColor = SystemColors.GrayText,
                Text = "With both options on, one OBS source can follow you between controllers: e.g. a 2015 Steam Controller theme " +
                       "for one game and a 2026 Steam Controller theme for another, switching as soon as you press something."
            });
            ctl.Controls.Add(ctlBody);
            root.Controls.Add(ctl);

            // --- window
            var win = Group("Window");
            btnColor.Click += (s, e) =>
            {
                using (var dlg = new ColorDialog { Color = swatch.BackColor, FullOpen = true })
                    if (dlg.ShowDialog(this) == DialogResult.OK) swatch.BackColor = dlg.Color;
            };
            win.Controls.Add(Row(btnColor, swatch));
            root.Controls.Add(win);

            // --- buttons
            var ok = new Button { Text = "OK", DialogResult = DialogResult.OK, AutoSize = true, MinimumSize = new Size(80, 0) };
            var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, AutoSize = true, MinimumSize = new Size(80, 0) };
            ok.Click += (s, e) => Save();
            AcceptButton = ok;
            CancelButton = cancel;
            var btns = new FlowLayoutPanel { FlowDirection = FlowDirection.RightToLeft, AutoSize = true, Anchor = AnchorStyles.Right, Width = 490 };
            btns.Controls.Add(cancel);
            btns.Controls.Add(ok);
            root.Controls.Add(btns);
            Controls.Add(root);

            chkOverlay.Checked = values.OverlayEnabled;
            numPort.Value = Math.Max(numPort.Minimum, Math.Min(numPort.Maximum, values.OverlayPort));
            numFps.Value = Math.Max(numFps.Minimum, Math.Min(numFps.Maximum, values.OverlayFps));
            chkAuto.Checked = values.AutoSelectOnlyController;
            chkFollow.Checked = values.FollowActiveController;
            chkRemember.Checked = values.RememberThemePerController;
            swatch.BackColor = values.Background;
            numPort.ValueChanged += (s, e) => UpdateUrl();
            chkOverlay.CheckedChanged += (s, e) => { numPort.Enabled = numFps.Enabled = chkOverlay.Checked; UpdateUrl(); };
            numPort.Enabled = numFps.Enabled = chkOverlay.Checked;
            UpdateUrl();

            refresh.Tick += (s, e) => lblStatus.Text = statusText();
            lblStatus.Text = statusText();
            refresh.Start();
        }

        private void UpdateUrl() => txtUrl.Text = chkOverlay.Checked ? $"http://127.0.0.1:{numPort.Value}/" : "(server off)";

        private void Save()
        {
            Values.OverlayEnabled = chkOverlay.Checked;
            Values.OverlayPort = (int)numPort.Value;
            Values.OverlayFps = (int)numFps.Value;
            Values.AutoSelectOnlyController = chkAuto.Checked;
            Values.FollowActiveController = chkFollow.Checked;
            Values.RememberThemePerController = chkRemember.Checked;
            Values.Background = swatch.BackColor;
        }

        private static GroupBox Group(string title) =>
            new GroupBox { Text = title, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Padding = new Padding(10), MinimumSize = new Size(490, 0) };

        private static FlowLayoutPanel Stack() =>
            new FlowLayoutPanel { FlowDirection = FlowDirection.TopDown, AutoSize = true, WrapContents = false, Dock = DockStyle.Fill };

        private static FlowLayoutPanel Row(params Control[] items)
        {
            var p = new FlowLayoutPanel { FlowDirection = FlowDirection.LeftToRight, AutoSize = true, WrapContents = false, Margin = new Padding(0, 4, 0, 4) };
            p.Controls.AddRange(items);
            return p;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) refresh.Dispose();
            base.Dispose(disposing);
        }
    }
}
