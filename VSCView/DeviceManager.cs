using ExtendInput.Controller;
using ExtendInput.DeviceProvider;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace VSCView
{
    public class DeviceManager
    {
        private ExtendInput.DeviceManager deviceManager;
        private Input.SdlGamepadManager sdlManager;
        public string SdlStatus => sdlManager?.Status;

        public event ControllerChangeEventHandler ControllerAdded;
        public event DeviceChangeEventHandler ControllerRemoved;

        public DeviceManager()
        {
            deviceManager = new ExtendInput.DeviceManager();
            deviceManager.ControllerAdded += OnControllerAdded;
            deviceManager.ControllerRemoved += OnControllerRemoved;

            // 2026 Steam Controller via SDL3 (the 2015 controller stays on ExtendInput's HID path)
            sdlManager = new Input.SdlGamepadManager();
            sdlManager.ControllerAdded += OnControllerAdded;
            sdlManager.ControllerRemoved += OnControllerRemoved;
        }

        private void OnControllerAdded(object sender, IController e)
        {
            ControllerChangeEventHandler threadSafeEventHandler = ControllerAdded;
            threadSafeEventHandler?.Invoke(this, e);
        }

        private void OnControllerRemoved(object sender, ExtendInput.DeviceProvider.IDevice e)
        {
            DeviceChangeEventHandler threadSafeEventHandler = ControllerRemoved;
            threadSafeEventHandler?.Invoke(this, e);
        }

        public void ScanNow()
        {
            deviceManager.ScanNow();
            sdlManager.Start(); // no-op once running; SDL rescans on its own thread
        }

        public void Shutdown()
        {
            sdlManager?.Dispose();
        }

        public List<IDeviceProvider> GetManualDeviceProviders()
        {
            return deviceManager.GetManualDeviceProviders();
        }
    }

    public delegate void ControllerChangeEventHandler(object sender, IController e);
    public delegate void DeviceChangeEventHandler(object sender, ExtendInput.DeviceProvider.IDevice e);
}
