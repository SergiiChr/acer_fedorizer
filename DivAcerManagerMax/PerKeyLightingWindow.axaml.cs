// SPDX-License-Identifier: GPL-3.0-only
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Media;

namespace DivAcerManagerMax;

public partial class PerKeyLightingWindow : Window
{
    private readonly DAMXClient _client;
    private readonly DAMXSettings _settings;
    private readonly Dictionary<int, string> _colors = new();
    private readonly Dictionary<int, Button> _keys = new();
    private readonly HashSet<int> _selected = new();
    private bool _pending;
    public bool Applied { get; private set; }

    public PerKeyLightingWindow(DAMXClient client, DAMXSettings settings)
    {
        InitializeComponent();
        _client = client; _settings = settings;
        Opened += async (_, _) => await LoadLayout();
        PaintColor.PropertyChanged += (_, e) => {
            if (e.Property == ColorView.ColorProperty)
                PaintHex.Text = $"#{PaintColor.Color.R:X2}{PaintColor.Color.G:X2}{PaintColor.Color.B:X2}";
        };
    }

    private async System.Threading.Tasks.Task LoadLayout()
    {
        try
        {
            using var response = await _client.SendCommandAsync("get_keyboard_layout");
            var layout = JsonSerializer.Deserialize<KeyboardLayout>(response.RootElement.GetProperty("data"))!;
            var defaults = LightingDraft.FromState(_settings.LightingState.TryGetValue("keyboard", out var state) ? state : default);
            KeyBrightness.Value = defaults.Brightness;
            JsonElement saved = default;
            if (_settings.LightingState.TryGetValue("per_key", out var custom) && custom.ValueKind == JsonValueKind.Object)
            {
                if (custom.TryGetProperty("colors", out var map)) saved = map;
                if (custom.TryGetProperty("brightness", out var brightness) && brightness.TryGetInt32(out var value)) KeyBrightness.Value = Math.Clamp(value, 0, 100);
            }
            foreach (var lamp in layout.Lamps.Where(l => l.Programmable))
            {
                var rgb = defaults.Color;
                if (saved.ValueKind == JsonValueKind.Object && saved.TryGetProperty(lamp.Id.ToString(), out var color) && color.ValueKind == JsonValueKind.String)
                    rgb = "#" + color.GetString();
                if (!Color.TryParse(rgb, out var parsed)) parsed = Color.Parse("#FF2300");
                _colors[lamp.Id] = $"{parsed.R:X2}{parsed.G:X2}{parsed.B:X2}";
                var key = new Button { Content = KeyLabel(lamp.KeyUsage, lamp.Id), Width = 42, Height = 35,
                    FontSize = 11, Padding = new Avalonia.Thickness(1), Margin = new Avalonia.Thickness(0), Tag = lamp.Id,
                    HorizontalContentAlignment = Avalonia.Layout.HorizontalAlignment.Center };
                // Positions are supplied by HID, including the numeric keypad.
                Canvas.SetLeft(key, Math.Clamp(lamp.X * 1000 / Math.Max(layout.Width, 1) - 21, 0, 958));
                Canvas.SetTop(key, Math.Clamp(lamp.Y * 320 / Math.Max(layout.Height, 1) - 17, 0, 285));
                ToolTip.SetTip(key, $"{KeyLabel(lamp.KeyUsage, lamp.Id)} · LED {lamp.Id}");
                key.Click += Key_Click;
                KeyboardCanvas.Children.Add(key); _keys[lamp.Id] = key;
                RefreshKey(lamp.Id);
            }
            ApplyKeys.IsEnabled = _keys.Count > 0;
            UpdateSelection();
        }
        catch (Exception e) { KeyResult.Text = "Could not read keyboard layout: " + e.Message; }
    }

