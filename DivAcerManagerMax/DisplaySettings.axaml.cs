// SPDX-License-Identifier: GPL-3.0-only
using System;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Threading;

namespace DivAcerManagerMax;

public partial class DisplaySettings : UserControl
{
    private bool _updating;
    private bool _busy;
    private string _connector = "";
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(5) };

    public DisplaySettings()
    {
        InitializeComponent();
        Loaded += async (_, _) => { await RefreshAsync(); _timer.Start(); };
        Unloaded += (_, _) => _timer.Stop();
        _timer.Tick += async (_, _) => { if (IsEffectivelyVisible) await RefreshAsync(); };
    }

    private async Task<JsonDocument> CallAsync(string action)
    {
        // Use the system interpreter: GNOME distributions install GI for this Python.
        var start = new ProcessStartInfo("/usr/bin/python3")
        {
            UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true,
            CreateNoWindow = true
        };
        start.ArgumentList.Add(Path.Combine(AppContext.BaseDirectory, "display_config.py"));
        start.ArgumentList.Add(action);
        if (action != "status") start.ArgumentList.Add(_connector);
        using var process = Process.Start(start) ?? throw new IOException("Could not start display controls.");
        var output = process.StandardOutput.ReadToEndAsync();
        var error = process.StandardError.ReadToEndAsync();
        try { await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(20)); }
        catch (TimeoutException)
        {
            process.Kill(entireProcessTree: true);
            throw new IOException("Display controls timed out. Refresh to check the current mode.");
        }
        var json = await output;
        var stderr = await error;
        if (string.IsNullOrWhiteSpace(json))
            throw new IOException("Display controls are unavailable. " + stderr.Trim());
        var result = JsonDocument.Parse(json);
        if (process.ExitCode != 0)
        {
            var message = result.RootElement.GetProperty("message").GetString();
            result.Dispose();
            throw new IOException(message);
        }
        return result;
    }

    private void ShowState(JsonElement state)
    {
        _updating = true;
        try
        {
            _connector = state.GetProperty("connector").GetString() ?? "";
            NativeSdrToggle.IsChecked = state.GetProperty("enabled").GetBoolean();
            NativeSdrToggle.IsEnabled = state.GetProperty("available").GetBoolean();
            DisplayStatus.Text = state.GetProperty("message").GetString();
        }
        finally { _updating = false; }
    }

    private async Task RefreshAsync()
    {
        if (_busy) return;
        _busy = true;
        RefreshDisplayButton.IsEnabled = false;
        NativeSdrToggle.IsEnabled = false;
        try
        {
            using var result = await CallAsync("status");
            ShowState(result.RootElement);
        }
        catch (Exception ex) { DisplayStatus.Text = ex.Message; }
        finally { _busy = false; RefreshDisplayButton.IsEnabled = true; }
    }

    private async void RefreshClicked(object? sender, RoutedEventArgs e) => await RefreshAsync();

    private async void NativeSdrChanged(object? sender, RoutedEventArgs e)
    {
        if (_updating || _busy || !NativeSdrToggle.IsEnabled) return;
        _busy = true;
        NativeSdrToggle.IsEnabled = false;
        RefreshDisplayButton.IsEnabled = false;
        DisplayStatus.Text = "Applying and saving display configuration…";
        try
        {
            using var result = await CallAsync(NativeSdrToggle.IsChecked == true ? "enable" : "disable");
            ShowState(result.RootElement);
        }
        catch (Exception ex)
        {
            // Re-read reality after rejection, hotplug, or a stale configuration serial.
            try { using var current = await CallAsync("status"); ShowState(current.RootElement); }
            catch { NativeSdrToggle.IsEnabled = false; }
            DisplayStatus.Text = "Could not apply: " + ex.Message;
        }
        finally { _busy = false; RefreshDisplayButton.IsEnabled = true; }
    }
}
