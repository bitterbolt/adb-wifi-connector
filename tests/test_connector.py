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


class TestParsingOutput(unittest.TestCase):
    def test_parse_devices_output(self):
        raw_output = """List of devices attached
192.168.1.100:5555     device product:cheetah model:Pixel_7 device:cheetah transport_id:1
RF8M123456             offline product:dm3q model:SM_S918B device:dm3q transport_id:2
emulator-5554          device product:sdk_gphone64_x86_64 model:sdk_gphone64_x86_64 device:emulator64_x86_64 transport_id:3
"""
        devices = ADBConnectAndControl._parse_devices_output(raw_output)
        self.assertEqual(len(devices), 3)

        dev0 = devices[0]
        self.assertEqual(dev0.serial, "192.168.1.100:5555")
        self.assertEqual(dev0.state, "device")
        self.assertEqual(dev0.model, "Pixel_7")
        self.assertEqual(dev0.device, "cheetah")
        self.assertEqual(dev0.transport_id, "1")
        self.assertTrue(dev0.is_wifi)

        dev1 = devices[1]
        self.assertEqual(dev1.serial, "RF8M123456")
        self.assertEqual(dev1.state, "offline")
        self.assertTrue(dev1.is_usb)

        dev2 = devices[2]
        self.assertEqual(dev2.serial, "emulator-5554")
        self.assertTrue(dev2.is_emulator)

    def test_parse_devices_output_empty(self):
        self.assertEqual(ADBConnectAndControl._parse_devices_output(""), [])
        self.assertEqual(ADBConnectAndControl._parse_devices_output("List of devices attached\n"), [])

    def test_parse_mdns_targets(self):
        raw_mdns = """List of discovered mdns services
adb-123456 _adb-tls-connect._tcp. 192.168.1.150:39451
pixel-7._adb._tcp. 192.168.1.160:43210
other_service._http._tcp. 192.168.1.200:8080
"""
        targets = ADBConnectAndControl._parse_mdns_targets(raw_mdns)
        self.assertEqual(targets, ["192.168.1.150:39451", "192.168.1.160:43210"])


if __name__ == "__main__":
    unittest.main()
