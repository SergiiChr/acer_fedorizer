// SPDX-License-Identifier: GPL-3.0-only
// Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
using System.Text.Json;

namespace DivAcerManagerMax;

// Editing one device must not change another device's draft or last applied state.
public sealed record LightingDraft(int Mode = 0, string Color = "#FF2300", int Brightness = 100,
    int Speed = 5, int Direction = 1, bool LinkWasd = true)
{
    public static LightingDraft FromState(JsonElement state)
    {
        if (state.ValueKind != JsonValueKind.Object) return new();
        int Number(string key, int fallback, int min, int max) =>
            state.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number) && number >= min && number <= max ? number : fallback;
        var color = state.TryGetProperty("color", out var rgb) && rgb.ValueKind == JsonValueKind.String ? "#" + rgb.GetString() : "#FF2300";
        var link = !state.TryGetProperty("link_wasd", out var linked) || linked.ValueKind != JsonValueKind.False;
        return new(Number("mode", 0, 0, 9), color, Number("brightness", 100, 0, 100),
            Number("speed", 5, 1, 9), Number("direction", 1, 1, 2), link);
    }
}
