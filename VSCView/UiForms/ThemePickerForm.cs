using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace VSCView.UiForms
{
    /// <summary>
    /// Browse all themes with a live preview (rendered by the real theme engine on a checkerboard so
    /// transparency is visible), then apply one to the window or copy a pinned OBS URL for it.
    /// </summary>
    public sealed class ThemePickerForm : Form
    {
        private readonly TreeView tree = new TreeView();
        private readonly PictureBox preview = new PictureBox();
        private readonly Label info = new Label();
        private readonly Button btnUse = new Button();
        private readonly Button btnCopy = new Button();
        private readonly Button btnClose = new Button();
        private readonly TextBox search = new TextBox();
        private readonly Dictionary<string, Image> previewCache = new Dictionary<string, Image>(StringComparer.OrdinalIgnoreCase);
        private readonly Action<string> apply;
        private readonly Func<string, string> pinnedUrl;
        private readonly List<ThemeEntry> entries;
        private readonly string current;

        public ThemePickerForm(string currentThemeFile, Action<string> apply, Func<string, string> pinnedUrl)
        {
            this.apply = apply;
            this.pinnedUrl = pinnedUrl;
            current = currentThemeFile;
            entries = ThemeCatalog.Load();

            Text = "Themes";
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(980, 600);
            MinimumSize = new Size(640, 400);
            Font = SystemFonts.MessageBoxFont;
            ShowInTaskbar = true;

            var split = new SplitContainer { Dock = DockStyle.Fill, SplitterDistance = 330, FixedPanel = FixedPanel.Panel1 };

            search.Dock = DockStyle.Top;
            search.Margin = new Padding(6);
            SetCue(search, "Filter themes…");
            search.TextChanged += (s, e) => Populate();
            tree.Dock = DockStyle.Fill;
            tree.HideSelection = false;
            tree.AfterSelect += (s, e) => ShowSelection();
            tree.NodeMouseDoubleClick += (s, e) => { if (e.Node.Tag is ThemeEntry) UseSelected(); };
            split.Panel1.Controls.Add(tree);
            split.Panel1.Controls.Add(search);
            split.Panel1.Padding = new Padding(6);

            preview.Dock = DockStyle.Fill;
            preview.SizeMode = PictureBoxSizeMode.Zoom;
            preview.BackgroundImage = Checkerboard();
            preview.BackgroundImageLayout = ImageLayout.Tile;

            info.Dock = DockStyle.Fill;
            info.TextAlign = ContentAlignment.MiddleLeft;
            info.AutoEllipsis = true;

            btnUse.Text = "Use in window";
            btnUse.AutoSize = true;
            btnUse.Click += (s, e) => UseSelected();
            btnCopy.Text = "Copy OBS URL for this theme";
            btnCopy.AutoSize = true;
            btnCopy.Click += (s, e) =>
            {
                if (tree.SelectedNode?.Tag is ThemeEntry t)
                {
                    try { Clipboard.SetText(pinnedUrl(t.File)); info.Text = "Copied: " + pinnedUrl(t.File); } catch { }
                }
            };
            btnClose.Text = "Close";
            btnClose.AutoSize = true;
            btnClose.DialogResult = DialogResult.Cancel;
            CancelButton = btnClose;
            AcceptButton = btnUse;

            var buttons = new FlowLayoutPanel { Dock = DockStyle.Right, AutoSize = true, FlowDirection = FlowDirection.LeftToRight, WrapContents = false };
            buttons.Controls.AddRange(new Control[] { btnCopy, btnUse, btnClose });
            var bottom = new Panel { Dock = DockStyle.Bottom, Height = 44, Padding = new Padding(8, 6, 8, 6) };
            bottom.Controls.Add(info);
            bottom.Controls.Add(buttons);

            split.Panel2.Controls.Add(preview);
            split.Panel2.Controls.Add(bottom);
            Controls.Add(split);

            Populate();
        }

        private void Populate()
        {
            string filter = search.Text.Trim();
            tree.BeginUpdate();
            tree.Nodes.Clear();
            TreeNode select = null;
            foreach (var fam in entries.Where(e => filter.Length == 0 || e.ToString().IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0)
                                       .GroupBy(e => e.Family))
            {
                var famNode = tree.Nodes.Add(fam.Key);
                foreach (var th in fam.GroupBy(e => e.Theme))
                {
                    var thNode = famNode.Nodes.Add(th.Key);
                    foreach (var v in th)
                    {
                        var n = thNode.Nodes.Add(v.Variant);
                        n.Tag = v;
                        if (current != null && Path.GetFullPath(v.File).Equals(Path.GetFullPath(current), StringComparison.OrdinalIgnoreCase))
                        {
                            n.NodeFont = new Font(tree.Font, FontStyle.Bold);
                            n.Text = v.Variant + "  (current)";
                            select = n;
                        }
                    }
                }
                if (filter.Length > 0) famNode.ExpandAll();
            }
            tree.EndUpdate();
            if (select != null) { select.EnsureVisible(); tree.SelectedNode = select; }
            ShowSelection();
        }

        private void ShowSelection()
        {
            var t = tree.SelectedNode?.Tag as ThemeEntry;
            btnUse.Enabled = btnCopy.Enabled = t != null;
            if (t == null)
            {
                preview.Image = null;
                info.Text = entries.Count + " theme layouts. Pick one to preview.";
                return;
            }
            preview.Image = GetPreview(t.File);
            string size = preview.Image != null ? $"{preview.Image.Width}×{preview.Image.Height}" : "preview failed";
            info.Text = $"{t.Theme} – {t.Variant}  ·  {size}" + (t.Author != null ? $"  ·  by {t.Author}" : "");
        }

        private Image GetPreview(string file)
        {
            if (previewCache.TryGetValue(file, out var img)) return img;
            try
            {
                using (UI ui = Web.OverlayHub.LoadUi(file, new ControllerData()))
                {
                    var bmp = new Bitmap(Math.Max(1, ui.Width), Math.Max(1, ui.Height));
                    using (var g = Graphics.FromImage(bmp))
                    {
                        g.Clear(Color.Transparent);
                        ui.Paint(g);
                    }
                    img = bmp;
                }
            }
            catch { img = null; }
            previewCache[file] = img;
            return img;
        }

        private void UseSelected()
        {
            if (tree.SelectedNode?.Tag is ThemeEntry t)
            {
                apply(t.File);
                Close();
            }
        }

        private static Image Checkerboard()
        {
            var bmp = new Bitmap(24, 24);
            using (var g = Graphics.FromImage(bmp))
            using (var a = new SolidBrush(Color.FromArgb(58, 58, 64)))
            using (var b = new SolidBrush(Color.FromArgb(44, 44, 50)))
            {
                g.FillRectangle(a, 0, 0, 24, 24);
                g.FillRectangle(b, 0, 0, 12, 12);
                g.FillRectangle(b, 12, 12, 12, 12);
            }
            return bmp;
        }

        [System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
        private static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, string lParam);
        private static void SetCue(TextBox box, string cue)
        {
            box.HandleCreated += (s, e) => SendMessage(box.Handle, 0x1501 /*EM_SETCUEBANNER*/, (IntPtr)1, cue);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                foreach (var i in previewCache.Values) i?.Dispose();
                previewCache.Clear();
            }
            base.Dispose(disposing);
        }
    }
}
