// SPDX-License-Identifier: GPL-3.0-only
// Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;

namespace DivAcerManagerMax;

/// <summary>
///     Client for communicating with the DAMX-Daemon over Unix socket
/// </summary>
public class DAMXClient : IDisposable
{
    private static string SocketPath => Environment.GetEnvironmentVariable("DAMX_SOCKET_PATH") ?? "/run/DAMX.sock";

    /// <summary>
    ///     Send a command to the DAMX-Daemon and receive response
    /// </summary>
    /// <param name="command">Command name</param>
    /// <param name="parameters">Optional parameters</param>
    /// <returns>Response from daemon as a JsonDocument</returns>
    private readonly SemaphoreSlim _commandLock = new(1, 1);

    // Cache of available features
    private HashSet<string> _availableFeatures = new();

    private bool _disposed;
    private Socket? _socket;

    public DAMXClient()
    {
        IsConnected = false;
    }

    public bool IsConnected { get; private set; }

    public void Dispose()
    {
        Dispose(true);
        GC.SuppressFinalize(this);
    }

    // Property to check if a feature is available
    public bool IsFeatureAvailable(string featureName)
    {
        return _availableFeatures.Contains(featureName);
    }

    /// <summary>
    ///     Connect to the DAMX-Daemon Unix socket
    /// </summary>
    /// <returns>True if connection successful, false otherwise</returns>
    public async Task<bool> ConnectAsync()
    {
        try
        {
            await GetAllSettingsAsync();
            return true;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Failed to connect to daemon: {ex.Message}");
            ResetConnection();
            return false;
        }
    }

    /// <summary>
    ///     Disconnect from the DAMX-Daemon Unix socket
    /// </summary>
    public void Disconnect()
    {
        if (IsConnected)
            try
            {
                _socket?.Close();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Error during disconnect: {ex.Message}");
            }
            finally
            {
                IsConnected = false;
            }
    }

    public async Task<JsonDocument> SendCommandAsync(string command, Dictionary<string, object>? parameters = null)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        await _commandLock.WaitAsync();
        try
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(12));
            if (!IsConnected)
            {
                _socket?.Dispose();
                _socket = new Socket(AddressFamily.Unix, SocketType.Stream, ProtocolType.Unspecified);
                await _socket.ConnectAsync(new UnixDomainSocketEndPoint(SocketPath), timeout.Token);
                IsConnected = true;
            }
            var request = JsonSerializer.Serialize(new { command, @params = parameters ?? new() }) + "\n";
            var bytes = Encoding.UTF8.GetBytes(request);
            for (var sent = 0; sent < bytes.Length;)
            {
                var n = await _socket.SendAsync(bytes.AsMemory(sent), SocketFlags.None, timeout.Token);
                if (n == 0) throw new IOException("Daemon disconnected during send");
                sent += n;
            }
            using var response = new MemoryStream();
            // The lock permits exactly one response in flight. No future
            // response exists yet, so receive chunks rather than one syscall per byte.
            var buffer = new byte[4096];
            while (true)
            {
                var n = await _socket.ReceiveAsync(buffer.AsMemory(), SocketFlags.None, timeout.Token);
                if (n == 0) throw new IOException("Daemon disconnected during receive");
                var delimiter = Array.IndexOf(buffer, (byte)'\n', 0, n);
                var count = delimiter >= 0 ? delimiter : n;
                if (response.Length + count > 262144) break;
                response.Write(buffer, 0, count);
                if (delimiter < 0) continue;
                if (delimiter != n - 1) throw new IOException("Unexpected data after daemon response");
                var result = JsonDocument.Parse(response.ToArray());
                if (!result.RootElement.GetProperty("success").GetBoolean())
                {
                    var error = result.RootElement.GetProperty("error").GetString();
                    result.Dispose();
                    throw new InvalidOperationException(error ?? "Command failed");
                }
                return result;
            }
            throw new IOException("Daemon response exceeds framing limit");
        }
        catch
        {
            ResetConnection();
            throw;
        }
        finally { _commandLock.Release(); }
    }

    /// <summary>
    ///     Get all settings from the DAMX-Daemon
    /// </summary>
    /// <returns>All settings as a JsonDocument</returns>
    public async Task<DAMXSettings> GetAllSettingsAsync()
    {
        using var response = await SendCommandAsync("get_all_settings");
        var success = response.RootElement.GetProperty("success").GetBoolean();

        if (success)
        {
            var data = response.RootElement.GetProperty("data");
            var settings = JsonSerializer.Deserialize<DAMXSettings>(data.GetRawText()) ?? new DAMXSettings();

            // Update available features cache
            if (settings.AvailableFeatures != null)
                _availableFeatures = new HashSet<string>(settings.AvailableFeatures);

            return settings;
        }

        var error = response.RootElement.GetProperty("error").GetString();
        throw new Exception($"Failed to get settings: {error}");
    }

    /// <summary>
    ///     Set fan speeds
    /// </summary>
    /// <param name="cpu">CPU fan speed (0-100)</param>
    /// <param name="gpu">GPU fan speed (0-100)</param>
    /// <returns>True if successful</returns>
    public async Task<bool> SetFanSpeedAsync(int cpu, int gpu)
    {
        if (!IsFeatureAvailable("fan_speed"))
        {
            Console.WriteLine("Fan speed control is not available on this device");
            return false;
        }

        var parameters = new Dictionary<string, object>
        {
            { "cpu", cpu },
            { "gpu", gpu }
        };

        using var response = await SendCommandAsync("set_fan_speed", parameters);
        return response.RootElement.GetProperty("success").GetBoolean();
    }

    protected virtual void Dispose(bool disposing)
    {
        if (_disposed) return;

        if (disposing)
        {
            Disconnect();
            _socket?.Dispose();
        }

        _disposed = true;
    }

    private void ResetConnection()
    {
        IsConnected = false;

        try
        {
            _socket?.Shutdown(SocketShutdown.Both);
        }
        catch
        {
            // Socket may already be closed.
        }

        try
        {
            _socket?.Dispose();
        }
        catch
        {
            // Ignore cleanup failure.
        }
    }
}

