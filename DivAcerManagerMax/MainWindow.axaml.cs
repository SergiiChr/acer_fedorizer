// SPDX-License-Identifier: GPL-3.0-only
// Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Markup.Xaml;
using Avalonia.Media;
using Avalonia.Threading;
using MsBox.Avalonia;

namespace DivAcerManagerMax;

public partial class MainWindow : Window, INotifyPropertyChanged
{
    private const string ProjectVersion = "1.2.0";
    private bool _daemonUnavailable = true;

    private void SetDaemonOverlay(bool unavailable)
    {
        _daemonUnavailable = unavailable;
        UpdateDaemonOverlay();
    }

    private void MainTabChanged(object? sender, SelectionChangedEventArgs e) => UpdateDaemonOverlay();

    private void UpdateDaemonOverlay()
    {
        // Selection changes also fire during XAML construction, before a name scope exists.
        if (_daemonErrorGrid == null) return;
        _daemonErrorGrid.IsVisible = _daemonUnavailable &&
            (this.FindControl<TabControl>("MainTabs")?.SelectedItem as TabItem)?.Name != "DisplayTab";
    }

    private bool _applyingSettings;
    private bool _closed;
    private bool _initializing;
    private bool _profileChangePending;
    private bool _refreshingStatus;
    private readonly DispatcherTimer _statusTimer = new() { Interval = TimeSpan.FromSeconds(2) };
    // UI Controls (will be bound via NameScope)
    private Button _applyKeyboardColorsButton;
    private RadioButton _autoFanSpeedRadioButton;
    private CheckBox _backlightTimeoutCheckBox;
    private RadioButton _balancedProfileButton;
    private CheckBox _batteryLimitCheckBox;
    private CheckBox _bootAnimAndSoundCheckBox;
    private TextBlock _calibrationStatusTextBlock;
    public DAMXClient _client;
    private Slider _cpuFanSlider;
    private int _cpuFanSpeed = 50;
    private TextBlock _cpuFanTextBlock;
    private Grid _daemonErrorGrid;
    private TextBlock _daemonVersionText;
    private TextBlock _driverVersionText;
    private Slider _gpuFanSlider;
    private int _gpuFanSpeed = 70;
    private TextBlock _gpuFanTextBlock;
    private TextBlock _guiVersionTextBlock;
    private bool _isCalibrating;
    private bool _isConnected;
    private bool _isManualFanControl;
    private bool _isSettingFanSpeed;
    private int _keyboardBrightness = 100;
    private Slider _keyBrightnessSlider;
    private TextBlock _keyBrightnessText;
    private TextBlock _laptopTypeText;
    private CheckBox _lcdOverrideCheckBox;
    private RadioButton _lowPowerProfileButton;
    private RadioButton _manualFanSpeedRadioButton;
    private RadioButton _maxFanSpeedRadioButton;
    private TextBlock _modelNameText;
    private RadioButton _performanceProfileButton;
    private ToggleSwitch _powerToggleSwitch;
    private RadioButton _quietProfileButton;
    private Button _setManualSpeedButton;
    public DAMXSettings _settings;
    private Button _startCalibrationButton;
    private Button _stopCalibrationButton;
    private TextBlock _supportedFeaturesTextBlock;
    private TextBlock _thermalProfileInfoText;
    private RadioButton _turboProfileButton;
    private ComboBox _usbChargingComboBox;
    private ColorPicker _zone1ColorPicker;
    private ColorPicker _zone2ColorPicker;
    private ColorPicker _zone3ColorPicker;
    private ColorPicker _zone4ColorPicker;

    public MainWindow()
    {
        InitializeComponent();
        DataContext = this;
        _client = new DAMXClient();
        Loaded += MainWindow_Loaded;
        _statusTimer.Tick += async (_, _) => await RefreshStatusAsync();
        Closed += (_, _) => { _closed = true; _statusTimer.Stop(); _client.Dispose(); };
    }

    public bool IsCalibrating
    {
        get => _isCalibrating;
        set => SetField(ref _isCalibrating, value);
    }

    private void InitializeComponent()
    {
        AvaloniaXamlLoader.Load(this);
    }

    private void MainWindow_Loaded(object sender, RoutedEventArgs e)
    {
        BindControls();
        AttachEventHandlers();
        _lightingUiReady = true;
        this.FindControl<ColorView>("SharedColor")!.PropertyChanged += SharedColorChanged;
        InitializeAsync();
    }

