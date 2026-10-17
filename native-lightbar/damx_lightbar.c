// SPDX-License-Identifier: GPL-2.0-only
/* PH16-72 rear lightbar. Protocol derived from Acer's 5.0.1463 DLL:
 * Rear SetMode RVA 0x2ed0 -> SetGamingKBBacklight RVA 0x11500.
 * This interface exposes static, breathing, neon and wave with validated fields.
 */
#include <linux/module.h>
#include <linux/wmi.h>
#include <linux/dmi.h>
#include <linux/mutex.h>
#include <linux/slab.h>

static DEFINE_MUTEX(lightbar_lock);

static ssize_t apply_light(struct device *dev, const char *buf, size_t count, bool effect)
{
    unsigned int r, g, b, brightness, mode = 0, speed = 1, direction = 1;
    char extra;
    u8 packet[16] = {0, 1, 100, 0, 1, 0, 0, 0, 3, 2};
    struct acpi_buffer in = {sizeof(packet), packet};
    struct acpi_buffer out = {ACPI_ALLOCATE_BUFFER, NULL};
    union acpi_object *obj;
    acpi_status status;
    int ret = -EIO;

    if (effect) {
        if (sscanf(buf, "%u %u %u %u %u %u %u %c", &mode, &speed, &brightness,
                   &direction, &r, &g, &b, &extra) != 7)
            return -EINVAL;
    } else if (sscanf(buf, "%u %u %u %u %c", &r, &g, &b, &brightness, &extra) != 4)
        return -EINVAL;
    if (r > 255 || g > 255 || b > 255 || brightness > 100 || mode > 3 ||
        speed < 1 || speed > 5 || direction < 1 || direction > 2)
        return -EINVAL;
    packet[0] = mode;
    packet[1] = speed;
    packet[2] = brightness;
    packet[4] = direction;
    packet[5] = r;
    packet[6] = g;
    packet[7] = b;
    mutex_lock(&lightbar_lock);
    status = wmidev_evaluate_method(to_wmi_device(dev), 0, 20, &in, &out);
    if (ACPI_SUCCESS(status)) {
        obj = out.pointer;
        if (obj && obj->type == ACPI_TYPE_INTEGER && obj->integer.value == 0)
            ret = 0;
        else if (obj && obj->type == ACPI_TYPE_BUFFER &&
                 (obj->buffer.length == 4 || obj->buffer.length == 8) &&
                 !memchr_inv(obj->buffer.pointer, 0, obj->buffer.length))
            ret = 0;
    }
    kfree(out.pointer);
    mutex_unlock(&lightbar_lock);
    return ret ? ret : count;
}
static ssize_t color_store(struct device *dev, struct device_attribute *attr,
                          const char *buf, size_t count)
{
    return apply_light(dev, buf, count, false);
}
static ssize_t effect_store(struct device *dev, struct device_attribute *attr,
                           const char *buf, size_t count)
{
    return apply_light(dev, buf, count, true);
}
static DEVICE_ATTR_WO(color);
static DEVICE_ATTR_WO(effect);

static int damx_probe(struct wmi_device *wdev, const void *context)
{
    if (!dmi_match(DMI_PRODUCT_NAME, "Predator PH16-72"))
        return -ENODEV;
    int ret = device_create_file(&wdev->dev, &dev_attr_color);
    if (ret) return ret;
    ret = device_create_file(&wdev->dev, &dev_attr_effect);
    if (ret) device_remove_file(&wdev->dev, &dev_attr_color);
    return ret;
}
static void damx_remove(struct wmi_device *wdev)
{
    device_remove_file(&wdev->dev, &dev_attr_color);
    device_remove_file(&wdev->dev, &dev_attr_effect);
}
static const struct wmi_device_id damx_ids[] = {
    {"7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56", NULL},
    {}
};
MODULE_DEVICE_TABLE(wmi, damx_ids);
static struct wmi_driver damx_driver = {
    .driver = {.name = "damx-lightbar"},
    .id_table = damx_ids,
    .probe = damx_probe,
    .remove = damx_remove,
};
module_wmi_driver(damx_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Optional PH16-72 rear lightbar WMI bridge");
