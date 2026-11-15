using ExtendInput.Controller;
using ExtendInput.Controls;
using ExtendInput.DeviceProvider;
using SDL3;
using System;
using System.Collections.Generic;

namespace VSCView.Input
{
    /// <summary>
    /// The 2026 Steam Controller, read through SDL3's native HIDAPI driver
    /// (SDL_hidapi_steam_triton.c, SDL 3.4.10+).
    ///
    /// Control names (see THEMEENGINE.md):
    ///   quad_left, quad_right, bumpers, triggers, menu, home, qam,
    ///   stick_left, stick_right, stick_touch (l/r capacitive),
    ///   touch_left, touch_right (ControlTouchPressure),
    ///   grip (upper back buttons L4/R4), grip2 (lower back buttons L5/R5),
    ///   grip_sense (l/r capacitive grip touch).
    /// </summary>
    public sealed class SdlSteamController : IController
    {
        // Joystick button indices used by SDL's Triton driver. 0-10 are the standard
        // SDL_GamepadButton values; 11+ are driver specific (see SDL_hidapi_steam_triton.c).
        private const int BTN_SOUTH = 0, BTN_EAST = 1, BTN_WEST = 2, BTN_NORTH = 3;
        private const int BTN_BACK = 4, BTN_GUIDE = 5, BTN_START = 6;
        private const int BTN_LSTICK = 7, BTN_RSTICK = 8, BTN_LSHOULDER = 9, BTN_RSHOULDER = 10;
        private const int BTN_QAM = 11;
        private const int BTN_R_PADDLE1 = 12, BTN_L_PADDLE1 = 13, BTN_R_PADDLE2 = 14, BTN_L_PADDLE2 = 15;
        private const int BTN_R_PAD_CLICK = 16, BTN_L_PAD_CLICK = 17;
        private const int BTN_R_STICK_TOUCH = 18, BTN_L_STICK_TOUCH = 19;
        private const int BTN_R_GRIP_TOUCH = 20, BTN_L_GRIP_TOUCH = 21;

        private const byte HAT_UP = 0x01, HAT_RIGHT = 0x02, HAT_DOWN = 0x04, HAT_LEFT = 0x08;

        public const string TypeCode = "DEVICE_SC2026";

        private readonly SdlDevice device;
        private volatile ControllerState state;
        private readonly object stateLock = new object();

        internal IntPtr Gamepad { get; private set; }
        internal uint InstanceId { get; }

        public event ControllerNameUpdateEvent ControllerMetadataUpdate;
        public event ControllerStateUpdateEvent ControllerStateUpdate;

        internal SdlSteamController(IntPtr gamepad, uint instanceId, SdlDevice device, string name)
        {
            Gamepad = gamepad;
            InstanceId = instanceId;
            this.device = device;
            Name = string.IsNullOrWhiteSpace(name) ? "Steam Controller (2026)" : name;
            if (!Name.Contains("2026"))
                Name += " (2026)";
            state = NewState();
            ConnectionType = device.ProductId == 0x1304 || device.ProductId == 0x1305 ? EConnectionType.Dongle : EConnectionType.USB;
        }

        public EConnectionType ConnectionType { get; }
        public string[] ConnectionTypeCode => ConnectionType == EConnectionType.Dongle
            ? new[] { "CONNECTION_DONGLE_SC2026", "CONNECTION_DONGLE" }
            : new[] { "CONNECTION_WIRE_USB", "CONNECTION_WIRE" };
        public string[] ControllerTypeCode => new[] { TypeCode, "DEVICE_SC" };
        public bool HasSelectableAlternatives => false;
        public Dictionary<string, string> Alternates => null;
        public string Name { get; }
        public string[] NameDetails => new[] { "via SDL3" };
        public string UniqueID => device.UniqueKey;
        public IDevice DeviceHackRef => device;
        public bool HasMotion => false;
        public bool IsPresent => Gamepad != IntPtr.Zero;

        public ControllerState GetState() => state;

        // Reading is driven by SdlGamepadManager's thread for as long as the device is attached,
        // so these are no-ops; nothing is written to the controller.
        public void Initalize() { }
        public void DeInitalize() { }
        public void Identify() { }
        public void SetActiveAlternateController(string ControllerID) { }
        public void Dispose() { }

        internal void Detach() => Gamepad = IntPtr.Zero;

        private static ControllerState NewState()
        {
            var s = new ControllerState();
            s.Controls["quad_left"] = new ControlDPad();
            s.Controls["quad_right"] = new ControlButtonQuad();
            s.Controls["bumpers"] = new ControlButtonPair();
            s.Controls["triggers"] = new ControlTriggerPair(HasStage2: false);
            s.Controls["menu"] = new ControlButtonPair();
            s.Controls["home"] = new ControlButton();
            s.Controls["qam"] = new ControlButton();
            s.Controls["stick_left"] = new ControlStick(HasClick: true);
            s.Controls["stick_right"] = new ControlStick(HasClick: true);
            s.Controls["stick_touch"] = new ControlButtonPair();
            s.Controls["touch_left"] = new ControlTouchPressure();
            s.Controls["touch_right"] = new ControlTouchPressure();
            s.Controls["grip"] = new ControlButtonPair();
            s.Controls["grip2"] = new ControlButtonPair();
            s.Controls["grip_sense"] = new ControlButtonPair();
            return s;
        }

