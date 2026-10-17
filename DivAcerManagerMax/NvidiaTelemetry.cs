// SPDX-License-Identifier: GPL-3.0-only
// Modified October 2026; see NOTICE.md for upstream credits.
using System;
using System.Globalization;

namespace DivAcerManagerMax;

internal record NvidiaTelemetry(double? Temperature, double? Usage, double? MemoryUsed, double? MemoryTotal, double? Watts)
{
    internal static NvidiaTelemetry Parse(string csv)
    {
        var parts = csv.Split('\n')[0].Split(',');
        if (parts.Length != 7) return new(null, null, null, null, null);
        static double? Number(string text) => double.TryParse(text.Trim(), NumberStyles.Float,
            CultureInfo.InvariantCulture, out var n) && double.IsFinite(n) && n >= 0 ? n : null;
        var maximum = Number(parts[6]);
        double? Power(string text)
        {
            var value = Number(text);
            // Some laptop drivers emit a bogus instantaneous sample on wake.
            // Allow brief transients, but reject readings far beyond the board's maximum.
            return maximum > 0 && value > maximum * 1.25 ? null : value;
        }
        return new(Number(parts[0]), Number(parts[1]), Number(parts[2]), Number(parts[3]),
            Power(parts[4]) ?? Power(parts[5]));
    }
}
