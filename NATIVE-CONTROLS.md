# Native controls

How each hardware control works on the PH16-72, where the protocol comes from, and what has been confirmed on real hardware.

## Reference software

Acer's PH16-72 package: PredatorSense 5.0.1463, W11x64.

Archive SHA-256: `f065461f7c0230624640226c75e5a55780626caf844f4957ea6cd0818651d88c`.

Reference URL: https://global-download.acer.com/GDFiles/Application/Predator%20Sense/Predator%20Sense_Acer_5.0.1463_W11x64_A.zip?acerid=638858095496061843&Step3=PREDATOR%20PH16-72

The archive was unpacked without running its Windows binaries.
`RGBDevice.ini`, model definitions, Electron app scripts, and the DLL disassemblies below informed the implementation.
Proprietary binaries and source are not in this repository.

The original app uses PH16-72 model classes `Helios_Etron_RTX` for the keyboard and `Etron_RTX_16` for rear lighting.
The package's MSI installer configuration for PH16-72 independently confirms MAG/WASD, rear bar, MCU logo, and interactive lighting support.
Some modes on every device use a firmware color palette; the app does not offer an arbitrary color for those modes.

The public [Helios RGB protocol notes](https://github.com/TensorRaya/acer-predator-helios-rgb) were a cross-check only.
They describe a PH16-73 with different Darfon hardware, so their vendor-mode start sequence is replaced by the PH16-72 DLL sequence, and their PH16-73 bar devices are not assumed present.

## Linux interfaces

Observed host: Predator PH16-72, BIOS V1.10, Fedora kernel 7.2.8-200.fc44.x86_64, NVIDIA 4080 Laptop GPU, driver 615.71.09.

- Stock Acer platform profiles: low-power, quiet, balanced, balanced-performance, performance.
- Stock Acer hwmon: fan1/2, pwm1/2, pwm1/2_enable. PWM is 0–255; enable 2 means auto, 0 means maximum, 1 means manual.
- Keyboard 05af:666a: a 103-lamp LampArray collection and a separate FF02 vendor collection.
- Lid logo 0d62:ba51: FF01 vendor HID collection.
- Rear lightbar: no USB device; reached through firmware WMI (see below).
- Battery charge limit and Acer extras appear only when their stock kernel attributes exist; this host exposes few of them.
- Physical MUX/Optimus switching is not available through any detected interface, so the app has no such control.

There is no raw EC or physical-memory access.

## Keyboard (Sunrex)

Source: `SunrexUSBKeyboard.dll`, effect routine RVA `0x1800`.

- Sequence: B1, prepare 08/02, apply 08/02, then 14 RGB.
- Each feature report is nine bytes ending with a one's-complement checksum.
- Wave uses the direction field; other effects set it to zero.
- Speed is sent as `10 - UI speed`.
- Neon and Wave use firmware palettes, so the app does not offer an arbitrary color for them.
- Four static zones are a keyboard choice; zone colors are sent at full value without brightness scaling.

## WASD (MAG keys)

- Same Sunrex device, with native IDs 0x41 static, 0x42 breathing, 0x43 wave, 0x44 snake, 0x45 neon.
- The color command uses scope 1 instead of scope 0.
- WASD is a separate device; the editor controls it on its own or linked to the keyboard.
- MAG Wave takes one mode-specific color, unlike the keyboard Wave palette (`SunrexUSBKeyboard.dll` SHA-256 `f02e26d1f831988ef7fdefee776502002fbfef1225e91f15fb73444d8304414f`). The editor lets you set it and sends it.

### Linked Wave

Keyboard Wave is effect `0x03`; WASD Wave is `0x43`.
`set_lighting` with `target=keyboard` and `link_wasd=true` sends both the same speed, brightness, and direction as two separate validated sequences.
The verified commands have no phase, shared clock, or common start trigger, so the two waves are not synchronized and must not be described that way.
No guessed command or periodic reset is used to fake synchronization.
A single wave across all keys would need software per-key animation, which needs confirmed physical WASD coverage and a usable frame rate first.

## Per-key lighting (LampArray)

The keyboard reports 103 programmable LEDs.
Lamp attribute reports include X/Y position and the bound key usage, and the editor draws the keyboard from them instead of using another model's key map.
Fields and key usages follow the [USB lighting specification](https://www.usb.org/sites/default/files/hutrr84_-_lighting_and_illumination_page.pdf).
Lamps without a key binding are shown by LED ID.

- `get_keyboard_layout` returns the geometry without changing colors.
- `set_per_key` validates every lamp and color, scales by brightness, and sends full LampMultiUpdate frames.
- Unscaled colors and brightness are saved only after the transfer succeeds.

## Lid logo (Darfon)

Source: `DarfonUSBLogo.dll`, UpdateMode RVA `0x9740` → SetMode RVA `0x1e20`.

- Sequence: B1, prepare 08/02, color 14/00/00/R/G/B/00, apply 08/03/nativeMode/11/brightness/randomFlag/direction.
- Speed field 11 is fixed.
- Firmware IDs: Static 1, Breathing 2, Neon 8, Rain 10.
- Routines at RVA `0x13f0` and `0x16c0` are keyboard paths and do not change the logo.

## Rear lightbar (EC via WMI)

Source: `AcerECLightbarController.dll`, SetMode RVA `0x2ed0`, RGB update RVA `0xfa00`, WMI wrapper RVA `0x11500`.

- Call: `AcerGamingFunction.SetGamingKBBacklight`, method 20, sixteen-byte input.
- Packet: `[mode,speed,brightness,0,direction+1,R,G,B,3,2,0,0,0,0,0,0]`.
- Selector 2 picks the EC lighting path; selector 1 is the older keyboard command.
- Modes: static 0, plus the original breathing, neon, and wave values.
- A direct Static command keeps the previous RGB on this firmware, so the daemon sends the color through Breathing first, then Static.

The stock Linux Acer driver does not expose this call.
`native-lightbar/` binds firmware WMI GUID `7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56` (WMBH method 0x14) and adds root-only `color` and `effect` attributes beside the stock controls.
It validates four integers, builds one constrained command, and checks the firmware reply before reporting success.
This BIOS declares a four-byte BHSK result; both four- and eight-byte zero results are accepted.

## All-lights sync

Sync offers only effects every detected device supports: Static, Breathing, and Neon on this laptop.
It applies each device in turn and saves each one that succeeds.
If one fails, it reports the failed device and the ones already applied.
It sets matching modes and colors; the animations are not phase-locked.

## Saved state and replay

Lighting shown after a restart is the last successful command, not a reading from the device.
Failed writes are never saved.
The service replays saved lighting at start, after sleep (`fedorizer-resume.service` runs `systemctl reload`), and when a hidraw device reconnects.
Replay never changes the saved state.

## Telemetry

- NVIDIA monitoring is off until the user turns it on.
- Per-core GHz is the `scaling_cur_freq` average over each physical core's threads.

## Hardware status

"Accepted" means the device took the command; "seen" means a person confirmed the visible result.

| Control | Status |
| --- | --- |
| Platform profile read/write | Accepted |
| Automatic fan mode | Accepted |
| Keyboard effect | Accepted |
| Logo color via `0x1e20` path | Seen |
| Bar color via Breathing → Static | Seen, steady orange-red |
| WASD independent static color | Seen, red |
| Sync Static blue on keyboard, WASD, logo, bar | Accepted |
| Per-key test (W red, A green, S blue, D yellow, Q magenta, Esc cyan) | Accepted; not yet seen |
| WASD Wave, reverse direction, medium speed | Accepted, but WASD stayed dark |
| NVIDIA telemetry (temperature, use, VRAM) | Working; all 24 physical cores report frequency |
| `switcherooctl` NVIDIA offload environment | Working |

WASD Wave darkness: the saved command had nonzero RGB and brightness, so the cause is unknown.
The user reports WASD comes back after moving brightness back and forth and accepts that.
No automatic retry or extra firmware workaround is used.

Not yet verified on hardware:

- Physical per-key and WASD lamp coverage.
- Appearance of animated effects.
- Phase alignment of linked or synced Wave.
- The service sandbox limits (see CONTRIBUTING.md).
- Secure Boot module signing.
- Clean-machine install on each supported distribution.