    private void BindControls()
    {
        var nameScope = this.FindNameScope();

        // Thermal Profile controls
        _lowPowerProfileButton = nameScope.Find<RadioButton>("LowPowerProfileButton");
        _quietProfileButton = nameScope.Find<RadioButton>("QuietProfileButton");
        _balancedProfileButton = nameScope.Find<RadioButton>("BalancedProfileButton");
        _performanceProfileButton = nameScope.Find<RadioButton>("PerformanceProfileButton");
        _turboProfileButton = nameScope.Find<RadioButton>("TurboProfileButton");
        _powerToggleSwitch = nameScope.Find<ToggleSwitch>("PluggedInToggleSwitch");

        // Fan control controls
        _manualFanSpeedRadioButton = nameScope.Find<RadioButton>("ManualFanSpeedRadioButton");
        _maxFanSpeedRadioButton = nameScope.Find<RadioButton>("MaxFanSpeedRadioButton");
        _cpuFanSlider = nameScope.Find<Slider>("CpuFanSlider");
        _gpuFanSlider = nameScope.Find<Slider>("GpuFanSlider");
        _cpuFanTextBlock = nameScope.Find<TextBlock>("CpuFanTextBlock");
        _gpuFanTextBlock = nameScope.Find<TextBlock>("GpuFanTextBlock");
        _setManualSpeedButton = nameScope.Find<Button>("SetManualSpeedButton");
        _autoFanSpeedRadioButton = nameScope.Find<RadioButton>("AutoFanSpeedRadioButton");

        // Battery calibration controls
        _startCalibrationButton = nameScope.Find<Button>("StartCalibrationButton");
        _stopCalibrationButton = nameScope.Find<Button>("StopCalibrationButton");
        _calibrationStatusTextBlock = nameScope.Find<TextBlock>("CalibrationStatusTextBlock");
        _batteryLimitCheckBox = nameScope.Find<CheckBox>("BatteryLimitCheckBox");

        // USB charging controls
        _usbChargingComboBox = nameScope.Find<ComboBox>("UsbChargingComboBox");

        // Keyboard lighting zone controls
        _zone1ColorPicker = nameScope.Find<ColorPicker>("Zone1ColorPicker");
        _zone2ColorPicker = nameScope.Find<ColorPicker>("Zone2ColorPicker");
        _zone3ColorPicker = nameScope.Find<ColorPicker>("Zone3ColorPicker");
        _zone4ColorPicker = nameScope.Find<ColorPicker>("Zone4ColorPicker");
        _keyBrightnessSlider = nameScope.Find<Slider>("KeyBrightnessSlider");
        _keyBrightnessText = nameScope.Find<TextBlock>("KeyBrightnessText");
        _applyKeyboardColorsButton = nameScope.Find<Button>("ApplyKeyboardColorsButton");

        // System settings controls
        _backlightTimeoutCheckBox = nameScope.Find<CheckBox>("BacklightTimeoutCheckBox");
        _lcdOverrideCheckBox = nameScope.Find<CheckBox>("LcdOverrideCheckBox");
        _bootAnimAndSoundCheckBox = nameScope.Find<CheckBox>("BootAnimAndSoundCheckBox");

        // Info Texts
        _thermalProfileInfoText = nameScope.Find<TextBlock>("ThermalProfileInfoText");
        _modelNameText = nameScope.Find<TextBlock>("ModelNameText");
        _laptopTypeText = nameScope.Find<TextBlock>("LaptopTypeText");
        _supportedFeaturesTextBlock = nameScope.Find<TextBlock>("SupportedFeaturesTextBlock");
        _daemonVersionText = nameScope.Find<TextBlock>("DaemonVersionText");
        _driverVersionText = nameScope.Find<TextBlock>("DriverVersionText");
        _guiVersionTextBlock = nameScope.Find<TextBlock>("ProjectVersionText");
        _daemonErrorGrid = nameScope.Find<Grid>("DaemonErrorGrid");

        // Set initial GUI version
        if (_guiVersionTextBlock != null)
            _guiVersionTextBlock.Text = $"v{ProjectVersion}";
    }

    private void AttachEventHandlers()
    {
        // Thermal Profile handlers
        if (_lowPowerProfileButton != null) _lowPowerProfileButton.IsCheckedChanged += ProfileButton_Checked;
        if (_quietProfileButton != null) _quietProfileButton.IsCheckedChanged += ProfileButton_Checked;
        if (_balancedProfileButton != null) _balancedProfileButton.IsCheckedChanged += ProfileButton_Checked;
        if (_performanceProfileButton != null) _performanceProfileButton.IsCheckedChanged += ProfileButton_Checked;
        if (_turboProfileButton != null) _turboProfileButton.IsCheckedChanged += ProfileButton_Checked;

        // Fan control handlers
        if (_manualFanSpeedRadioButton != null) _manualFanSpeedRadioButton.Click += ManualFanControlRadioBox_Click;
        if (_cpuFanSlider != null) _cpuFanSlider.PropertyChanged += CpuFanSlider_ValueChanged;
        if (_gpuFanSlider != null) _gpuFanSlider.PropertyChanged += GpuFanSlider_ValueChanged;
        if (_autoFanSpeedRadioButton != null) _autoFanSpeedRadioButton.Click += AutoFanSpeedRadioButtonClick;
        if (_setManualSpeedButton != null) _setManualSpeedButton.Click += SetManualSpeedButton_OnClick;

        // Battery calibration handlers
        if (_startCalibrationButton != null) _startCalibrationButton.Click += StartCalibrationButton_Click;
        if (_stopCalibrationButton != null) _stopCalibrationButton.Click += StopCalibrationButton_Click;
        if (_batteryLimitCheckBox != null) _batteryLimitCheckBox.Click += BatteryLimitCheckBox_Click;


        // Keyboard lighting handlers
        if (_keyBrightnessSlider != null) _keyBrightnessSlider.PropertyChanged += KeyboardBrightnessSlider_ValueChanged;
        if (_applyKeyboardColorsButton != null) _applyKeyboardColorsButton.Click += ApplyKeyboardColorsButton_Click;

        // System settings handlers
        if (_backlightTimeoutCheckBox != null) _backlightTimeoutCheckBox.Click += BacklightTimeoutCheckBox_Click;
        if (_lcdOverrideCheckBox != null) _lcdOverrideCheckBox.Click += LcdOverrideCheckBox_Click;
        if (_bootAnimAndSoundCheckBox != null) _bootAnimAndSoundCheckBox.Click += BootSoundCheckBox_Click;
    }

