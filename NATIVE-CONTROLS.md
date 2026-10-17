# Native control implementation and evidence

## Reference software

Acer's supplied PH16-72 package: PredatorSense 5.0.1463, W11x64.

Archive SHA-256: `f065461f7c0230624640226c75e5a55780626caf844f4957ea6cd0818651d88c`.

Reference URL: https://global-download.acer.com/GDFiles/Application/Predator%20Sense/Predator%20Sense_Acer_5.0.1463_W11x64_A.zip?acerid=638858095496061843&Step3=PREDATOR%20PH16-72

The archive was unpacked without executing its Windows binaries. `RGBDevice.ini`, model definitions, Electron application scripts, and the following DLL disassemblies informed the implementation. Proprietary binaries and source are not included in this repository.

- `SunrexUSBKeyboard.dll`, effect routine RVA `0x1800`: B1, prepare 08/02, apply 08/02, then 14 RGB. Wave uses the direction field; other effects set it to zero. Each feature report is nine bytes with the final one's-complement checksum. Speed is encoded as `10 - UI speed`.
- `DarfonUSBLogo.dll`, actual logo UpdateMode RVA `0x9740` -> SetMode RVA `0x1e20`: B1, prepare 08/02, color 14/00/00/R/G/B/00, apply 08/03/nativeMode/11/brightness/randomFlag/direction. Speed field 11 is fixed. The earlier direct-transfer routine RVA `0x13f0` and SetMode RVA `0x16c0` are keyboard paths and did not change this logo. Static/Breathing/Neon/Rain firmware IDs are 1/2/8/10.
- Sunrex's MAG key path uses native IDs 0x41 static, 0x42 breathing, 0x43 wave, 0x44 snake, 0x45 neon, and color-command scope 1 instead of scope 0. WASD is a separate device in the original app. The shared editor supports independent WASD control and optional keyboard linking.
- `AcerECLightbarController.dll`, rear SetMode RVA `0x2ed0`, RGB controller update RVA `0xfa00`, WMI wrapper RVA `0x11500`: `AcerGamingFunction.SetGamingKBBacklight`, method 20, sixteen-byte input. Static mode is 0. Packet is `[mode,speed,brightness,0,direction+1,R,G,B,3,2,0,0,0,0,0,0]`. Selector 2 identifies the EC lighting path; the older keyboard command uses selector 1. The bridge exposes the original static, breathing, neon, and wave mode values, with validated speed, brightness, direction, and RGB fields.
- Original app uses PH16-72 model classes `Helios_Etron_RTX` for keyboard and `Etron_RTX_16` for rear lighting. Some modes use a firmware color palette. An arbitrary color is not promised for those modes.

