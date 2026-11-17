using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace VSCView.UiForms
{
    /// <summary>One selectable theme layout file (e.g. themes/steamcontroller2026/graphite/Full.json).</summary>
    public sealed class ThemeEntry
    {
        public string Family { get; set; }    // e.g. "Valve Steam Controller (2026)"
        public string Theme { get; set; }     // e.g. "Graphite"
        public string Variant { get; set; }   // e.g. "Full"
        public string File { get; set; }      // relative path, as used by the window
        public string Author { get; set; }

        public override string ToString() => $"{Family} / {Theme} / {Variant}";
    }

    /// <summary>Enumerates themes the same way the window's Theme menu does.</summary>
    public static class ThemeCatalog
    {
        public static List<ThemeEntry> Load(string themesDir = "themes")
        {
            var list = new List<ThemeEntry>();
            if (!Directory.Exists(themesDir)) return list;

            foreach (string meta in Directory.EnumerateFiles(themesDir, "theme.json", SearchOption.AllDirectories))
            {
                string dir = Path.GetDirectoryName(meta);
                string[] parts = dir.Split(new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar }, StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length < 2) continue;

                string familyDir = Path.Combine(parts[0], parts[1]);
                string family = ReadName(Path.Combine(familyDir, "name.txt")) ?? parts[1];

                string theme = Path.GetFileName(dir);
                string author = null;
                try
                {
                    var desc = JsonConvert.DeserializeObject<ThemeDesc>(File.ReadAllText(meta));
                    if (!string.IsNullOrWhiteSpace(desc?.name)) theme = desc.name;
                    author = desc?.authors?.FirstOrDefault()?.name;
                }
                catch { }
                // Prefix intermediate folders ("default / Black") so similarly named themes stay distinguishable.
                if (parts.Length > 3)
                {
                    var middle = new List<string>();
                    for (int i = 2; i < parts.Length - 1; i++)
                    {
                        string sub = string.Join(Path.DirectorySeparatorChar.ToString(), parts.Take(i + 1));
                        middle.Add(ReadName(Path.Combine(sub, "name.txt")) ?? parts[i]);
                    }
                    theme = $"{string.Join(" / ", middle)} / {theme}";
                }

                foreach (string file in Directory.EnumerateFiles(dir, "*.json", SearchOption.TopDirectoryOnly))
                {
                    if (Path.GetFileName(file).Equals("theme.json", StringComparison.OrdinalIgnoreCase)) continue;
                    string variant = Path.GetFileNameWithoutExtension(file);
                    try
                    {
                        var sub = JsonConvert.DeserializeObject<ThemeSubDesc>(File.ReadAllText(file));
                        if (!string.IsNullOrWhiteSpace(sub?.name)) variant = sub.name;
                    }
                    catch { }
                    list.Add(new ThemeEntry { Family = family, Theme = theme, Variant = variant, File = file, Author = author });
                }
            }
            return list.OrderBy(e => e.Family, StringComparer.OrdinalIgnoreCase)
                       .ThenBy(e => e.Theme, StringComparer.OrdinalIgnoreCase)
                       .ThenBy(e => e.File, StringComparer.OrdinalIgnoreCase)
                       .ToList();
        }

        private static string ReadName(string path)
        {
            try
            {
                if (File.Exists(path))
                {
                    string s = File.ReadAllText(path).Trim().TrimStart('﻿');
                    return string.IsNullOrWhiteSpace(s) ? null : s;
                }
            }
            catch { }
            return null;
        }
    }
}