    private void UpdateUIElementVisibility()
    {
        if (_settings == null) return;

        var nameScope = this.FindNameScope();
        var thermalProfilePanel = nameScope.Find<Border>("ThermalProfilePanel");
        var fanControlPanel = nameScope.Find<Border>("FanControlPanel");
        var batteryTab = nameScope.Find<TabItem>("BatteryPanel");
        var usbChargingPanel = nameScope.Find<Border>("UsbChargingPanel");
        var keyboardLightingTab = nameScope.Find<TabItem>("KeyboardLightingPanel");
        var zoneColorControlPanel = nameScope.Find<Border>("ZoneColorControlPanel");
        var keyboardEffectsPanel = nameScope.Find<Border>("KeyboardEffectsPanel");
        var systemSettingsTab = nameScope.Find<TabItem>("SystemSettingsPanel");

        if (thermalProfilePanel != null)
            thermalProfilePanel.IsVisible = _client.IsFeatureAvailable("thermal_profile");

        if (fanControlPanel != null)
            fanControlPanel.IsVisible = _client.IsFeatureAvailable("fan_speed");

        if (batteryTab != null)
        {
            var hasBatteryFeatures = _client.IsFeatureAvailable("battery_calibration") ||
                                     _client.IsFeatureAvailable("battery_limiter");
            batteryTab.IsVisible = hasBatteryFeatures || _client.IsFeatureAvailable("usb_charging") ||
                                   this.FindControl<BatteryMonitor>("BatteryOverview")!.HasBattery;

            var calibrationControls = nameScope.Find<Border>("CalibrationControls");
            var limiterControls = nameScope.Find<Border>("LimiterControls");

            if (calibrationControls != null)
                calibrationControls.IsVisible = _client.IsFeatureAvailable("battery_calibration");

            if (limiterControls != null)
                limiterControls.IsVisible = _client.IsFeatureAvailable("battery_limiter");
        }

        this.FindControl<Button>("PerKeyEditorButton")!.IsVisible = _client.IsFeatureAvailable("per_key_mode");
        var hasKeyboardFeatures = _client.IsFeatureAvailable("backlight_timeout") ||
                                  _client.IsFeatureAvailable("per_zone_mode") ||
                                  _client.IsFeatureAvailable("four_zone_mode");

        if (keyboardLightingTab != null)
            keyboardLightingTab.IsVisible = hasKeyboardFeatures;

        if (zoneColorControlPanel != null)
            zoneColorControlPanel.IsVisible = _client.IsFeatureAvailable("per_zone_mode");

        if (keyboardEffectsPanel != null)
            keyboardEffectsPanel.IsVisible = _client.IsFeatureAvailable("four_zone_mode");

        if (usbChargingPanel != null)
            usbChargingPanel.IsVisible = _client.IsFeatureAvailable("usb_charging");

        if (systemSettingsTab != null)
        {
            var hasSystemSettings = _client.IsFeatureAvailable("lcd_override") ||
                                    _client.IsFeatureAvailable("boot_animation_sound");

            var backlightControls = nameScope.Find<Border>("BacklightTimeoutControls");
            var lcdControls = nameScope.Find<Border>("LcdOverrideControls");
            var bootSoundControls = nameScope.Find<Border>("BootSoundControls");

            if (backlightControls != null)
                backlightControls.IsVisible = _client.IsFeatureAvailable("backlight_timeout");

            if (lcdControls != null)
                lcdControls.IsVisible = _client.IsFeatureAvailable("lcd_override");

            if (bootSoundControls != null)
                bootSoundControls.IsVisible = _client.IsFeatureAvailable("boot_animation_sound");
        }
    }

    private void UpdateFanReadings()
    {
        string Rpm(string name) => _settings.FanRpm.TryGetValue(name, out var rpm) && rpm >= 0 ? $"{rpm} RPM" : "N/A";
        this.FindControl<TextBlock>("CpuFanRpm")!.Text = Rpm("cpu");
        this.FindControl<TextBlock>("GpuFanRpm")!.Text = Rpm("gpu");
    }

    private async Task RefreshStatusAsync()
    {
        if (_closed || _initializing || _refreshingStatus || _profileChangePending) return;
        _refreshingStatus = true;
        try
        {
            var settings = await _client.GetAllSettingsAsync();
            if (_closed) return;
            var reconnecting = !_isConnected;
            _settings = settings;
            _isConnected = true;
            if (reconnecting) ApplySettingsToUI();
            SetDaemonOverlay(false);
            _applyingSettings = true;
            if (settings.AcOnline.HasValue) _powerToggleSwitch.IsChecked = settings.AcOnline.Value;
            UpdateProfileButtons();
            UpdateFanReadings();
            UpdateUIElementVisibility();
            UpdateSharedLightingControls();
        }
        catch (Exception ex)
        {
            _isConnected = false;
            this.FindControl<TextBlock>("CpuFanRpm")!.Text = "N/A";
            this.FindControl<TextBlock>("GpuFanRpm")!.Text = "N/A";
            SetDaemonOverlay(true);
            UpdateSharedLightingControls();
            Console.WriteLine($"Status refresh: {ex.Message}");
        }
        finally { _applyingSettings = false; _refreshingStatus = false; }
    }

    public async void InitializeAsync()
    {
        if (_closed || _initializing) return;
        _initializing = true;
        try
        {
            _isConnected = await _client.ConnectAsync();
            if (_isConnected)
            {
                SetDaemonOverlay(false);
                await LoadSettingsAsync();
                _statusTimer.Start();
            }
            else
            {
                Console.WriteLine("Daemon unavailable; retrying automatically.");
                SetDaemonOverlay(true);
            }
        }
        catch (Exception ex)
        {
            await ShowMessageBox("Error while initializing", $"Error initializing: {ex.Message}");
            SetDaemonOverlay(true);
        }
        finally { _initializing = false; if (!_closed) _statusTimer.Start(); }
    }

