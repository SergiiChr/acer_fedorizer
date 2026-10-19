# Frequently asked questions

**Will NVIDIA updates require reinstalling DAMX?**
Core controls are independent of NVIDIA and use stock kernel drivers. The optional bar module uses DKMS to rebuild after kernel updates. Its build still requires matching kernel headers.

**Why does the performance selection change?**
It displays the stock driver's current profile every two seconds, including changes made through the hardware button or another application. It does not apply a profile merely because you opened DAMX.

**Why can't I change a color for every effect?**
Neon and Wave use firmware palettes in the native interface. Other listed effects send the separate color command used by Acer's original software. Lighting state is the last successful command; hardware effect readback has not been verified.

**Is MUX/Optimus switching supported?**
No. The detected interfaces do not support a physical display MUX switch, so this control has been removed.

**Why is VRAM monitoring paused?**
GPU monitoring is opt-in because NVIDIA queries may wake the discrete GPU. Enable it on the dashboard to collect GPU metrics and VRAM history.

**Where are the missing battery/USB/extras controls?**
They appear only when supported stock kernel attributes exist. This firmware does not expose most optional controls.

**Where are logs and settings?**
Use `journalctl -u damx-daemon.service -b` for service logs. Successful lighting
commands are saved in `/var/lib/damx/lighting.json`. Reinstalling with `./setup.sh install` resets this state after asking for
confirmation.

**What should I do if installation fails?**
Run `./setup.sh status`. It checks the application files, service, socket reply,
and rear lightbar driver for your running kernel and shows repair instructions.
Install automatically includes matching kernel headers and all dependencies.
After a kernel update, reboot before reinstalling so the running kernel and
available headers match. Secure Boot can require enrolling the distribution's
DKMS signing key; a module load failure is reported instead of claiming success.

**What does uninstall remove?**
`./setup.sh uninstall` removes the application, service, desktop launcher/icon,
control socket, lighting state, old installation backups, socket-access group,
and every DAMX lightbar DKMS version and its installed module/source files.
Repeated uninstall is safe. Shared OS packages and this downloaded folder stay.
It does not revert desktop color-management choices already saved in Mutter.

**Can keyboard and WASD Wave run as one synchronized wave?**
The link option sends matching effect, speed, brightness, and direction to the
keyboard and WASD firmware effects. Those effects run independently: the verified
PH16-72 protocol exposes no shared phase/clock or spatial-wave synchronization
command. Reapplying both is not a guarantee of phase alignment. A single wave
across all keys would require software animation through per-key LampArray
frames, including confirming physical WASD coverage and usable frame rates on
this keyboard. That animation is not currently implemented.
