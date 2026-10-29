# Compatibility

This native edition targets the **Predator PH16-72**, tested on Fedora with Linux 7.2.8 and BIOS V1.10.
Other models are not verified.

Core controls need the stock `acer_wmi` platform-profile and hwmon interfaces.
Older kernels may lack them; missing features are hidden.
RGB lighting is found from the actual USB devices and their HID descriptors.
The rear lightbar module refuses to load on any other DMI model.

The app needs Python 3.12+, GTK 4.10+, and libadwaita 1.4+.
Automatic setup supports Fedora, Ubuntu 24.04, and Debian 13.
Other desktops can run the app, but display color management needs a GNOME/Mutter session.

See [NATIVE-CONTROLS.md](NATIVE-CONTROLS.md) for detected hardware and [README.md](README.md) for installation.