    private async Task LoadSettingsAsync()
    {
        try
        {
            _settings = await _client.GetAllSettingsAsync() ?? new DAMXSettings();
            ApplySettingsToUI();
        }
        catch (Exception ex)
        {
            await ShowMessageBox("Error while loading settings", $"Error loading settings: {ex.Message}");
            SetDaemonOverlay(true);
        }
    }

    private void UpdateProfileButtons()
    {
        if (_settings?.ThermalProfile == null) return;

        var isPluggedIn = _powerToggleSwitch?.IsChecked ?? false;
        var profileConfigs =
            new Dictionary<string, (RadioButton button, string description, bool showOnBattery, bool showOnAC)>
            {
                {
                    "low-power",
                    (_lowPowerProfileButton,
                        "Prioritizes energy efficiency, reduces performance to extend battery life.", true, false)
                },
                { "quiet", (_quietProfileButton, "Minimizes noise, prioritizes low power and cooling.", false, true) },
                {
                    "balanced",
                    (_balancedProfileButton, "Optimal mix of performance and noise for everyday tasks.", true, true)
                },
                {
                    "balanced-performance",
                    (_performanceProfileButton, "Maximizes speed for demanding workloads, higher fan noise", false,
                        true)
                },
                {
                    "performance",
                    (_turboProfileButton, "Unleashes peak power for extreme tasks, loudest fans.", false, true)
                }
            };

        foreach (var config in profileConfigs.Values)
            if (config.button != null)
            {
                config.button.IsVisible = false;
                config.button.IsEnabled = false;
            }

        foreach (var profile in _settings.ThermalProfile.Available)
        {
            var profileKey = profile.ToLower();
            if (profileConfigs.TryGetValue(profileKey, out var config) && config.button != null)
            {
                var canSelect = isPluggedIn || profileKey is "balanced" or "low-power";
                config.button.IsEnabled = canSelect;
                config.button.IsVisible = true;
            }
        }

        foreach (var config in profileConfigs.Values)
            if (config.button != null) config.button.IsChecked = false;
        if (!string.IsNullOrEmpty(_settings.ThermalProfile.Current))
        {
            var currentProfileKey = _settings.ThermalProfile.Current.ToLower();
            if (profileConfigs.TryGetValue(currentProfileKey, out var config) && config.button != null)
            {
                config.button.IsChecked = true;
                if (_thermalProfileInfoText != null)
                    _thermalProfileInfoText.Text = config.description;
            }
        }
    }

    private void ApplySettingsToUI()
    {
        UpdateFanReadings();
        _applyingSettings = true;
        try
        {
        if (_settings.AcOnline.HasValue) _powerToggleSwitch.IsChecked = _settings.AcOnline.Value;
        UpdateProfileButtons();

        SetCheckBox(_backlightTimeoutCheckBox, IsEnabledSetting(_settings.BacklightTimeout));
        SetCheckBox(_batteryLimitCheckBox, IsEnabledSetting(_settings.BatteryLimiter));

        var isCalibrating = IsEnabledSetting(_settings.BatteryCalibration);
        IsCalibrating = isCalibrating;
        SetEnabled(_startCalibrationButton, !isCalibrating);
        SetEnabled(_stopCalibrationButton, isCalibrating);
        SetText(_calibrationStatusTextBlock, isCalibrating ? "Status: Calibrating" : "Status: Not calibrating");

        SetCheckBox(_bootAnimAndSoundCheckBox, IsEnabledSetting(_settings.BootAnimationSound));
        SetCheckBox(_lcdOverrideCheckBox, IsEnabledSetting(_settings.LcdOverride));

        if (_usbChargingComboBox != null)
            _usbChargingComboBox.SelectedIndex = GetUsbChargingIndex(_settings.UsbCharging);

        var cpuSpeed = ApplyFanSpeed(_settings.FanSpeed?.Cpu, ref _cpuFanSpeed, _cpuFanSlider, _cpuFanTextBlock);
        var gpuSpeed = ApplyFanSpeed(_settings.FanSpeed?.Gpu, ref _gpuFanSpeed, _gpuFanSlider, _gpuFanTextBlock);

        var isAutoMode = cpuSpeed == 0 && gpuSpeed == 0;
        var isMaxMode = cpuSpeed == 100 && gpuSpeed == 100;
        var isManualMode = !isAutoMode && !isMaxMode;

        _isManualFanControl = isManualMode;

        if (_autoFanSpeedRadioButton != null)
            _autoFanSpeedRadioButton.IsChecked = isAutoMode;

        if (_maxFanSpeedRadioButton != null)
            _maxFanSpeedRadioButton.IsChecked = isMaxMode;

        if (_manualFanSpeedRadioButton != null)
            _manualFanSpeedRadioButton.IsChecked = isManualMode;

        ApplyKeyboardSettings();

        SetText(_keyBrightnessText, $"{_keyboardBrightness}%");
        SetText(_daemonVersionText, $"v{_settings.Version}");
        SetText(_driverVersionText, _settings.DriverVersion);
        SetText(_laptopTypeText, _settings.LaptopType);
        SetText(_supportedFeaturesTextBlock, string.Join(", ", _settings.AvailableFeatures));
        SetText(_modelNameText, _settings.LaptopType);

        UpdateUIElementVisibility();
        if (_loadedLightingDevice != null && !_lightingApplyPending)
            _lightingDrafts[_loadedLightingDevice] = CaptureLightingDraft();
        LoadLightingTarget();
        }
        finally { _applyingSettings = false; }
    }

    private static bool IsEnabledSetting(string? value)
    {
        return (value ?? "0").Equals("1", StringComparison.OrdinalIgnoreCase);
    }

    private static int GetUsbChargingIndex(string? value)
    {
        return value switch
        {
            "10" => 1,
            "20" => 2,
            "30" => 3,
            _ => 0
        };
    }

