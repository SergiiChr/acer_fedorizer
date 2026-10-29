# Frequently asked questions

**Will NVIDIA updates require reinstalling Acer Fedorizer?**
No.
Core controls use stock kernel drivers, not NVIDIA.
The lightbar module rebuilds through DKMS after kernel updates, which needs matching kernel headers.

**Why does the performance selection change on its own?**
The app shows the stock driver's current profile every two seconds, including changes from the hardware button or another app.
Opening the app never applies a profile.

**Why can't I change the color for every effect?**
Neon and Wave use firmware palettes.
Other effects send the separate color command used by Acer's original software.

**Is MUX/Optimus switching supported?**
No.
The detected interfaces have no physical display MUX switch.

**Why is VRAM monitoring paused?**
GPU monitoring is opt-in because NVIDIA queries may wake the discrete GPU.
Turn it on in the dashboard to collect GPU metrics and VRAM history.

**Where are the battery, USB, and other extra controls?**
They appear only when the stock kernel exposes them.
This firmware exposes few of them.

**Where are logs and settings?**
Service logs: `journalctl -u fedorizer-daemon.service -b`.
Successful lighting commands are saved in `/var/lib/acer-fedorizer/lighting.json`.
Reinstalling with `./setup.sh install` resets them after asking.

**What should I do if installation fails?**
Run `./setup.sh status`.
It checks the app files, service, socket reply, and lightbar driver for your running kernel, and shows how to fix problems.
Install pulls in matching kernel headers and all dependencies.
After a kernel update, reboot before reinstalling so the running kernel matches the headers.
With Secure Boot you may need to enroll your distribution's DKMS signing key; a failed module load is reported, not hidden.

**What does uninstall remove?**
`./setup.sh uninstall` removes the app, service, launcher and icon, control socket, saved lighting, old backups, the socket-access group, and every lightbar DKMS version with its files.
Running it twice is safe.
Shared OS packages and the downloaded folder stay.
Color-management choices already saved in Mutter are not reverted.

**Can keyboard and WASD Wave run as one synchronized wave?**
No.
Linking sends the same effect, speed, brightness, and direction to both, but the firmware runs them independently with no shared clock.
One wave across all keys would need software per-key animation, which is not implemented.
See [NATIVE-CONTROLS.md](NATIVE-CONTROLS.md#linked-wave).
