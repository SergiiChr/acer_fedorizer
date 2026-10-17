# Compatibility

This native edition targets **Predator PH16-72** and was built and tested on Fedora with Linux 7.2.8 and BIOS V1.10. Other models are not verified.

Core controls require the stock `acer_wmi` platform-profile and hwmon interfaces. RGB discovery uses the actual USB devices and HID descriptors. The optional EC rear lightbar module refuses other DMI models.

Older kernels may not provide the required Acer fan/profile interfaces. Missing features are hidden. See [NATIVE-CONTROLS.md](NATIVE-CONTROLS.md) for detected hardware and [README.md](README.md) for installation.