    private static int ApplyFanSpeed(
        string? value,
        ref int backingField,
        Slider? slider,
        TextBlock? textBlock)
    {
        if (!int.TryParse(value ?? "0", out var speed))
            return 0;

        backingField = speed;

        if (slider != null)
            slider.Value = speed;

        SetText(textBlock, FormatFanSpeed(speed));

        return speed;
    }

    private static string FormatFanSpeed(int speed)
    {
        return speed == 0 ? "Auto" : $"{speed}%";
    }

    private static void SetCheckBox(CheckBox? checkBox, bool value)
    {
        if (checkBox != null)
            checkBox.IsChecked = value;
    }

    private static void SetRadioButton(RadioButton? radioButton, bool value)
    {
        if (radioButton != null)
            radioButton.IsChecked = value;
    }

    private static void SetEnabled(Control? control, bool value)
    {
        if (control != null)
            control.IsEnabled = value;
    }

    private static void SetText(TextBlock? textBlock, string? value)
    {
        if (textBlock != null)
            textBlock.Text = value ?? string.Empty;
    }

    private void ApplyKeyboardSettings()
    {
        if (!_settings.HasFourZoneKb)
            return;

        ApplyPerZoneSettingsToUI();



    }

    private void ApplyPerZoneSettingsToUI()
    {
        if (!TryParsePerZoneMode(
                _settings.PerZoneMode,
                out var zone1,
                out var zone2,
                out var zone3,
                out var zone4,
                out var brightness))
            return;

        SetColorPicker(_zone1ColorPicker, zone1);
        SetColorPicker(_zone2ColorPicker, zone2);
        SetColorPicker(_zone3ColorPicker, zone3);
        SetColorPicker(_zone4ColorPicker, zone4);

        SetKeyboardBrightness(brightness);
    }

    private async Task ShowMessageBox(string title, string message)
    {
        var box = MessageBoxManager.GetMessageBoxStandard(title, message);
        await box.ShowWindowDialogAsync(this);
    }

    private void RetryConnectionButton_OnClick(object? sender, RoutedEventArgs e)
    {
        InitializeAsync();
    }

    private void Licenses_Click(object? sender, RoutedEventArgs e)
    {
        var folder = Path.Combine(AppContext.BaseDirectory, "licenses");
        Process.Start(new ProcessStartInfo("xdg-open") { ArgumentList = { folder }, UseShellExecute = false });
    }

    private async void PerKeyEditor_Click(object? sender, RoutedEventArgs e)
    {
        if (!_isConnected || _settings == null) return;
        var editor = new PerKeyLightingWindow(_client, _settings);
        await editor.ShowDialog(this);
        if (editor.Applied)
        {
            _lightingDrafts.Remove("keyboard");
            if (_loadedLightingDevice == "keyboard") _loadedLightingDevice = null;
            await LoadSettingsAsync();
        }
    }

    private void InternalsMangerWindow_OnClick(object? sender, RoutedEventArgs e)
    {
        var internalsManagerWindow = new InternalsManager(this);
        internalsManagerWindow.ShowDialog(this);
    }


    private async void ProfileButton_Checked(object sender, RoutedEventArgs e)
    {
        if (_applyingSettings || _profileChangePending || !_isConnected ||
            sender is not RadioButton button || button.IsChecked != true) return;
        var profile = button.Name switch
        {
            "LowPowerProfileButton" => "low-power", "QuietProfileButton" => "quiet",
            "PerformanceProfileButton" => "balanced-performance", "TurboProfileButton" => "performance",
            _ => "balanced"
        };
        _profileChangePending = true;
        this.FindControl<Border>("ThermalProfilePanel")!.IsEnabled = false;
        try
        {
            using var response = await _client.SendCommandAsync("set_thermal_profile", new() { ["profile"] = profile });
            if (!response.RootElement.GetProperty("success").GetBoolean())
                await ShowMessageBox("Profile was not applied", response.RootElement.GetProperty("error").GetString() ?? "Firmware rejected the profile");
            await LoadSettingsAsync();
        }
        catch (Exception ex) { await ShowMessageBox("Profile was not applied", ex.Message); }
        finally
        {
            _profileChangePending = false;
            this.FindControl<Border>("ThermalProfilePanel")!.IsEnabled = true;
            await RefreshStatusAsync();
        }
    }

    private void ManualFanControlRadioBox_Click(object sender, RoutedEventArgs e)
    {
        _isManualFanControl = true;
        if (_manualFanSpeedRadioButton != null) _manualFanSpeedRadioButton.IsChecked = true;
        if (_autoFanSpeedRadioButton != null) _autoFanSpeedRadioButton.IsChecked = false;
    }

    private void CpuFanSlider_ValueChanged(object sender, AvaloniaPropertyChangedEventArgs e)
    {
        if (e.Property == Slider.ValueProperty)
        {
            _cpuFanSpeed = Convert.ToInt32(e.NewValue);
            if (_cpuFanTextBlock != null)
                _cpuFanTextBlock.Text = _cpuFanSpeed == 0 ? "Auto" : $"{_cpuFanSpeed}%";
        }
    }

    private void GpuFanSlider_ValueChanged(object sender, AvaloniaPropertyChangedEventArgs e)
    {
        if (e.Property == Slider.ValueProperty)
        {
            _gpuFanSpeed = Convert.ToInt32(e.NewValue);
            if (_gpuFanTextBlock != null)
                _gpuFanTextBlock.Text = _gpuFanSpeed == 0 ? "Auto" : $"{_gpuFanSpeed}%";
        }
    }

