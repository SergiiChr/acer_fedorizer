// SPDX-License-Identifier: GPL-3.0-only
// Native PH16-72 edition; modified October 2026. See NOTICE.md.
using System;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Threading;

namespace DivAcerManagerMax;

public partial class BatteryMonitor : UserControl
{
    private readonly string? _path;
    private readonly DispatcherTimer _timer;
    private bool _pending;
    public bool HasBattery => _path != null;

    public BatteryMonitor()
    {
        InitializeComponent();
        try
        {
            _path = Directory.EnumerateDirectories("/sys/class/power_supply")
                .FirstOrDefault(p => Read(Path.Combine(p, "type")) == "Battery");
        }
        catch (IOException) { }
        _timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
        _timer.Tick += (_, _) => Refresh();
        AttachedToVisualTree += (_, _) => { _timer.Start(); Refresh(); };
        DetachedFromVisualTree += (_, _) => _timer.Stop();
    }

    private static string Read(string path)
    {
        try { return File.ReadAllText(path).Trim(); }
        catch (IOException) { return ""; }
        catch (UnauthorizedAccessException) { return ""; }
    }

    private double? Number(string field) => _path != null &&
        double.TryParse(Read(Path.Combine(_path, field)), NumberStyles.Float, CultureInfo.InvariantCulture, out var n) &&
        double.IsFinite(n) && n >= 0 ? n : null;

    private async void Refresh()
    {
        if (_pending) return;
        _pending = true;
        try
        {
            var sample = await Task.Run(() =>
            {
                var percent = Number("capacity");
                var status = _path == null ? "No battery detected" : Read(Path.Combine(_path, "status"));
                var time = status == "Full" ? "Fully charged" : status == "Not charging" ? "Not charging" : "Unavailable";
                // Keep energy/power and charge/current pairs together: both yield hours.
                var energy = Number("energy_now");
                var now = energy ?? Number("charge_now");
                var full = Number(energy.HasValue ? "energy_full" : "charge_full");
                var rate = Number(energy.HasValue ? "power_now" : "current_now");
                var hours = rate > 0 && now.HasValue ?
                    status == "Discharging" ? now / rate : status == "Charging" && full.HasValue ? (full - now) / rate : null : null;
                if (hours > 0 && hours < 100)
                {
                    var duration = TimeSpan.FromHours(hours.Value);
                    time = $"{(int)duration.TotalHours}h {duration.Minutes:00}m " +
                           (status == "Charging" ? "to full" : "remaining");
                }
                return (percent, status, time);
            });
            ChargePercentage.Text = sample.percent is >= 0 and <= 100 ? $"{sample.percent:F0}%" : "N/A";
            ChargeBar.Value = sample.percent is >= 0 and <= 100 ? sample.percent.Value : 0;
            ChargeStatus.Text = string.IsNullOrEmpty(sample.status) ? "Unavailable" : sample.status;
            ChargeTime.Text = sample.time;
        }
        finally { _pending = false; }
    }
}
