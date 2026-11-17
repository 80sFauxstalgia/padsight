using ExtendInput.Controls;
using System;

namespace VSCView.Input
{
    /// <summary>
    /// Single-finger touch surface with click and pressure, used for the 2026 Steam Controller's trackpads.
    /// Exposes the same Flee keys as <see cref="ControlTouch"/> (<c>click</c>, <c>0:touch</c>, <c>0:x</c>, <c>0:y</c>)
    /// so existing trackpad theme snippets work, plus <c>0:pressure</c> (0.0 to 1.0).
    /// </summary>
    public class ControlTouchPressure : IControl
    {
        public bool Touch { get; set; }
        public float X { get; set; }
        public float Y { get; set; }
        public float Pressure { get; set; }
        public bool Click { get; set; }

        public T Value<T>(string key)
        {
            switch (key)
            {
                case "click": return (T)Convert.ChangeType(Click, typeof(T));
                case "0:touch": return (T)Convert.ChangeType(Touch, typeof(T));
                case "0:x": return (T)Convert.ChangeType(X, typeof(T));
                case "0:y": return (T)Convert.ChangeType(Y, typeof(T));
                case "0:pressure": return (T)Convert.ChangeType(Pressure, typeof(T));
                default: return default;
            }
        }

        public Type Type(string key)
        {
            switch (key)
            {
                case "click":
                case "0:touch":
                    return typeof(bool);
                case "0:x":
                case "0:y":
                case "0:pressure":
                    return typeof(float);
                default:
                    return default;
            }
        }

        public object Clone()
        {
            return new ControlTouchPressure { Touch = Touch, X = X, Y = Y, Pressure = Pressure, Click = Click };
        }
    }
}