    private async void SetManualSpeedButton_OnClick(object sender, RoutedEventArgs e)
    {
        if (!_isConnected || _isSettingFanSpeed)
            return;

        _isSettingFanSpeed = true;

        if (_setManualSpeedButton != null)
            _setManualSpeedButton.IsEnabled = false;

        try
        {
            await _client.SetFanSpeedAsync(_cpuFanSpeed, _gpuFanSpeed);
            await LoadSettingsAsync();
        }
        catch (Exception ex)
        {
            await ShowMessageBox(
                "Fan Speed Error",
                $"Failed to set fan speed: {ex.Message}"
            );
        }
        finally
        {
            _isSettingFanSpeed = false;

            if (_setManualSpeedButton != null)
                _setManualSpeedButton.IsEnabled = true;
        }
    }

    private async void AutoFanSpeedRadioButtonClick(object sender, RoutedEventArgs e)
    {
        if (_isConnected)
        {
            await ApplyLightingCommandAsync("set_fan_speed", new() { ["cpu"] = 0, ["gpu"] = 0 });
            _isManualFanControl = false;
            if (_manualFanSpeedRadioButton != null) _manualFanSpeedRadioButton.IsChecked = false;
            await LoadSettingsAsync();
        }
    }

    private async void MaxFanSpeedRadioButton_OnClick(object? sender, RoutedEventArgs e)
    {
        if (!_isConnected)
            return;

        _cpuFanSpeed = 100;
        _gpuFanSpeed = 100;
        _isManualFanControl = false;

        if (_cpuFanSlider != null)
            _cpuFanSlider.Value = 100;

        if (_gpuFanSlider != null)
            _gpuFanSlider.Value = 100;

        if (_cpuFanTextBlock != null)
            _cpuFanTextBlock.Text = "100%";

        if (_gpuFanTextBlock != null)
            _gpuFanTextBlock.Text = "100%";

        await ApplyLightingCommandAsync("set_fan_speed", new() { ["cpu"] = 100, ["gpu"] = 100 });
    }

    private async void StartCalibrationButton_Click(object sender, RoutedEventArgs e)
    {
        if (_isConnected)
        {
            if (!await ApplyLightingCommandAsync("set_battery_calibration", new() { ["enabled"] = true })) return;
            if (_startCalibrationButton != null) _startCalibrationButton.IsEnabled = false;
            if (_stopCalibrationButton != null) _stopCalibrationButton.IsEnabled = true;
            if (_calibrationStatusTextBlock != null) _calibrationStatusTextBlock.Text = "Status: Calibrating";
        }
    }

    private async void StopCalibrationButton_Click(object sender, RoutedEventArgs e)
    {
        if (_isConnected)
        {
            if (!await ApplyLightingCommandAsync("set_battery_calibration", new() { ["enabled"] = false })) return;
            if (_startCalibrationButton != null) _startCalibrationButton.IsEnabled = true;
            if (_stopCalibrationButton != null) _stopCalibrationButton.IsEnabled = false;
            if (_calibrationStatusTextBlock != null) _calibrationStatusTextBlock.Text = "Status: Not calibrating";
        }
    }

    private async void BatteryLimitCheckBox_Click(object sender, RoutedEventArgs e)
    {
        if (_isConnected && sender is CheckBox checkBox)
            await ApplyLightingCommandAsync("set_battery_limiter", new() { ["enabled"] = checkBox.IsChecked ?? false });
    }

    private void KeyboardBrightnessSlider_ValueChanged(object sender, AvaloniaPropertyChangedEventArgs e)
    {
        if (e.Property == Slider.ValueProperty)
            SetKeyboardBrightness(Convert.ToInt32(e.NewValue), false);
    }

    private async Task<bool> ApplyLightingCommandAsync(string command, Dictionary<string, object> parameters)
    {
        try
        {
            using var response = await _client.SendCommandAsync(command, parameters);
            if (!response.RootElement.GetProperty("success").GetBoolean())
                throw new InvalidOperationException(response.RootElement.GetProperty("error").GetString());
            await LoadSettingsAsync();
            return true;
        }
        catch (Exception ex)
        {
            await ShowMessageBox("Setting was not applied", ex.Message);
            await LoadSettingsAsync();
            return false;
        }
    }

    private async void ApplyKeyboardColorsButton_Click(object sender, RoutedEventArgs e)
    {
        await ApplyLightingCommandAsync("set_per_zone_mode", new()
        {
            ["zone1"] = ToRgbHex(_zone1ColorPicker.Color), ["zone2"] = ToRgbHex(_zone2ColorPicker.Color),
            ["zone3"] = ToRgbHex(_zone3ColorPicker.Color), ["zone4"] = ToRgbHex(_zone4ColorPicker.Color),
            ["brightness"] = _keyboardBrightness
        });
    }

    private readonly Dictionary<string, LightingDraft> _lightingDrafts = new();
    private string? _loadedLightingDevice;
    private bool _lightingApplyPending;
    private bool _loadingLighting;
    private bool _lightingUiReady;
    private string LightingDevice => (this.FindControl<ComboBox>("LightingTarget")?.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "keyboard";
    private int LightingEffect => this.FindControl<ComboBox>("SharedEffects")?.SelectedIndex ?? 0;
    private void LightingTargetChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (_loadingLighting || !_lightingUiReady) return;
        if (_loadedLightingDevice != null)
            _lightingDrafts[_loadedLightingDevice] = CaptureLightingDraft();
        this.FindControl<TextBlock>("LightingResult")!.Text = "";
        LoadLightingTarget();
    }

