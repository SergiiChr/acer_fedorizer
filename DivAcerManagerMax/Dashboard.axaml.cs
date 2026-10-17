// SPDX-License-Identifier: GPL-3.0-only
// Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Globalization;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Avalonia.Animation;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Styling;
using Avalonia.Threading;
using LiveChartsCore;
using LiveChartsCore.SkiaSharpView;
using LiveChartsCore.SkiaSharpView.Avalonia;
using LiveChartsCore.SkiaSharpView.Painting;
using Material.Icons.Avalonia;
using SkiaSharp;

namespace DivAcerManagerMax;

public partial class Dashboard : UserControl, INotifyPropertyChanged
{
    private const int REFRESH_INTERVAL_MS = 2000; // 2 seconds
    private const int MAX_HISTORY_POINTS = 60; // Two minutes at a 2-second refresh

    // Timer to refresh dynamic system metrics
    private readonly DispatcherTimer _refreshTimer;
    private bool _samplePending;
    private bool _monitorGpu;
    private readonly ColumnSeries<double> _frequencySeries = new() { Name = "GHz", Values = Array.Empty<double>() };
    private double? _vramUsed;
    private double? _vramTotal;
    private double? _gpuWatts;

    // Cache for system info paths
    private readonly Dictionary<string, string> _systemInfoPaths = new();

    private string _cpuName;
    private double _cpuTemp;
    private ObservableCollection<double> _cpuTempHistory;
    private double _cpuUsage;

    private string _gpuName;
    private double _gpuTemp;
    private ObservableCollection<double?> _gpuTempHistory;
    private GpuType _gpuType = GpuType.Unknown;
    private double _gpuUsage;
    private string _kernelVersion;
    private string _osVersion;
    private string _ramTotal;
    private double _ramUsage;
    private CartesianChart _temperatureChart;
    private ObservableCollection<ISeries> _tempSeries;

    public Dashboard()
    {
        InitializeComponent();
        DataContext = this;

        // Fetch static system information once at initialization
        InitializeStaticSystemInfo();

        // Setup refresh timer for dynamic metrics
        _refreshTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromMilliseconds(REFRESH_INTERVAL_MS)
        };
        _refreshTimer.Tick += RefreshDynamicMetrics;
        AttachedToVisualTree += (_, _) => _refreshTimer.Start();
        DetachedFromVisualTree += (_, _) => _refreshTimer.Stop();
        InitializeExtraCharts();

