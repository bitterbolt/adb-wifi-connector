import os
import unittest
from importlib.machinery import SourceFileLoader

script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ADB_WIFI_CONNECTOR.PY"))
connector = SourceFileLoader("adb_wifi_connector", script_path).load_module()

DeviceInfo = connector.DeviceInfo
ADBConnectAndControl = connector.ADBConnectAndControl


class TestDeviceInfo(unittest.TestCase):
    def test_wifi_device(self):
        d = DeviceInfo(serial="192.168.1.100:5555", state="device", model="Pixel 7")
        self.assertTrue(d.is_wifi)
        self.assertFalse(d.is_usb)
        self.assertFalse(d.is_emulator)
        self.assertEqual(d.short_type, "Wi-Fi")

    def test_usb_device(self):
        d = DeviceInfo(serial="RF8M123456", state="device", model="Galaxy S23")
        self.assertFalse(d.is_wifi)
        self.assertTrue(d.is_usb)
        self.assertFalse(d.is_emulator)
        self.assertEqual(d.short_type, "USB")

    def test_emulator_device(self):
        d = DeviceInfo(serial="emulator-5554", state="device", model="sdk_gphone64")
        self.assertFalse(d.is_wifi)
        self.assertFalse(d.is_usb)
        self.assertTrue(d.is_emulator)
        self.assertEqual(d.short_type, "Emulator")


class TestADBConnectAndControlConfig(unittest.TestCase):
    def test_default_config(self):
        app = ADBConnectAndControl()
        self.assertEqual(app.preferred_wifi_port, "5555")
        self.assertEqual(app.preferred_wifi_ip, "")

    def test_custom_arguments(self):
        app = ADBConnectAndControl(
            adb_path="C:\\adb\\adb.exe",
            preferred_wifi_ip="192.168.0.50",
            preferred_wifi_port="4444",
        )
        self.assertEqual(app.adb, "C:\\adb\\adb.exe")
        self.assertEqual(app.preferred_wifi_ip, "192.168.0.50")
        self.assertEqual(app.preferred_wifi_port, "4444")

    def test_decode_output_encodings(self):
        app = ADBConnectAndControl()
        utf8_bytes = "Привет мир".encode("utf-8")
        cp1251_bytes = "Привет мир".encode("cp1251")
        self.assertEqual(app._decode_output(utf8_bytes), "Привет мир")
        self.assertEqual(app._decode_output(cp1251_bytes), "Привет мир")
        self.assertEqual(app._decode_output(b""), "")


if __name__ == "__main__":
    unittest.main()
