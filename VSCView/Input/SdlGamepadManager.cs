using ExtendInput.Controller;
using SDL3;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

namespace VSCView.Input
{
    /// <summary>
    /// Owns SDL3 on a dedicated thread and exposes 2026 Steam Controllers as <see cref="IController"/>s.
    ///
    /// SDL is configured so that it only ever touches the 2026 controller:
    ///  - every HIDAPI driver except Valve's is disabled (no LED/rumble writes to other pads);
    ///  - the 2015 Steam Controller (and Steam Deck) are on SDL's HID ignore list, because VSCView's
    ///    existing ExtendInput HID decoder already reads them with full trackpad data, and SDL's 2015
    ///    driver re-enables lizard mode when it closes the device;
    ///  - the XInput / RawInput / WGI / GameInput / DirectInput backends are off, so Steam's virtual
    ///    Xbox pads are never picked up.
    /// </summary>
    public sealed class SdlGamepadManager : IDisposable
    {
        private const ushort ValveVendorId = 0x28de;

        public event ControllerChangeEventHandler ControllerAdded;
        public event DeviceChangeEventHandler ControllerRemoved;

        public string Status { get; private set; } = "SDL3 not started";

        private Thread thread;
        private volatile bool running;
        private readonly Dictionary<uint, SdlSteamController> open = new Dictionary<uint, SdlSteamController>();

        [DllImport("kernel32", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern IntPtr LoadLibrary(string lpFileName);

        public void Start()
        {
            if (thread != null) return;
            running = true;
            thread = new Thread(Run) { IsBackground = true, Name = "SDL3 gamepads", Priority = ThreadPriority.AboveNormal };
            thread.Start();
        }

        public void Dispose()
        {
            running = false;
            thread?.Join(2000);
            thread = null;
        }

        private void Run()
        {
            bool sdlUp = false;
            try
            {
                // Make sure the SDL3.dll next to the exe is the one that gets loaded.
                string local = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "SDL3.dll");
                if (File.Exists(local)) LoadLibrary(local);

                SDL.SDL_SetHint("SDL_JOYSTICK_HIDAPI", "0");
                SDL.SDL_SetHint("SDL_JOYSTICK_HIDAPI_STEAM", "1");
                SDL.SDL_SetHint("SDL_HIDAPI_IGNORE_DEVICES",
                    "0x28de/0x1101,0x28de/0x1102,0x28de/0x1105,0x28de/0x1106,0x28de/0x1142,0x28de/0x1205");
                SDL.SDL_SetHint("SDL_JOYSTICK_RAWINPUT", "0");
                SDL.SDL_SetHint("SDL_JOYSTICK_WGI", "0");
                SDL.SDL_SetHint("SDL_JOYSTICK_GAMEINPUT", "0");
                SDL.SDL_SetHint("SDL_XINPUT_ENABLED", "0");
                SDL.SDL_SetHint("SDL_JOYSTICK_DIRECTINPUT", "0");
                SDL.SDL_SetHint("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1");

                if (!SDL.SDL_Init(SDL.SDL_InitFlags.SDL_INIT_GAMEPAD))
                {
                    Status = "SDL_Init failed: " + SDL.SDL_GetError();
                    Debug.WriteLine(Status);
                    return;
                }
                sdlUp = true;
                int v = SDL.SDL_GetVersion();
                Status = $"SDL {v / 1000000}.{v / 1000 % 1000}.{v % 1000} ready";
                Debug.WriteLine(Status);

                var scan = Stopwatch.StartNew();
                Rescan();
                while (running)
                {
                    SDL.SDL_UpdateGamepads();

                    if (scan.ElapsedMilliseconds > 500)
                    {
                        Rescan();
                        scan.Restart();
                    }

                    foreach (var c in open.Values)
                        c.Poll();

                    Thread.Sleep(2); // ~500 Hz; renderers sample the latest state
                }
            }
            catch (DllNotFoundException ex)
            {
                Status = "SDL3.dll not found: " + ex.Message;
                Debug.WriteLine(Status);
            }
            catch (EntryPointNotFoundException ex)
            {
                Status = "SDL3.dll is too old: " + ex.Message;
                Debug.WriteLine(Status);
            }
            catch (Exception ex)
            {
                Status = "SDL3 thread failed: " + ex.Message;
                Debug.WriteLine(ex);
            }
            finally
            {
                foreach (var c in open.Values)
                {
                    if (c.Gamepad != IntPtr.Zero) SDL.SDL_CloseGamepad(c.Gamepad);
                    c.Detach();
                }
                open.Clear();
                if (sdlUp) SDL.SDL_Quit();
            }
        }

        private void Rescan()
        {
            var present = new HashSet<uint>();
            IntPtr ids = SDL.SDL_GetGamepads(out int count);
            if (ids != IntPtr.Zero)
            {
                try
                {
                    for (int i = 0; i < count; i++)
                        present.Add((uint)Marshal.ReadInt32(ids, i * sizeof(int)));
                }
                finally { SDL.SDL_free(ids); }
            }

            // removals
            var gone = new List<uint>();
            foreach (var kv in open)
                if (!present.Contains(kv.Key) || !SDL.SDL_GamepadConnected(kv.Value.Gamepad))
                    gone.Add(kv.Key);
            foreach (uint id in gone)
            {
                var c = open[id];
                open.Remove(id);
                if (c.Gamepad != IntPtr.Zero) SDL.SDL_CloseGamepad(c.Gamepad);
                c.Detach();
                Debug.WriteLine($"SDL3: removed {c.Name}");
                ControllerRemoved?.Invoke(this, c.DeviceHackRef);
            }

            // additions
            foreach (uint id in present)
            {
                if (open.ContainsKey(id)) continue;
                IntPtr pad = SDL.SDL_OpenGamepad(id);
                if (pad == IntPtr.Zero) continue;

                ushort vid = SDL.SDL_GetGamepadVendor(pad);
                ushort pid = SDL.SDL_GetGamepadProduct(pad);
                IntPtr joy = SDL.SDL_GetGamepadJoystick(pad);
                int buttons = joy != IntPtr.Zero ? SDL.SDL_GetNumJoystickButtons(joy) : 0;

                // Only the 2026 controller's driver reports 22 buttons and two touchpads under Valve's VID.
                if (vid != ValveVendorId || buttons < 22 || SDL.SDL_GetNumGamepadTouchpads(pad) < 2)
                {
                    SDL.SDL_CloseGamepad(pad);
                    continue;
                }

                string name = SDL.SDL_GetGamepadName(pad);
                string path = SDL.SDL_GetGamepadPath(pad) ?? $"sdl:{id}";
                string serial = SDL.SDL_GetGamepadSerial(pad);
                string key = "SDL3:" + (string.IsNullOrEmpty(serial) ? path : serial);
                var ctrl = new SdlSteamController(pad, id, new SdlDevice(path, vid, pid, key), name);
                open[id] = ctrl;
                Debug.WriteLine($"SDL3: added {ctrl.Name} {vid:x4}:{pid:x4} {path}");
                ControllerAdded?.Invoke(this, ctrl);
            }
        }
    }
}