    private LightingDraft CaptureLightingDraft() => new(
        LightingEffect, this.FindControl<TextBox>("SharedColorHex")!.Text ?? "#FF2300",
        (int)(this.FindControl<NumericUpDown>("SharedBrightness")!.Value ?? 100),
        (int)this.FindControl<Slider>("SharedSpeed")!.Value,
        this.FindControl<ComboBox>("SharedDirection")!.SelectedIndex + 1,
        this.FindControl<CheckBox>("LinkWasd")!.IsChecked == true);
    private void SharedEffectChanged(object? sender, SelectionChangedEventArgs e) => UpdateSharedLightingControls();

    private void LoadLightingTarget()
    {
        if (_settings == null || _loadingLighting) return;
        var effects = this.FindControl<ComboBox>("SharedEffects");
        if (effects == null) return;
        _loadingLighting = true;
        try
        {
            var target = LightingDevice;
            foreach (ComboBoxItem item in this.FindControl<ComboBox>("LightingTarget")!.Items)
                item.IsEnabled = _settings.LightingModes.ContainsKey(item.Tag!.ToString()!);
            var supported = _settings.LightingModes.TryGetValue(target, out var modes) ? modes : new List<int>();
            foreach (ComboBoxItem item in effects.Items)
                item.IsEnabled = supported.Contains(int.Parse(item.Tag!.ToString()!));
            var draft = _lightingDrafts.TryGetValue(target, out var cached) ? cached :
                LightingDraft.FromState(_settings.LightingState.TryGetValue(target, out var state) ? state : default);
            effects.SelectedIndex = supported.Contains(draft.Mode) ? draft.Mode : supported.Count > 0 ? supported[0] : -1;
            SetSharedColor(NormalizeRgbHex(draft.Color) is { } hex ? "#" + hex : "#FF2300");
            this.FindControl<TextBox>("SharedColorHex")!.Text = draft.Color;
            this.FindControl<NumericUpDown>("SharedBrightness")!.Value = draft.Brightness;
            this.FindControl<Slider>("SharedSpeed")!.Value = draft.Speed;
            this.FindControl<ComboBox>("SharedDirection")!.SelectedIndex = draft.Direction - 1;
            this.FindControl<CheckBox>("LinkWasd")!.IsChecked = draft.LinkWasd;
            _loadedLightingDevice = target;
        }
        finally { _loadingLighting = false; }
        UpdateSharedLightingControls();
    }

    private void UpdateSharedLightingControls()
    {
        if (!_lightingUiReady) return;
        var picker = this.FindControl<ColorView>("SharedColor");
        if (picker == null) return;
        var palette = LightingEffect is 2 or 3;
        picker.IsEnabled = !palette;
        this.FindControl<TextBox>("SharedColorHex")!.IsEnabled = !palette;
        this.FindControl<StackPanel>("LightingSwatches")!.IsEnabled = !palette;
        this.FindControl<ComboBox>("SharedDirection")!.IsVisible = LightingEffect == 3;
        this.FindControl<CheckBox>("LinkWasd")!.IsVisible = LightingDevice == "keyboard";
        this.FindControl<Slider>("SharedSpeed")!.IsEnabled = LightingEffect != 0 && LightingDevice != "logo";
        this.FindControl<TextBlock>("SharedEffectNote")!.Text =
            LightingEffect == 3 && LightingDevice is "keyboard" or "wasd"
                ? "Wave uses the firmware palette. Linked keyboard and WASD share speed and direction, but their animations run independently."
                : LightingDevice == "all"
                    ? "Applies to every detected light. Shared effects only; device animation timing may differ."
                    : palette ? "This effect uses its native color palette."
                    : LightingDevice == "keyboard"
                        ? "WASD follows matching effects with independent animation timing; for other effects it uses the selected static color."
                        : "Your color and brightness apply to the selected device.";
        if ((LightingDevice is "keyboard" or "wasd") && _settings?.LightingState.TryGetValue(LightingDevice, out var last) == true &&
            last.ValueKind == System.Text.Json.JsonValueKind.Object && last.TryGetProperty("kind", out var kind) && kind.GetString() == "per_key")
            this.FindControl<TextBlock>("SharedEffectNote")!.Text = "Last applied: per-key colors. Apply replaces them with the selected effect.";
        var device = this.FindControl<ComboBox>("LightingTarget")!.SelectedItem as ComboBoxItem;
        this.FindControl<Button>("SharedApply")!.Content = "Apply to " + device?.Content;
        this.FindControl<Button>("SharedApply")!.IsEnabled = !_lightingApplyPending && _isConnected && LightingEffect >= 0;
    }