        /// <summary>Called on the SDL thread after SDL_UpdateGamepads().</summary>
        internal void Poll()
        {
            IntPtr pad = Gamepad;
            if (pad == IntPtr.Zero) return;
            IntPtr joy = SDL.SDL_GetGamepadJoystick(pad);
            if (joy == IntPtr.Zero) return;

            bool B(int i) => SDL.SDL_GetJoystickButton(joy, i);

            var s = NewState();

            var face = (ControlButtonQuad)s.Controls["quad_right"];
            face.ButtonS = B(BTN_SOUTH);
            face.ButtonE = B(BTN_EAST);
            face.ButtonW = B(BTN_WEST);
            face.ButtonN = B(BTN_NORTH);

            byte hat = SDL.SDL_GetJoystickHat(joy, 0);
            ((ControlDPad)s.Controls["quad_left"]).Direction = HatToDirection(hat);

            Pair(s, "bumpers", B(BTN_LSHOULDER), B(BTN_RSHOULDER));
            Pair(s, "menu", B(BTN_BACK), B(BTN_START));
            ((ControlButton)s.Controls["home"]).Button0 = B(BTN_GUIDE);
            ((ControlButton)s.Controls["qam"]).Button0 = B(BTN_QAM);
            Pair(s, "grip", B(BTN_L_PADDLE1), B(BTN_R_PADDLE1));
            Pair(s, "grip2", B(BTN_L_PADDLE2), B(BTN_R_PADDLE2));
            Pair(s, "stick_touch", B(BTN_L_STICK_TOUCH), B(BTN_R_STICK_TOUCH));
            Pair(s, "grip_sense", B(BTN_L_GRIP_TOUCH), B(BTN_R_GRIP_TOUCH));

            var triggers = (ControlTriggerPair)s.Controls["triggers"];
            triggers.Left.Analog = Trigger(SDL.SDL_GetGamepadAxis(pad, SDL.SDL_GamepadAxis.SDL_GAMEPAD_AXIS_LEFT_TRIGGER));
            triggers.Right.Analog = Trigger(SDL.SDL_GetGamepadAxis(pad, SDL.SDL_GamepadAxis.SDL_GAMEPAD_AXIS_RIGHT_TRIGGER));

            var ls = (ControlStick)s.Controls["stick_left"];
            ls.X = Axis(SDL.SDL_GetGamepadAxis(pad, SDL.SDL_GamepadAxis.SDL_GAMEPAD_AXIS_LEFTX));
            ls.Y = Axis(SDL.SDL_GetGamepadAxis(pad, SDL.SDL_GamepadAxis.SDL_GAMEPAD_AXIS_LEFTY));
            ls.Click = B(BTN_LSTICK);
            var rs = (ControlStick)s.Controls["stick_right"];
            rs.X = Axis(SDL.SDL_GetGamepadAxis(pad, SDL.SDL_GamepadAxis.SDL_GAMEPAD_AXIS_RIGHTX));
            rs.Y = Axis(SDL.SDL_GetGamepadAxis(pad, SDL.SDL_GamepadAxis.SDL_GAMEPAD_AXIS_RIGHTY));
            rs.Click = B(BTN_RSTICK);

            ReadPad(pad, 0, (ControlTouchPressure)s.Controls["touch_left"], B(BTN_L_PAD_CLICK));
            ReadPad(pad, 1, (ControlTouchPressure)s.Controls["touch_right"], B(BTN_R_PAD_CLICK));

            state = s;
            ControllerStateUpdate?.Invoke(this, s);
        }

        private static void ReadPad(IntPtr pad, int index, ControlTouchPressure t, bool click)
        {
            t.Click = click;
            if (SDL.SDL_GetGamepadTouchpadFinger(pad, index, 0, out SDL.SDLBool down, out float x, out float y, out float pressure))
            {
                t.Touch = down;
                // SDL reports 0..1 with y growing downward; themes expect -1..1 centered, y down.
                t.X = Clamp(x * 2f - 1f);
                t.Y = Clamp(y * 2f - 1f);
                t.Pressure = Math.Max(0f, Math.Min(1f, pressure));
            }
        }

        private static void Pair(ControllerState s, string key, bool l, bool r)
        {
            var p = (ControlButtonPair)s.Controls[key];
            p.Left.Button0 = l;
            p.Right.Button0 = r;
        }

        private static EDPadDirection HatToDirection(byte hat)
        {
            bool u = (hat & HAT_UP) != 0, d = (hat & HAT_DOWN) != 0, l = (hat & HAT_LEFT) != 0, r = (hat & HAT_RIGHT) != 0;
            if (u && r) return EDPadDirection.NorthEast;
            if (u && l) return EDPadDirection.NorthWest;
            if (d && r) return EDPadDirection.SouthEast;
            if (d && l) return EDPadDirection.SouthWest;
            if (u) return EDPadDirection.North;
            if (d) return EDPadDirection.South;
            if (l) return EDPadDirection.West;
            if (r) return EDPadDirection.East;
            return EDPadDirection.None;
        }

        private static float Axis(short v) => Clamp(v < 0 ? v / 32768f : v / 32767f);
        private static float Trigger(short v) => Math.Max(0f, Math.Min(1f, v / 32767f));
        private static float Clamp(float v) => Math.Max(-1f, Math.Min(1f, v));
    }

    internal sealed class SdlDevice : IDevice
    {
        public SdlDevice(string path, int vendorId, int productId, string uniqueKey)
        {
            DevicePath = path;
            VendorId = vendorId;
            ProductId = productId;
            UniqueKey = uniqueKey;
        }

        public string DevicePath { get; }
        public int ProductId { get; }
        public int VendorId { get; }
        public string UniqueKey { get; }
        public Dictionary<string, dynamic> Properties { get; } = new Dictionary<string, dynamic>();

        public bool Equals(IDevice other) => other != null && other.UniqueKey == UniqueKey;
        public override bool Equals(object obj) => Equals(obj as IDevice);
        public override int GetHashCode() => UniqueKey.GetHashCode();
    }
}