        // Initial refresh of dynamic metrics
        RefreshDynamicMetricsAsync();
    }

    private bool GpuReadingsAvailable => _gpuType != GpuType.Nvidia || (_monitorGpu && _vramUsed.HasValue);
    public string GpuTemperatureDisplay => GpuReadingsAvailable ? $"{GpuTemp:F0}°C" : _monitorGpu ? "N/A" : "Paused";
    public string GpuUsageDisplay => GpuReadingsAvailable ? $"{GpuUsage:F0}%" : _monitorGpu ? "N/A" : "Paused";

    public string CpuName
    {
        get => _cpuName;
        set => SetProperty(ref _cpuName, value);
    }

    public string GpuName
    {
        get => _gpuName;
        set => SetProperty(ref _gpuName, value);
    }

    public string OsVersion
    {
        get => _osVersion;
        set => SetProperty(ref _osVersion, value);
    }

    public string KernelVersion
    {
        get => _kernelVersion;
        set => SetProperty(ref _kernelVersion, value);
    }

    public string RamTotal
    {
        get => _ramTotal;
        set => SetProperty(ref _ramTotal, value);
    }

    public double CpuTemp
    {
        get => _cpuTemp;
        set => SetProperty(ref _cpuTemp, value);
    }

    public double GpuTemp
    {
        get => _gpuTemp;
        set => SetProperty(ref _gpuTemp, value);
    }

    public double CpuUsage
    {
        get => _cpuUsage;
        set => SetProperty(ref _cpuUsage, value);
    }

    public double RamUsage
    {
        get => _ramUsage;
        set => SetProperty(ref _ramUsage, value);
    }

    public double GpuUsage
    {
        get => _gpuUsage;
        set => SetProperty(ref _gpuUsage, value);
    }

    // INotifyPropertyChanged implementation
    public event PropertyChangedEventHandler? PropertyChanged;

    private void RefreshDynamicMetrics(object? sender, EventArgs e)
    {
        RefreshDynamicMetricsAsync();
    }

    private async void RefreshDynamicMetricsAsync()
    {
        if (_samplePending) return;
        _samplePending = true;
        _monitorGpu = this.FindControl<CheckBox>("EnableGpuMonitoring")?.IsChecked == true;
        try
        {
            var metricsData = await Task.Run(() =>
            {
                var data = new MetricsData();

                var frequencies = GetCoreFrequencies();
                data.CoreLabels = frequencies.labels;
                data.CoreGHz = frequencies.values;
                // Update CPU metrics
                data.CpuUsage = GetCpuUsage();
                data.CpuTemp = GetCpuTemperature();

                // Update RAM metrics
                data.RamUsage = GetRamUsage();

                // Update GPU metrics
                var gpuMetrics = GetGpuMetrics();
                data.GpuTemp = gpuMetrics.temperature;
                data.GpuUsage = gpuMetrics.usage;
                data.VramUsed = _vramUsed;
                data.VramTotal = _vramTotal;
                data.GpuWatts = _gpuWatts;

                return data;
            });

            // Update UI from UI thread
            Dispatcher.UIThread.Post(() =>
            {
                _frequencySeries.Values = metricsData.CoreGHz;
                this.FindControl<CartesianChart>("FrequencyChart")!.XAxes = new[] { new Axis { Labels = metricsData.CoreLabels, LabelsRotation = 45, TextSize = 10 } };
                var hasVram = metricsData.VramUsed.HasValue && metricsData.VramTotal > 0;
                this.FindControl<TextBlock>("VramSummary")!.Text = !_monitorGpu ? "Paused" : hasVram ?
                    $"{metricsData.VramUsed / 1024:F1} / {metricsData.VramTotal / 1024:F1} GiB" : "N/A";
                this.FindControl<ProgressBar>("VramUsageBar")!.Value = hasVram ?
                    Math.Clamp(metricsData.VramUsed!.Value / metricsData.VramTotal!.Value * 100, 0, 100) : 0;
                this.FindControl<TextBlock>("GpuPower")!.Text = !_monitorGpu ? "Paused" :
                    metricsData.GpuWatts.HasValue ? $"{metricsData.GpuWatts:F1} W" : "N/A";
                // Apply the collected metrics to UI-bound properties
                CpuUsage = metricsData.CpuUsage;
                CpuTemp = metricsData.CpuTemp;
                RamUsage = metricsData.RamUsage;
                GpuTemp = metricsData.GpuTemp;
                GpuUsage = metricsData.GpuUsage;
                PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(GpuTemperatureDisplay)));
                PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(GpuUsageDisplay)));




                // Update temperature history charts
                if (_cpuTempHistory.Count >= MAX_HISTORY_POINTS)
                    _cpuTempHistory.RemoveAt(0);
                _cpuTempHistory.Add(metricsData.CpuTemp);

                if (_gpuTempHistory.Count >= MAX_HISTORY_POINTS)
                    _gpuTempHistory.RemoveAt(0);
                _gpuTempHistory.Add(GpuReadingsAvailable ? metricsData.GpuTemp : null);
            });
        }
        catch (Exception ex)
        {
            // Log exception if needed
            Console.WriteLine($"Error updating metrics: {ex.Message}");
        }
        finally { _samplePending = false; }
    }

    private void InitializeStaticSystemInfo()
    {
        try
        {
            // Initialize CPU information
            CpuName = GetCpuName();

            // Initialize GPU information
            DetectGpuType();
            GpuName = GetGpuName();

            // Find fan speed paths and cache them
            FindSystemPaths();

            // Update GPU driver info on UI thread
            var gpuDriver = GetGpuDriverVersion();

            // Initialize temperature graph
            InitializeTemperatureGraph();

            Dispatcher.UIThread.Post(() => { GpuDriver.Text = gpuDriver; });

            // Get OS information
            OsVersion = GetOsVersion();
            KernelVersion = GetKernelVersion();

            // Get RAM information
            RamTotal = GetTotalRam();

        }
        catch (Exception ex)
        {
            Console.WriteLine($"Error during initialization: {ex.Message}");
        }
    }

    private string GetCpuName()
    {
        try
        {
            var cpuInfo = File.ReadAllText("/proc/cpuinfo");
            var modelNameMatch = Regex.Match(cpuInfo, @"model name\s+:\s+(.+)");
            if (modelNameMatch.Success) return modelNameMatch.Groups[1].Value.Trim();
            return "Unknown CPU";
        }
        catch
        {
            return "CPU Information Unavailable";
        }
    }

    private void DetectGpuType()
    {
        try
        {
            // Check for NVIDIA GPU
            if (Directory.Exists("/sys/class/drm/card0/device/driver/module/nvidia") ||
                RunCommand("lspci", "").Contains("NVIDIA"))
            {
                _gpuType = GpuType.Nvidia;
                return;
            }

            // Check for AMD GPU
            if (Directory.Exists("/sys/class/drm/card0/device/driver/module/amdgpu") ||
                RunCommand("lspci", "").Contains("AMD") ||
                RunCommand("lspci", "").Contains("ATI"))
            {
                _gpuType = GpuType.Amd;
                return;
            }

            // Default to Intel if not NVIDIA or AMD
            if (RunCommand("lspci", "").Contains("Intel"))
            {
                _gpuType = GpuType.Intel;
                return;
            }

            _gpuType = GpuType.Unknown;
        }
        catch
        {
            _gpuType = GpuType.Unknown;
        }
    }

    private string GetGpuName()
    {
        try
        {
            switch (_gpuType)
            {
                case GpuType.Nvidia:
                    return GetNvidiaGpuName();
                case GpuType.Amd:
                    return GetAmdGpuName();
                case GpuType.Intel:
                    return GetIntelGpuName();
                default:
                    return GetFallbackGpuName();
            }
        }
        catch
        {
            return "GPU Information Unavailable";
        }
    }

    private string GetNvidiaGpuName()
    {
        // PCI metadata identifies the card without waking its driver.
        var lines = RunCommand("lspci", "").Split('\n');
        var gpu = lines.FirstOrDefault(line => line.Contains("NVIDIA", StringComparison.OrdinalIgnoreCase) &&
            (line.Contains("VGA") || line.Contains("3D controller") || line.Contains("Display controller")));
        if (gpu != null)
        {
            var separator = gpu.IndexOf(": ", StringComparison.Ordinal);
            return separator >= 0 ? gpu[(separator + 2)..].Trim() : gpu.Trim();
        }
        return "NVIDIA GPU (Unknown Model)";
    }

    private string GetAmdGpuName()
    {
        // Try ROCm-SMI if available
        var rocmOutput = RunCommand("rocm-smi", "--showproductname");
        if (!string.IsNullOrWhiteSpace(rocmOutput))
        {
            var match = Regex.Match(rocmOutput, @"Product Name:\s+(.+)");
            if (match.Success)
                return match.Groups[1].Value.Trim();
        }

        // Fallback to glxinfo
        var glxOutput = RunCommand("glxinfo", "-B");
        var glxMatch = Regex.Match(glxOutput, @"OpenGL renderer string:\s+(.+)");
        if (glxMatch.Success)
        {
            var renderer = glxMatch.Groups[1].Value;
            return Regex.Replace(renderer, @"(\(.*?\)|LLVM.*|DRM.*)", "").Trim(); // Clean up extra info
        }

        // Fallback to lspci
        var lspciOutput = RunCommand("lspci", "-vmm");
        var lspciMatch = Regex.Match(lspciOutput, @"Device:\s+(.+?)(?:\s*\[|\(|$)");
        if (lspciMatch.Success)
        {
            var rawName = lspciMatch.Groups[1].Value.Trim();
            return Regex.Replace(rawName, @"\b(R[0-9]{3}|GFX[0-9]{3})\b", "").Trim(); // Remove chip codes
        }

        return "AMD GPU (Unknown Model)";
    }

    private string GetIntelGpuName()
    {
        // Try intel_gpu_top if available
        var intelOutput = RunCommand("intel_gpu_top", "-o -");
        if (!string.IsNullOrWhiteSpace(intelOutput))
        {
            var match = Regex.Match(intelOutput, @"GPU:\s+(.+)");
            if (match.Success)
                return match.Groups[1].Value.Trim();
        }

        // Fallback to lspci
        var lspciOutput = RunCommand("lspci", "-vmm");
        var lspciMatch = Regex.Match(lspciOutput, @"Device:\s+(.+?)(?:\s*\[|\(|$)");
        if (lspciMatch.Success)
        {
            var rawName = lspciMatch.Groups[1].Value.Trim();
            return Regex.Replace(rawName, @"\b(Alder Lake|Raptor Lake|Xe)\b", "").Trim(); // Remove chipset names
        }

        return "Intel Graphics (Unknown Model)";
    }

    private string GetFallbackGpuName()
    {
        var lspciOutput = RunCommand("lspci", "-vmm");
        var match = Regex.Match(lspciOutput, @"Device:\s+(.+?)(?:\s*\[|\(|$)");
        return match.Success ? match.Groups[1].Value.Trim() : "Unknown GPU";
    }

    private string GetGpuDriverVersion()
    {
        try
        {
            if (_gpuType == GpuType.Nvidia && File.Exists("/sys/module/nvidia/version"))
                return File.ReadAllText("/sys/module/nvidia/version").Trim();
            return _gpuType switch { GpuType.Amd => "amdgpu", GpuType.Intel => "i915 / xe", _ => "Unknown" };
        }
        catch { return "Unavailable"; }
    }

    private string GetOsVersion()
    {
        try
        {
            if (File.Exists("/etc/os-release"))
            {
                var osRelease = File.ReadAllText("/etc/os-release");
                var prettyNameMatch = Regex.Match(osRelease, @"PRETTY_NAME=""(.+?)""");
                if (prettyNameMatch.Success) return prettyNameMatch.Groups[1].Value;
            }

            // Fallback
            var lsbOutput = RunCommand("lsb_release", "-d");
            var lsbMatch = Regex.Match(lsbOutput, @"Description:\s+(.+)");
            if (lsbMatch.Success) return lsbMatch.Groups[1].Value;

            return "Unknown Linux Distribution";
        }
        catch
        {
            return "OS Information Unavailable";
        }
    }

    private string GetKernelVersion()
    {
        try
        {
            var output = RunCommand("uname", "-r");
            return output.Trim();
        }
        catch
        {
            return "Kernel Information Unavailable";
        }
    }

    private string GetTotalRam()
    {
        try
        {
            var memInfo = File.ReadAllText("/proc/meminfo");
            var match = Regex.Match(memInfo, @"MemTotal:\s+(\d+) kB");
            if (match.Success)
            {
                var kbytes = long.Parse(match.Groups[1].Value);
                var gbytes = kbytes / (1024.0 * 1024.0);
                return $"{gbytes:F2} GB";
            }

            return "Unknown";
        }
        catch
        {
            return "RAM Information Unavailable";
        }
    }

    private void InitializeTemperatureGraph()
    {
        // Initialize collections
        _cpuTempHistory = new ObservableCollection<double>();
        _gpuTempHistory = new ObservableCollection<double?>();

        // Initialize series
        _tempSeries = new ObservableCollection<ISeries>
        {
            new LineSeries<double>
            {
                Values = _cpuTempHistory,
                Name = "CPU Temperature",
                Stroke = new SolidColorPaint(SKColors.CornflowerBlue) { StrokeThickness = 3 },
                GeometryStroke = new SolidColorPaint(SKColors.DeepSkyBlue),
                GeometryFill = new SolidColorPaint(SKColors.DeepSkyBlue),
                Fill = new SolidColorPaint(SKColors.Transparent),
                GeometrySize = 5,
                XToolTipLabelFormatter = chartPoint => $"CPU: {chartPoint.Label}°C"
            },
            new LineSeries<double?>
            {
                Values = _gpuTempHistory,
                Name = "GPU Temperature",
                Stroke = new SolidColorPaint(SKColors.LimeGreen) { StrokeThickness = 3 },
                GeometryFill = new SolidColorPaint(SKColors.GreenYellow),
                GeometryStroke = new SolidColorPaint(SKColors.GreenYellow),
                Fill = new SolidColorPaint(SKColors.Transparent),
                GeometrySize = 5,
                XToolTipLabelFormatter = chartPoint => $"GPU: {chartPoint.Label}°C"
            }
        };

        // Initialize and configure the chart
        _temperatureChart = this.FindControl<CartesianChart>("TemperatureChart");
        if (_temperatureChart != null)
        {
            _temperatureChart.Series = _tempSeries;
            _temperatureChart.XAxes = new List<Axis>
            {
                new()
                {
                    Name = "Time",
                    IsVisible = false
                }
            };
            _temperatureChart.YAxes = new List<Axis>
            {
                new()
                {
                    Name = "Temperature (°C)",
                    NamePaint = new SolidColorPaint(SKColors.Gray),
                    LabelsPaint = new SolidColorPaint(SKColors.Gray)
                }
            };
        }
    }

    private long _previousCpuTotal;
    private long _previousCpuIdle;
    private double GetCpuUsage()
    {
        try
        {
            var values = File.ReadLines("/proc/stat").First().Split(' ', StringSplitOptions.RemoveEmptyEntries).Skip(1).Take(8).Select(long.Parse).ToArray();
            var total = values.Sum();
            var idle = values[3] + values[4];
            var totalDelta = total - _previousCpuTotal;
            var idleDelta = idle - _previousCpuIdle;
            var first = _previousCpuTotal == 0;
            _previousCpuTotal = total; _previousCpuIdle = idle;
            return first || totalDelta <= 0 ? 0 : Math.Clamp(100.0 * (1 - (double)idleDelta / totalDelta), 0, 100);
        }
        catch { return 0; }
    }

    private double GetCpuTemperature()
    {
        try
        {
            // Check for multiple temperature files from hwmon6
            if (_systemInfoPaths.ContainsKey("cpu_temp_files"))
            {
                var tempFiles = _systemInfoPaths["cpu_temp_files"].Split(',');
                if (tempFiles.Length > 0)
                {
                    double tempSum = 0;
                    var validReadings = 0;

                    foreach (var tempFile in tempFiles)
                        if (File.Exists(tempFile))
                        {
                            var temperatureStr = File.ReadAllText(tempFile).Trim();
                            if (int.TryParse(temperatureStr, out var tempValue))
                            {
                                // Temperature is often reported in millidegrees C
                                tempSum += tempValue / 1000.0;
                                validReadings++;
                            }
                        }

                    if (validReadings > 0)
                        // Calculate average temperature
                        return Math.Round(tempSum / validReadings, 1);
                }
            }

            // Fallback to single temperature file if available
            if (_systemInfoPaths.ContainsKey("cpu_temp") && File.Exists(_systemInfoPaths["cpu_temp"]))
            {
                var temperatureStr = File.ReadAllText(_systemInfoPaths["cpu_temp"]).Trim();
                if (int.TryParse(temperatureStr, out var tempValue))
                {
                    // Temperature is often reported in millidegrees C
                    var tempC = tempValue / 1000.0;
                    return Math.Round(tempC, 1);
                }
            }

            // Fallback to lm-sensors if available
            var output = RunCommand("sensors", "");
            var match = Regex.Match(output, @"Package id \d+:\s+\+?(\d+\.\d+)°C");
            if (match.Success)
                if (double.TryParse(match.Groups[1].Value, out var tempC))
                    return Math.Round(tempC, 1);

            // Couldn't get temperature
            return 0;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Error getting CPU temperature: {ex.Message}");
            return 0;
        }
    }

    private double GetRamUsage()
    {
        try
        {
            var memInfo = File.ReadAllText("/proc/meminfo");

            var totalMatch = Regex.Match(memInfo, @"MemTotal:\s+(\d+) kB");
            var availableMatch = Regex.Match(memInfo, @"MemAvailable:\s+(\d+) kB");

            if (totalMatch.Success && availableMatch.Success)
            {
                var totalKb = long.Parse(totalMatch.Groups[1].Value);
                var availableKb = long.Parse(availableMatch.Groups[1].Value);
                var usedKb = totalKb - availableKb;

                var usagePercentage = usedKb / (double)totalKb * 100.0;
                return Math.Round(usagePercentage, 1);
            }

            return 0;
        }
        catch
        {
            return 0;
        }
    }

    private (double temperature, double usage) GetGpuMetrics()
    {
        try
        {
            switch (_gpuType)
            {
                case GpuType.Nvidia:
                    return GetNvidiaGpuMetrics();
                case GpuType.Amd:
                    return GetAmdGpuMetrics();
                case GpuType.Intel:
                    return GetIntelGpuMetrics();
                default:
                    return (0, 0);
            }
        }
        catch
        {
            return (0, 0);
        }
    }

    private (double temperature, double usage) GetNvidiaGpuMetrics()
    {
        _vramUsed = _vramTotal = _gpuWatts = null;
        if (!_monitorGpu) return (0, 0);
        const string fields = "temperature.gpu,utilization.gpu,memory.used,memory.total,";
        var output = RunCommand("nvidia-smi", "--query-gpu=" + fields + "power.draw.average,power.draw,power.max_limit --format=csv,noheader,nounits");
        // Older drivers may not recognize the average-power field.
        if (string.IsNullOrWhiteSpace(output))
        {
            output = RunCommand("nvidia-smi", "--query-gpu=" + fields + "power.draw,power.max_limit --format=csv,noheader,nounits");
            var legacy = output.Split('\n')[0].Split(',');
            if (legacy.Length == 6) output = string.Join(',', legacy.Take(4)) + ",N/A," + string.Join(',', legacy.Skip(4));
        }
        var sample = NvidiaTelemetry.Parse(output);
        _vramUsed = sample.MemoryUsed; _vramTotal = sample.MemoryTotal; _gpuWatts = sample.Watts;
        return (sample.Temperature ?? 0, sample.Usage ?? 0);
    }

    private void InitializeExtraCharts()
    {
        this.FindControl<CartesianChart>("FrequencyChart")!.Series = new ISeries[] { _frequencySeries };
        this.FindControl<CartesianChart>("FrequencyChart")!.YAxes = new[] { new Axis { Name = "GHz", MinLimit = 0 } };
    }

    private static (string[] labels, double[] values) GetCoreFrequencies()
    {
        var cores = new SortedDictionary<(int package, int core), List<double>>();
        foreach (var path in Directory.EnumerateDirectories("/sys/devices/system/cpu", "cpu*"))
        {
            if (!Regex.IsMatch(Path.GetFileName(path), @"^cpu\d+$")) continue;
            try
            {
                var package = int.Parse(File.ReadAllText(Path.Combine(path, "topology/physical_package_id")));
                var core = int.Parse(File.ReadAllText(Path.Combine(path, "topology/core_id")));
                var freq = double.Parse(File.ReadAllText(Path.Combine(path, "cpufreq/scaling_cur_freq")), CultureInfo.InvariantCulture) / 1000000;
                var key = (package, core);
                if (!cores.ContainsKey(key)) cores[key] = new List<double>();
                cores[key].Add(freq);
            }
            catch (IOException) { } // Offline/hot-unplugged CPUs have no reading.
            catch (FormatException) { }
            catch (UnauthorizedAccessException) { }
        }
        return (cores.Keys.Select(k => $"{k.package}:{k.core}").ToArray(), cores.Values.Select(v => v.Average()).ToArray());
    }

    private (double temperature, double usage) GetAmdGpuMetrics()
    {
        try
        {
            double temp = 0;
            double usage = 0;

            // Use cached GPU temp path if available
            if (_systemInfoPaths.ContainsKey("gpu_temp") && File.Exists(_systemInfoPaths["gpu_temp"]))
            {
                var tempStr = File.ReadAllText(_systemInfoPaths["gpu_temp"]);
                if (int.TryParse(tempStr.Trim(), out var tempValue))
                    temp = tempValue / 1000.0; // Convert from milliCelsius to Celsius
            }

            // Use cached GPU usage path if available
            if (_systemInfoPaths.ContainsKey("gpu_usage") && File.Exists(_systemInfoPaths["gpu_usage"]))
            {
                var usageStr = File.ReadAllText(_systemInfoPaths["gpu_usage"]);
                if (int.TryParse(usageStr.Trim(), out var usageValue)) usage = usageValue;
            }

            // If we couldn't get values from cached paths, try radeontop
            if (temp == 0 || usage == 0)
            {
                var radeontopOutput = RunCommand("radeontop", "-d- -l1");
                var tempMatch = Regex.Match(radeontopOutput, @"Temperature:\s+(\d+)");
                var usageMatch = Regex.Match(radeontopOutput, @"GPU\s+(\d+)%");

                if (tempMatch.Success && temp == 0)
                    if (double.TryParse(tempMatch.Groups[1].Value, out var tempValue))
                        temp = tempValue;

                if (usageMatch.Success && usage == 0)
                    if (double.TryParse(usageMatch.Groups[1].Value, out var usageValue))
                        usage = usageValue;
            }

            return (temp, usage);
        }
        catch
        {
            return (0, 0);
        }
    }

    private (double temperature, double usage) GetIntelGpuMetrics()
    {
        try
        {
            double temp = 0;
            double usage = 0;

            // Use cached GPU temp path if available
            if (_systemInfoPaths.ContainsKey("gpu_temp") && File.Exists(_systemInfoPaths["gpu_temp"]))
            {
                var tempStr = File.ReadAllText(_systemInfoPaths["gpu_temp"]);
                if (int.TryParse(tempStr.Trim(), out var tempValue))
                    temp = tempValue / 1000.0; // Convert from milliCelsius to Celsius
            }

            // For usage, we might be able to use the intel_gpu_top tool
            var intelOutput = RunCommand("intel_gpu_top", "-o -");
            var match = Regex.Match(intelOutput, @"Render/3D.*?(\d+)%");
            if (match.Success)
                if (double.TryParse(match.Groups[1].Value, out var usageValue))
                    usage = usageValue;

            return (temp, usage);
        }
        catch
        {
            return (0, 0);
        }
    }

    private void FindSystemPaths()
    {
        try
        {
            // First check for hwmon6 directory and collect all temp input files
            string[] hwmonPaths =
            [
                "/sys/class/hwmon/hwmon5", "/sys/class/hwmon/hwmon6", "/sys/class/hwmon/hwmon7",
                "/sys/class/hwmon/hwmon8"
            ];
            foreach (var hwmonPath in hwmonPaths)
                if (Directory.Exists(hwmonPath))
                {
                    var tempFiles = Directory.GetFiles(hwmonPath, "temp*_input");
                    if (tempFiles.Length > 3)
                    {
                        // Store all temperature files in a list
                        _systemInfoPaths["cpu_temp_files"] = string.Join(",", tempFiles);
                        Console.WriteLine(
                            $"Found CPU Reporting Temps at {_systemInfoPaths["cpu_temp_files"].Split(',').Length} Cores, using their Avg ({hwmonPath})");
                        return;
                    }
                }

            // Fallback to other possible paths if hwmon6 doesn't have temperature files
            string[] possibleCpuTempPaths =
            {
                "/sys/class/hwmon/hwmon1/temp1_input",
                "/sys/class/thermal/thermal_zone0/temp",
                "/sys/devices/platform/coretemp.0/hwmon/hwmon1/temp1_input"
            };


            foreach (var pathPattern in possibleCpuTempPaths)
                if (Directory.Exists(Path.GetDirectoryName(pathPattern) ?? string.Empty))
                {
                    var files = Directory.GetFiles(Path.GetDirectoryName(pathPattern) ?? string.Empty,
                        Path.GetFileName(pathPattern));
                    if (files.Length > 0)
                    {
                        _systemInfoPaths["cpu_temp"] = files[0];
                        break;
                    }
                }

            Console.WriteLine(
                $"Found CPU Reporting Temp at {_systemInfoPaths["cpu_temp"].Split(',').Length} Core");

            // Find fan speed paths

            // Find GPU temperature path based on GPU type
            switch (_gpuType)
            {
                case GpuType.Nvidia:
                    // Nvidia uses nvidia-smi command
                    break;
                case GpuType.Amd:
                    string[] possibleAmdGpuTempPaths =
                    {
                        "/sys/class/drm/card0/device/hwmon/hwmon*/temp1_input",
                        "/sys/class/hwmon/hwmon*/temp1_input"
                    };
                    foreach (var pathPattern in possibleAmdGpuTempPaths)
                        if (Directory.Exists(Path.GetDirectoryName(pathPattern) ?? string.Empty))
                        {
                            var files = Directory.GetFiles(
                                Path.GetDirectoryName(pathPattern) ?? string.Empty,
                                Path.GetFileName(pathPattern).Replace("*", "").Replace("?", ""),
                                SearchOption.AllDirectories);
                            if (files.Length > 0)
                            {
                                _systemInfoPaths["gpu_temp"] = files[0];
                                break;
                            }
                        }

                    break;
                case GpuType.Intel:
                    string[] possibleIntelGpuTempPaths =
                    {
                        "/sys/class/thermal/thermal_zone*/temp",
                        "/sys/class/hwmon/hwmon*/temp1_input"
                    };
                    foreach (var pathPattern in possibleIntelGpuTempPaths)
                        if (Directory.Exists(Path.GetDirectoryName(pathPattern) ?? string.Empty))
                        {
                            var dirs = Directory.GetDirectories(Path.GetDirectoryName(pathPattern) ?? string.Empty);
                            foreach (var dir in dirs)
                            {
                                var typeFile = Path.Combine(dir, "type");
                                if (File.Exists(typeFile) && File.ReadAllText(typeFile).Contains("gpu"))
                                {
                                    var tempFile = Path.Combine(dir, "temp");
                                    if (File.Exists(tempFile))
                                    {
                                        _systemInfoPaths["gpu_temp"] = tempFile;
                                        break;
                                    }
                                }
                            }
                        }

                    break;
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Error finding system paths: {ex.Message}");
        }
    }

    private string RunCommand(string command, string arguments)
    {
        try
        {
            using var process = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = command,
                    Arguments = arguments,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true
                }
            };

            process.Start();
            var stdout = process.StandardOutput.ReadToEndAsync();
            var stderr = process.StandardError.ReadToEndAsync();
            if (!process.WaitForExit(3000))
            {
                process.Kill(entireProcessTree: true);
                return string.Empty;
            }
            return process.ExitCode == 0 ? stdout.GetAwaiter().GetResult() : string.Empty;
        }
        catch
        {
            return string.Empty;
        }
    }

    protected bool SetProperty<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return false;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        return true;
    }

    protected virtual void OnPropertyChanged([CallerMemberName] string? propertyName = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }

    private class MetricsData
    {
        public string[] CoreLabels { get; set; } = Array.Empty<string>();
        public double[] CoreGHz { get; set; } = Array.Empty<double>();
        public double? VramUsed { get; set; }
        public double? VramTotal { get; set; }
        public double? GpuWatts { get; set; }
        public double CpuUsage { get; set; }
        public double CpuTemp { get; set; }
        public double RamUsage { get; set; }
        public double GpuTemp { get; set; }
        public double GpuUsage { get; set; }
    }

    private enum GpuType
    {
        Unknown,
        Nvidia,
        Amd,
        Intel
    }
}