    private void SetSharedColor(string hex)
    {
        var color = Color.Parse(hex);
        this.FindControl<ColorView>("SharedColor")!.Color = color;
        this.FindControl<TextBox>("SharedColorHex")!.Text = $"#{color.R:X2}{color.G:X2}{color.B:X2}";
    }
    private void SharedColorChanged(object? sender, AvaloniaPropertyChangedEventArgs e)
    {
        if (e.Property == ColorPicker.ColorProperty)
        {
            var color = this.FindControl<ColorView>("SharedColor")!.Color;
            this.FindControl<TextBox>("SharedColorHex")!.Text = $"#{color.R:X2}{color.G:X2}{color.B:X2}";
        }
    }
    private void LightingSwatch_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button button) SetSharedColor(button.Tag!.ToString()!);
    }
    private void LightingHexLostFocus(object? sender, RoutedEventArgs e)
    {
        try { SetSharedColor(this.FindControl<TextBox>("SharedColorHex")!.Text!); }
        catch { this.FindControl<TextBlock>("LightingResult")!.Text = "Enter a color as #RRGGBB."; }
    }
    private async void SharedLightingApply_Click(object? sender, RoutedEventArgs e)
    {
        var button = this.FindControl<Button>("SharedApply")!;
        var status = this.FindControl<TextBlock>("LightingResult")!;
        if (_lightingApplyPending) return;
        _lightingApplyPending = true;
        this.FindControl<Border>("KeyboardEffectsPanel")!.IsEnabled = false;
        try
        {
            var hex = LightingEffect is 2 or 3 ? ToRgbHex(this.FindControl<ColorView>("SharedColor")!.Color) :
                this.FindControl<TextBox>("SharedColorHex")!.Text?.Trim().TrimStart('#');
            if (hex == null || !System.Text.RegularExpressions.Regex.IsMatch(hex, "^[0-9a-fA-F]{6}$"))
                throw new ArgumentException("Enter a color as #RRGGBB.");
            var target = LightingDevice;
            status.Text = "Applying…";
            using var result = await _client.SendCommandAsync("set_lighting", new()
            {
                ["target"] = target, ["mode"] = LightingEffect, ["color"] = hex,
                ["brightness"] = (int)(this.FindControl<NumericUpDown>("SharedBrightness")!.Value ?? 100),
                ["speed"] = (int)this.FindControl<Slider>("SharedSpeed")!.Value,
                ["direction"] = this.FindControl<ComboBox>("SharedDirection")!.SelectedIndex + 1,
                ["link_wasd"] = this.FindControl<CheckBox>("LinkWasd")!.IsChecked == true
            });
            if (target == "all") _lightingDrafts.Clear();
            else _lightingDrafts.Remove(target);
            if (target == "keyboard" && this.FindControl<CheckBox>("LinkWasd")!.IsChecked == true)
                _lightingDrafts.Remove("wasd");
            var effectName = (this.FindControl<ComboBox>("SharedEffects")!.SelectedItem as ComboBoxItem)?.Content;
            status.Text = $"Applied {effectName} to {target}" + (LightingEffect is 2 or 3 ? "." : $": #{hex.ToUpperInvariant()}.");
            await LoadSettingsAsync();
        }
        catch (Exception ex) { status.Text = "Could not apply: " + ex.Message; }
        finally { _lightingApplyPending = false; this.FindControl<Border>("KeyboardEffectsPanel")!.IsEnabled = true; UpdateSharedLightingControls(); }
    }

    private async void BacklightTimeoutCheckBox_Click(object sender, RoutedEventArgs e)
    {
        if (_isConnected && sender is CheckBox checkBox)
            await ApplyLightingCommandAsync("set_backlight_timeout", new() { ["enabled"] = checkBox.IsChecked ?? false });
    }

    private async void LcdOverrideCheckBox_Click(object sender, RoutedEventArgs e)
    {
        if (_isConnected && sender is CheckBox checkBox)
            await ApplyLightingCommandAsync("set_lcd_override", new() { ["enabled"] = checkBox.IsChecked ?? false });
    }

    private async void BootSoundCheckBox_Click(object sender, RoutedEventArgs e)
    {
        if (_isConnected && sender is CheckBox checkBox)
            await ApplyLightingCommandAsync("set_boot_animation_sound", new() { ["enabled"] = checkBox.IsChecked ?? false });
    }

    private async void UsbChargingComboBox_OnSelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (!_applyingSettings && _isConnected && _usbChargingComboBox != null)
        {
            var level = _usbChargingComboBox.SelectedIndex switch
            {
                1 => 10,
                2 => 20,
                3 => 30,
                _ => 0
            };
            await ApplyLightingCommandAsync("set_usb_charging", new() { ["level"] = level });
        }
    }

    private void SetKeyboardBrightness(int brightness, bool updateSlider = true)
    {
        _keyboardBrightness = brightness;

        if (updateSlider && _keyBrightnessSlider != null)
            _keyBrightnessSlider.Value = brightness;

        SetText(_keyBrightnessText, $"{brightness}%");
    }

    private static string ToRgbHex(Color color)
    {
        return $"{color.R:X2}{color.G:X2}{color.B:X2}";
    }

    private static void SetColorPicker(ColorPicker? picker, string rgbHex)
    {
        if (picker == null)
            return;

        var normalized = NormalizeRgbHex(rgbHex);
        if (normalized == null)
            return;

        picker.Color = Color.Parse($"#{normalized}");
    }

    private static string? NormalizeRgbHex(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return null;

        var hex = value.Trim();

        if (hex.StartsWith('#'))
            hex = hex[1..];

        if (hex.Length != 6)
            return null;

        foreach (var c in hex)
            if (!Uri.IsHexDigit(c))
                return null;

        return hex.ToUpperInvariant();
    }

    private static bool TryParsePerZoneMode(
        string? value,
        out string zone1,
        out string zone2,
        out string zone3,
        out string zone4,
        out int brightness)
    {
        zone1 = "";
        zone2 = "";
        zone3 = "";
        zone4 = "";
        brightness = 100;

        if (string.IsNullOrWhiteSpace(value))
            return false;

        var parts = value.Trim().Split(',', StringSplitOptions.TrimEntries);

        if (parts.Length != 5)
            return false;

        zone1 = NormalizeRgbHex(parts[0]) ?? "";
        zone2 = NormalizeRgbHex(parts[1]) ?? "";
        zone3 = NormalizeRgbHex(parts[2]) ?? "";
        zone4 = NormalizeRgbHex(parts[3]) ?? "";

        if (zone1.Length != 6 ||
            zone2.Length != 6 ||
            zone3.Length != 6 ||
            zone4.Length != 6)
            return false;

        if (!int.TryParse(parts[4], out brightness))
            return false;

        return brightness is >= 0 and <= 100;
    }


    public new event PropertyChangedEventHandler? PropertyChanged;
    protected bool SetField<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return false;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        return true;
    }

}
