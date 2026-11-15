using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace VSCView
{
    public class Settings
    {
        public string Theme { get; set; }
        public string Background { get; set; }
        public int PreviousPid { get; set; }
        public bool CustomSize { get; set; }
        public int? Width { get; set; }
        public int? Height { get; set; }
        public bool AutoSelectOnlyController { get; set; }



        public bool HackScMotionOn { get; set; }

        // OBS Browser Source (local overlay server on 127.0.0.1)
        public bool? OverlayEnabled { get; set; }
        public int? OverlayPort { get; set; }
        public int? OverlayFps { get; set; }

        // Controller handling
        public bool? FollowActiveController { get; set; }
        public bool? RememberThemePerController { get; set; }
        public Dictionary<string, string> ThemeByController { get; set; }

        // Control panel
        public string PanelKey { get; set; }          // per-install key for the panel API (local only)
        public bool? OpenPanelOnStart { get; set; }
        public bool? ShowPreviewWindow { get; set; }  // the classic borderless window
        public bool? SetupDone { get; set; }
        public string Accent { get; set; }            // "#rrggbb", null = default cyan
    }
}