/// <summary>
///     Models for DAMX settings
/// </summary>
public class DAMXSettings
{
    [JsonPropertyName("laptop_type")] public string LaptopType { get; set; } = "UNKNOWN";

    [JsonPropertyName("has_four_zone_kb")] public bool HasFourZoneKb { get; set; }

    [JsonPropertyName("available_features")]
    public List<string> AvailableFeatures { get; set; } = new();

    [JsonPropertyName("version")] public string Version { get; set; } = "Disconnected";
    [JsonPropertyName("driver_version")] public string DriverVersion { get; set; } = "Unavailable";


    [JsonPropertyName("thermal_profile")] public ThermalProfileSettings ThermalProfile { get; set; } = new();

    [JsonPropertyName("backlight_timeout")]
    public string BacklightTimeout { get; set; } = "0";

    [JsonPropertyName("battery_calibration")]
    public string BatteryCalibration { get; set; } = "0";

    [JsonPropertyName("battery_limiter")] public string BatteryLimiter { get; set; } = "0";

    [JsonPropertyName("boot_animation_sound")]
    public string BootAnimationSound { get; set; } = "0";

    [JsonPropertyName("fan_speed")] public FanSpeedSettings FanSpeed { get; set; } = new();

    [JsonPropertyName("lcd_override")] public string LcdOverride { get; set; } = "0";

    [JsonPropertyName("usb_charging")] public string UsbCharging { get; set; } = "0";

    [JsonPropertyName("per_zone_mode")] public string PerZoneMode { get; set; } = "";

    [JsonPropertyName("four_zone_mode")] public string FourZoneMode { get; set; } = "";

    [JsonPropertyName("fan_rpm")] public Dictionary<string, int?> FanRpm { get; set; } = new();
    [JsonPropertyName("ac_online")] public bool? AcOnline { get; set; }
    [JsonPropertyName("lightbar_status")] public string LightbarStatus { get; set; } = "";
    [JsonPropertyName("lighting_modes")] public Dictionary<string, List<int>> LightingModes { get; set; } = new();
    [JsonPropertyName("lighting_state")] public Dictionary<string, JsonElement> LightingState { get; set; } = new();
    [JsonPropertyName("modprobe_parameter")]
    public string ModprobeParameter { get; set; } = "";
}

public class ThermalProfileSettings
{
    [JsonPropertyName("current")] public string Current { get; set; } = "";

    [JsonPropertyName("available")] public List<string> Available { get; set; } = new();
}

public class FanSpeedSettings
{
    [JsonPropertyName("cpu")] public string Cpu { get; set; } = "0";

    [JsonPropertyName("gpu")] public string Gpu { get; set; } = "0";
}