    private void Key_Click(object? sender, RoutedEventArgs e)
    {
        if (_pending || sender is not Button { Tag: int id }) return;
        if (!_selected.Add(id)) _selected.Remove(id);
        RefreshKey(id); UpdateSelection();
    }
    private void RefreshKey(int id)
    {
        var color = Color.Parse("#" + _colors[id]);
        var key = _keys[id]; key.Background = new SolidColorBrush(color);
        key.Foreground = new SolidColorBrush(0.299 * color.R + 0.587 * color.G + 0.114 * color.B > 145 ? Colors.Black : Colors.White);
        key.BorderBrush = _selected.Contains(id) ? Brushes.White : new SolidColorBrush(Color.Parse("#505055"));
        key.BorderThickness = new Avalonia.Thickness(_selected.Contains(id) ? 3 : 1);
    }
    private void UpdateSelection()
    {
        SelectionInfo.Text = $"{_selected.Count} selected · {_keys.Count} programmable keys";
        PaintSelection.IsEnabled = _selected.Count > 0 && !_pending;
    }
    private void SelectAll_Click(object? sender, RoutedEventArgs e)
    { if (_pending) return; foreach (var id in _keys.Keys) { _selected.Add(id); RefreshKey(id); } UpdateSelection(); }
    private void ClearSelection_Click(object? sender, RoutedEventArgs e)
    { if (_pending) return; _selected.Clear(); foreach (var id in _keys.Keys) RefreshKey(id); UpdateSelection(); }
    private void Paint_Click(object? sender, RoutedEventArgs e)
    {
        if (_pending) return;
        var hex = PaintHex.Text?.Trim().TrimStart('#');
        if (hex == null || !System.Text.RegularExpressions.Regex.IsMatch(hex, "^[0-9a-fA-F]{6}$"))
        { KeyResult.Text = "Enter a color as #RRGGBB."; return; }
        foreach (var id in _selected) { _colors[id] = hex.ToUpperInvariant(); RefreshKey(id); }
        KeyResult.Text = "Preview updated. Apply sends these colors to the keyboard.";
    }
    private async void Apply_Click(object? sender, RoutedEventArgs e)
    {
        if (_pending) return;
        _pending = true; ApplyKeys.IsEnabled = false; KeyBrightness.IsEnabled = PaintColor.IsEnabled = PaintHex.IsEnabled = false;
        KeyResult.Text = "Applying per-key colors…";
        try
        {
            using var response = await _client.SendCommandAsync("set_per_key", new() {
                ["colors"] = _colors.ToDictionary(p => p.Key.ToString(), p => p.Value),
                ["brightness"] = (int)(KeyBrightness.Value ?? 100) });
            Applied = true; KeyResult.Text = $"Applied {_keys.Count} per-key colors.";
        }
        catch (Exception error) { KeyResult.Text = "Could not apply: " + error.Message; }
        finally { _pending = false; ApplyKeys.IsEnabled = true; KeyBrightness.IsEnabled = PaintColor.IsEnabled = PaintHex.IsEnabled = true; UpdateSelection(); }
    }

    public static string KeyLabel(int usage, int id) => usage switch
    {
        >= 4 and <= 29 => ((char)('A' + usage - 4)).ToString(),
        >= 30 and <= 38 => (usage - 29).ToString(), 39 => "0",
        >= 58 and <= 69 => "F" + (usage - 57),
        >= 104 and <= 115 => "F" + (usage - 91), 101 => "Menu",
        >= 89 and <= 97 => "N" + (usage - 88),
        40 => "Enter", 41 => "Esc", 42 => "Back", 43 => "Tab", 44 => "Space", 45 => "-", 46 => "=",
        47 => "[", 48 => "]", 49 => "\\", 51 => ";", 52 => "'", 53 => "`", 54 => ",", 55 => ".", 56 => "/",
        57 => "Caps", 70 => "PrtSc", 71 => "Scroll", 72 => "Pause", 73 => "Ins", 74 => "Home", 75 => "PgUp",
        76 => "Del", 77 => "End", 78 => "PgDn", 79 => "→", 80 => "←", 81 => "↓", 82 => "↑",
        83 => "Num", 84 => "N/", 85 => "N*", 86 => "N-", 87 => "N+", 88 => "N↵", 98 => "N0", 99 => "N.",
        224 or 228 => "Ctrl", 225 or 229 => "Shift", 226 or 230 => "Alt", 227 or 231 => "Super",
        _ => "#" + id
    };
}

public sealed class KeyboardLayout
{
    [JsonPropertyName("width")] public double Width { get; set; }
    [JsonPropertyName("height")] public double Height { get; set; }
    [JsonPropertyName("lamps")] public List<KeyboardLamp> Lamps { get; set; } = new();
}
public sealed class KeyboardLamp
{
    [JsonPropertyName("id")] public int Id { get; set; }
    [JsonPropertyName("x")] public double X { get; set; }
    [JsonPropertyName("y")] public double Y { get; set; }
    [JsonPropertyName("programmable")] public bool Programmable { get; set; }
    [JsonPropertyName("key_usage")] public int KeyUsage { get; set; }
}
