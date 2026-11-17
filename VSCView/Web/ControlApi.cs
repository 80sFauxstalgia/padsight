using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;

namespace VSCView.Web
{
    /// <summary>One request to the control panel API (<c>/api/...</c>). Only reaches the app after the key check.</summary>
    public sealed class ApiRequest
    {
        public string Method { get; set; }
        public string Path { get; set; }
        public Dictionary<string, string> Query { get; set; }
        public string Body { get; set; }
    }

    public sealed class ApiResponse
    {
        public int Code { get; set; } = 200;
        public string Json { get; set; } = "{}";

        public static ApiResponse Ok(string json) => new ApiResponse { Json = json };
        public static ApiResponse Error(int code, string message) =>
            new ApiResponse { Code = code, Json = Newtonsoft.Json.JsonConvert.SerializeObject(new { error = message }) };
    }

    /// <summary>
    /// The per-install key that every control-panel API call must carry (header <c>X-Panel-Key</c>).
    /// Any website can send requests to 127.0.0.1, so the key, plus the Origin check in the server, is what
    /// stops another page from driving the app. The key reaches the panel only through the URL fragment the
    /// app opens (fragments are never sent to a server).
    /// </summary>
    public static class PanelKey
    {
        public static string Generate()
        {
            byte[] b = new byte[24];
            using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(b);
            return Convert.ToBase64String(b).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        }

        /// <summary>Constant-time comparison, so the key can't be guessed byte by byte from response timing.</summary>
        public static bool Matches(string expected, string given)
        {
            if (string.IsNullOrEmpty(expected) || given == null) return false;
            byte[] a = Encoding.UTF8.GetBytes(expected), b = Encoding.UTF8.GetBytes(given);
            int diff = a.Length ^ b.Length;
            for (int i = 0; i < Math.Max(a.Length, b.Length); i++)
                diff |= (i < a.Length ? a[i] : 0) ^ (i < b.Length ? b[i] : 0);
            return diff == 0;
        }
    }
}