The public [Helios RGB protocol notes](https://github.com/TensorRaya/acer-predator-helios-rgb) were consulted as a cross-check, but describe a PH16-73 with different Darfon hardware. Its initial vendor-mode sequence was replaced with the supplied PH16-72 DLL sequence. The PH16-73 bar devices were not assumed present on this laptop.

## Actual Linux interfaces

Observed host: Predator PH16-72, BIOS V1.10, Fedora kernel 7.2.8-200.fc44.x86_64, NVIDIA 4080 Laptop GPU, driver 615.71.09.

- Stock Acer platform-profile choices: low-power, quiet, balanced, balanced-performance, performance.
- Stock Acer hwmon: fan1/2, pwm1/2, pwm1/2_enable. PWM is 0–255; enable 2 means auto, 0 means maximum, 1 means manual.
- Keyboard 05af:666a: a 103-lamp LampArray collection and separate FF02 vendor collection.
- Lid logo 0d62:ba51: FF01 vendor HID collection.
- No separate USB rear lightbar was detected.
- Firmware ACPI WMI gaming GUID `7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56`, WMBH method 0x14, accepts the original sixteen-byte command. The unmodified Linux Acer driver does not expose this bar operation. The optional module binds this GUID and adds root-only `color` and `effect` attributes; it does not replace stock Acer controls.

There is no raw EC or physical-memory access. The bridge validates four integers and constructs a single constrained lighting command. It checks the firmware response before reporting success. This BIOS declares the BHSK result as a four-byte buffer; both four- and eight-byte zero results are handled.

## Validation

The backend regression suite covers profile readback and external changes, rejected commands, fan validation and failure recovery, full Darfon transfers, original Sunrex packet ordering/checksums, failed-state persistence, and fragmented/coalesced/malformed JSON socket requests. GUI builds with .NET 8 and the module builds against the installed kernel headers.

Hardware smoke testing accepted stock profile read/write, automatic fan mode, keyboard effect, lid-logo transfer, and rear lightbar commands. The optional bridge was installed through DKMS and the native daemon is enabled and running. The actual C# client passed concurrent reads, rejected-command handling, and reconnection against the installed restricted socket. The initial blue test was insufficient: later orange-red commands revealed that the old logo path and initial bar static command did not change visible colors. After correcting the logo-specific mode routine and applying the bar native breathing command, the user confirmed that the logo and bar changed. The user also confirmed independent red WASD and a steady orange-red bar after Breathing → Static. The daemon now loads the bar color through Breathing before applying Static, because a direct Static command retains its previous RGB on this firmware. A regression test covers this sequence and failure-state preservation. The dashboard query succeeded with temperature, utilization, used VRAM, and total VRAM; all 24 physical cores have frequency readings. switcherooctl successfully set the NVIDIA render-offload environment.

## Scope limits

- HID lighting state shown after restart is persisted successful command state, not a verified firmware query. Failed writes never become successful saved state.
- Physical MUX/Optimus display switching is unavailable through the detected interfaces. The graphics control card and NVIDIA application launcher were removed at the user’s request.
- Battery charge threshold and Acer extras are offered only when their stock kernel attributes exist. This host does not expose most optional extras.
- NVIDIA GPU monitoring is opt-in. Per-core GHz values are sampled `scaling_cur_freq` readings averaged across the logical threads of each physical core.

## Desktop portal and editor fixes

The previous first-login `sg damx` launcher changed the GUI group credentials, making `/proc/<GUI PID>/root` inaccessible to the file chooser portal. The launcher now executes normally; the root daemon assigns the control socket to the installing desktop UID and the damx group, with mode 0660. The GUI has real/effective UID and GID 1000 and its process root is readable by the desktop session.

Lighting now uses one device/effect editor for Keyboard, WASD, Logo, and Bar. Unsupported effects are disabled per device. Explicit hex input and color swatches accompany the color picker; apply feedback identifies the device and submitted color. Four static keyboard zones remain in a collapsed advanced section. The installer stages the GUI in a new directory and swaps it in, so updating an open executable no longer fails with ETXTBSY.

## Follow-up review

See [REVIEW.md](REVIEW.md) for current findings and validation limits. The MSI's PH16-72 configuration independently confirms MAG/WASD, rear bar, MCU logo, and interactive lighting support. Newly identified feature candidates remain proposals until their Linux paths are verified.

## Per-key editor and global lighting sync

The PH16-72 keyboard reports 103 programmable LampArray LEDs. Lamp attribute reports include X/Y geometry and InputBinding keyboard usages; the editor reads these rather than importing another model's key map. Fields and key usage semantics follow the [USB lighting specification](https://www.usb.org/sites/default/files/hutrr84_-_lighting_and_illumination_page.pdf). Unbound lamps are displayed by LED ID instead of guessing their key names. Host static layouts use validated full LampMultiUpdate frames, with brightness scaling before transfer.

get_keyboard_layout returns geometry without changing colors. set_per_key validates every lamp/color before transfer and saves the unscaled colors and brightness only after successful transfer. The current per-key visual test assigns W red, A green, S blue, D yellow, Q magenta, and Esc cyan; visible confirmation is pending.

Global sync uses the intersection of detected device effects: Static, Breathing, and Neon on this laptop. It applies each native controller, records each successful device, and reports the failed target and already-applied targets if a later write fails. This is coordinated mode/color selection, not phase-locked firmware animation. A static blue sync was accepted for keyboard, WASD, logo, and bar, then the per-key test layout was restored.

## Keyboard/WASD Wave timing

Keyboard Wave selects firmware effect `0x03`; MAG/WASD Wave selects `0x43`.
`set_lighting` with `target=keyboard` and `link_wasd=true` sends both the same
speed, brightness, and direction, in separate validated command sequences. The
verified PH16-72 commands have no phase, common clock, or shared start trigger.
Matching parameters must not be described as phase-locked or spatially continuous
Wave. No guessed firmware command or periodic animation reset is used to claim
synchronization. Software per-key animation would need physical WASD coverage
and frame-rate validation before being offered as a replacement.
