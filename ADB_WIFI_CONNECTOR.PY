#!/usr/bin/env python3
"""
ADB Connect & Control for Windows
- Автоподключение (Wi-Fi debugging / mDNS / USB fallback)
- Выбор устройства только если их больше одного
- Интерактивная консоль с безопасной маршрутизацией adb-команд
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional


# ===== Конфигурация =====
# Значения по умолчанию — пустые (полный авто-поиск). Переопределяются, не трогая
# код: аргументами CLI (--adb / --ip / --port) или переменными окружения
# (ADB_PATH / ADB_WIFI_IP / ADB_WIFI_PORT). Приоритет: аргумент > env > константа.
ADB_PATH = ""
PREFERRED_WIFI_IP = ""    # пусто = только авто-поиск; напр. "192.168.1.50"
PREFERRED_WIFI_PORT = ""  # пусто = 5555 по умолчанию
WINGET_ADB_ID = "Google.PlatformTools"

GLOBAL_ADB_COMMANDS = {
    "devices",
    "start-server",
    "kill-server",
    "connect",
    "disconnect",
    "pair",
    "mdns",
    "version",
    "help",
    "reconnect",
    "usb",
    "tcpip",
}


@dataclass
class DeviceInfo:
    serial: str
    state: str
    model: str = ""
    device: str = ""
    product: str = ""
    transport_id: str = ""

    @property
    def is_emulator(self) -> bool:
        return self.serial.startswith("emulator-")

    @property
    def is_wifi(self) -> bool:
        return ":" in self.serial and not self.is_emulator

    @property
    def is_usb(self) -> bool:
        return not self.is_wifi and not self.is_emulator

    @property
    def short_type(self) -> str:
        if self.is_wifi:
            return "Wi-Fi"
        if self.is_usb:
            return "USB"
        if self.is_emulator:
            return "Emulator"
        return "Unknown"


class ADBConnectAndControl:
    def __init__(
        self,
        adb_path: Optional[str] = None,
        preferred_wifi_ip: Optional[str] = None,
        preferred_wifi_port: Optional[str] = None,
    ) -> None:
        # Priority for each setting: explicit argument > environment variable > module constant.
        adb = adb_path if adb_path is not None else (os.environ.get("ADB_PATH") or ADB_PATH)
        ip = preferred_wifi_ip if preferred_wifi_ip is not None else (os.environ.get("ADB_WIFI_IP") or PREFERRED_WIFI_IP)
        port = preferred_wifi_port if preferred_wifi_port is not None else (os.environ.get("ADB_WIFI_PORT") or PREFERRED_WIFI_PORT)

        self.adb = (adb or "").strip()
        self.preferred_wifi_ip = (ip or "").strip()
        self.preferred_wifi_port = (port or "").strip() or "5555"
        self.current_device: Optional[DeviceInfo] = None

    # ---------- util ----------
    @staticmethod
    def _decode_output(data: Optional[bytes]) -> str:
        if not data:
            return ""
        for enc in ("utf-8", "cp1251", "cp866"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    def run_adb(
        self,
        args: List[str],
        *,
        capture_output: bool = True,
        check: bool = False,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess:
        cmd = [self.adb] + args
        if capture_output:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=False,
                timeout=timeout,
            )
            result.stdout = self._decode_output(result.stdout)
            result.stderr = self._decode_output(result.stderr)
        else:
            result = subprocess.run(
                cmd,
                capture_output=False,
                timeout=timeout,
            )
        if check and result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            raise RuntimeError(
                f"ADB command failed ({result.returncode}): {' '.join(args)}\n"
                f"stdout: {stdout}\n"
                f"stderr: {stderr}"
            )
        return result

    @staticmethod
    def _parse_devices_output(text: str) -> List[DeviceInfo]:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        out: List[DeviceInfo] = []
        for line in lines:
            if line.startswith("List of devices attached"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            extras = {
                token.split(":", 1)[0]: token.split(":", 1)[1]
                for token in parts[2:]
                if ":" in token
            }
            out.append(
                DeviceInfo(
                    serial=serial,
                    state=state,
                    model=extras.get("model", ""),
                    device=extras.get("device", ""),
                    product=extras.get("product", ""),
                    transport_id=extras.get("transport_id", ""),
                )
            )
        return out

    def get_devices(self) -> List[DeviceInfo]:
        try:
            res = self.run_adb(["devices", "-l"], capture_output=True)
        except subprocess.TimeoutExpired:
            print("[!] 'adb devices' не ответил вовремя (adb завис?) — список пуст.")
            return []
        except FileNotFoundError:
            print(f"[!] adb не найден: {self.adb or 'adb'} (проверьте ADB_PATH / PATH).")
            return []
        if res.returncode != 0:
            return []
        return self._parse_devices_output(res.stdout or "")

    def is_device_responsive(self, serial: str, timeout: int = 4) -> bool:
        """Проверяет, что устройство реально отвечает на shell, а не только числится в devices."""
        try:
            res = self.run_adb(
                ["-s", serial, "shell", "echo", "__ADB_OK__"],
                capture_output=True,
                timeout=timeout,
            )
            if res.returncode != 0:
                return False
            out = (res.stdout or "").strip()
            return "__ADB_OK__" in out
        except Exception:
            return False

    def get_ready_devices(self, verify_shell: bool = True) -> List[DeviceInfo]:
        ready = [d for d in self.get_devices() if d.state == "device"]
        if not verify_shell:
            return ready
        return [d for d in ready if self.is_device_responsive(d.serial)]

    @staticmethod
    def print_banner() -> None:
        print(
            """
=================================================
        ADB Connect & Control v4.0
   Автоподключение + интерактивная консоль
=================================================
""".strip()
        )

    @staticmethod
    def print_step(text: str) -> None:
        print(f"\n==> {text}")

    @staticmethod
    def print_devices_table(devices: Iterable[DeviceInfo], title: str) -> None:
        rows = list(devices)
        print(f"\n{title}")
        print("-" * 88)
        print(f"{'#':<3} {'serial':<26} {'state':<12} {'type':<9} {'model':<18} {'transport':<8}")
        print("-" * 88)
        for idx, d in enumerate(rows, 1):
            model = d.model or "-"
            transport = d.transport_id or "-"
            print(f"{idx:<3} {d.serial:<26} {d.state:<12} {d.short_type:<9} {model:<18} {transport:<8}")
        print("-" * 88)

    # ---------- connection logic ----------
    def _adb_from_env(self) -> Optional[str]:
        for key in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
            root = (os.environ.get(key) or "").strip()
            if not root:
                continue
            candidate = os.path.join(root, "platform-tools", "adb.exe")
            if os.path.exists(candidate):
                return candidate
        return None

    def _adb_from_known_locations(self) -> Optional[str]:
        candidates: List[str] = []
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        if local:
            candidates.append(os.path.join(local, "Android", "Sdk", "platform-tools", "adb.exe"))
        program_files = (os.environ.get("ProgramFiles") or "").strip()
        if program_files:
            candidates.append(os.path.join(program_files, "Android", "platform-tools", "adb.exe"))
        program_files_x86 = (os.environ.get("ProgramFiles(x86)") or "").strip()
        if program_files_x86:
            candidates.append(os.path.join(program_files_x86, "Android", "platform-tools", "adb.exe"))
        candidates.append(r"C:\Android\platform-tools\adb.exe")

        for path in candidates:
            if path and os.path.exists(path):
                return path
        return None

    def _adb_from_where(self) -> Optional[str]:
        try:
            res = subprocess.run(
                ["where", "adb"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return None
        if res.returncode != 0:
            return None
        for line in (res.stdout or "").splitlines():
            path = line.strip()
            if path and os.path.exists(path):
                return path
        return None

    def _can_run_winget(self) -> bool:
        try:
            res = subprocess.run(
                ["winget", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return res.returncode == 0
        except Exception:
            return False

    def _install_adb_with_winget(self) -> bool:
        if not self._can_run_winget():
            print("[ERR] winget не найден. Установите Platform Tools вручную.")
            return False
        raw = input("ADB не найден. Установить через winget? [Y/n]: ").strip().lower()
        if raw and raw not in {"y", "yes", "д", "да"}:
            print("[INFO] Установка пропущена.")
            return False
        try:
            res = subprocess.run(
                [
                    "winget",
                    "install",
                    "--id",
                    WINGET_ADB_ID,
                    "-e",
                    "--source",
                    "winget",
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                ],
                timeout=300,
            )
            if res.returncode != 0:
                print("[ERR] Установка через winget завершилась с ошибкой.")
                return False
            return True
        except Exception as exc:
            print(f"[ERR] Ошибка установки через winget: {exc}")
            return False

    def resolve_adb_path(self) -> Optional[str]:
        if self.adb and os.path.exists(self.adb):
            return self.adb

        candidate = self._adb_from_env()
        if candidate:
            return candidate

        candidate = self._adb_from_known_locations()
        if candidate:
            return candidate

        candidate = self._adb_from_where()
        if candidate:
            return candidate

        if self._install_adb_with_winget():
            candidate = self._adb_from_known_locations()
            if candidate:
                return candidate
            candidate = self._adb_from_where()
            if candidate:
                return candidate

        return None

    def ensure_adb(self) -> bool:
        resolved = self.resolve_adb_path()
        if not resolved:
            if self.adb:
                print(f"[ERR] ADB не найден: {self.adb}")
            else:
                print("[ERR] ADB не найден.")
            return False
        self.adb = resolved
        return True

    def start_server(self) -> bool:
        try:
            self.run_adb(["kill-server"], capture_output=True)
            res = self.run_adb(["start-server"], capture_output=True)
            if res.returncode != 0:
                print("[ERR] Не удалось запустить adb server")
                print((res.stderr or res.stdout or "").strip())
                return False
            return True
        except Exception as exc:
            print(f"[ERR] Ошибка запуска adb server: {exc}")
            return False

    def discover_mdns_targets(self) -> List[str]:
        """
        Ищет Wi-Fi debug endpoints через mDNS.
        Примеры строк adb mdns services:
          some-id _adb-tls-connect._tcp. 192.168.0.10:37123
          Pixel-7._adb-tls-connect._tcp. 192.168.0.10:37123
        """
        targets: List[str] = []
        try:
            res = self.run_adb(["mdns", "services"], capture_output=True, timeout=10)
            text = (res.stdout or "") + "\n" + (res.stderr or "")
            for line in text.splitlines():
                if "_adb-tls-connect._tcp" not in line and "_adb._tcp" not in line:
                    continue
                m = re.search(r"([A-Za-z0-9_.-]+):(\d{2,5})", line)
                if not m:
                    continue
                host = m.group(1)
                port = m.group(2)
                targets.append(f"{host}:{port}")
        except subprocess.TimeoutExpired:
            print("[!] 'adb mdns services' не ответил вовремя — пропускаю mDNS-поиск.")
        except Exception:
            pass

        if self.preferred_wifi_ip:
            preferred = f"{self.preferred_wifi_ip}:{self.preferred_wifi_port}"
            if preferred not in targets:
                targets.append(preferred)

        unique: List[str] = []
        seen = set()
        for t in targets:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique

    def try_connect_targets(self, targets: List[str]) -> List[DeviceInfo]:
        """Возвращает только реально живые Wi-Fi устройства."""
        if not targets:
            return []

        before_wifi = {
            d.serial
            for d in self.get_ready_devices(verify_shell=False)
            if d.is_wifi
        }

        for target in targets:
            print(f"   ... adb connect {target}")
            try:
                res = self.run_adb(["connect", target], capture_output=True, timeout=10)
                msg = (res.stdout or "").strip() or (res.stderr or "").strip()
                if msg:
                    print(f"      {msg}")
            except Exception as exc:
                print(f"      ошибка: {exc}")
            time.sleep(1)

        after_wifi_any = [d for d in self.get_devices() if d.is_wifi]
        if after_wifi_any:
            ready = self.wait_authorization(timeout=20)
            wifi_ready = [d for d in ready if d.is_wifi]
            fresh_wifi = [d for d in wifi_ready if d.serial not in before_wifi]
            if fresh_wifi:
                return fresh_wifi
            if wifi_ready:
                return wifi_ready

        after_wifi = [d for d in self.get_ready_devices(verify_shell=True) if d.is_wifi]
        fresh_wifi = [d for d in after_wifi if d.serial not in before_wifi]
        if fresh_wifi:
            return fresh_wifi
        return after_wifi

    def wait_authorization(self, timeout: int = 30) -> List[DeviceInfo]:
        """Ждет, пока unauthorized/offline устройства станут device и начнут отвечать."""
        print("\n[WAIT] Ожидание авторизации (если на телефоне открыт запрос)...")
        for sec in range(timeout, 0, -1):
            listed_ready = self.get_ready_devices(verify_shell=False)
            ready = [d for d in listed_ready if self.is_device_responsive(d.serial)]
            if ready:
                print("\n[OK] Устройство авторизовано")
                return ready
            states = ", ".join(f"{d.serial}:{d.state}" for d in self.get_devices()) or "нет устройств"
            print(f"\r   статус: {states} | осталось {sec:2d}с", end="", flush=True)
            time.sleep(1)
        print()
        return self.get_ready_devices(verify_shell=True)

    def usb_fallback_connect(self) -> List[DeviceInfo]:
        """
        USB fallback:
        - гарантированно позволяет работать по USB,
        - затем пробует Wi-Fi,
        - если Wi-Fi недоступен, остаётся на USB.
        """
        self.print_step("Fallback: USB")
        print("   Подключите телефон по USB и подтвердите отладку.")

        usb: Optional[DeviceInfo] = None
        for _ in range(45):
            devices = self.get_devices()
            usb_candidates = [d for d in devices if d.is_usb]
            if usb_candidates:
                usb = next((d for d in usb_candidates if d.state == "device"), usb_candidates[0])
                if usb.state == "device":
                    break
            time.sleep(1)

        if not usb:
            print("   [ERR] USB устройство не найдено")
            return []

        if usb.state != "device":
            print(f"   [WAIT] USB найден ({usb.serial}:{usb.state}), ждем авторизацию...")
            ready = self.wait_authorization(timeout=45)
            usb_ready = next((d for d in ready if d.serial == usb.serial), None)
            if not usb_ready:
                print("   [ERR] USB не авторизован")
                return []
            usb = usb_ready

        usb_live = next(
            (d for d in self.get_ready_devices(verify_shell=True) if d.serial == usb.serial),
            None,
        )
        if not usb_live:
            print("   [ERR] USB устройство перестало отвечать")
            return []

        print(f"   [OK] USB готов: {usb_live.serial}")
        print("   [INFO] Пытаюсь включить Wi-Fi debug. Если не получится - останусь на USB.")

        tcpip = self.run_adb(["-s", usb_live.serial, "tcpip", self.preferred_wifi_port], capture_output=True)
        if tcpip.returncode != 0:
            msg = (tcpip.stderr or tcpip.stdout or "").strip()
            print(f"   [WARN] Wi-Fi режим недоступен: {msg or 'tcpip failed'}")
            print("   [OK] Продолжаю работу через USB.")
            return [usb_live]

        targets = self.discover_mdns_targets()
        if not targets and self.preferred_wifi_ip:
            targets = [f"{self.preferred_wifi_ip}:{self.preferred_wifi_port}"]

        wifi_ready = self.try_connect_targets(targets)
        if wifi_ready:
            return wifi_ready

        print("   [WARN] Wi-Fi debug не дал активного устройства. Продолжаю работу через USB.")
        return [usb_live]

    def choose_device(self, devices: List[DeviceInfo]) -> Optional[DeviceInfo]:
        if not devices:
            return None
        if len(devices) == 1:
            return devices[0]

        self.print_devices_table(devices, "Найдено несколько устройств. Выберите активное:")
        while True:
            raw = input(f"Введите номер [1..{len(devices)}]: ").strip()
            if not raw:
                print("Пустой ввод. Укажите номер устройства.")
                continue
            if raw.isdigit():
                idx = int(raw)
                if 1 <= idx <= len(devices):
                    return devices[idx - 1]
            print("Неверный номер.")

    def prompt_manual_wifi_target(self) -> Optional[str]:
        default_target = (
            f"{self.preferred_wifi_ip}:{self.preferred_wifi_port}"
            if self.preferred_wifi_ip
            else f"<ip>:{self.preferred_wifi_port}"
        )
        print("\n   [WARN] Автопоиск Wi-Fi устройства не дал результата.")
        print(f"   Введите IP[:PORT] вручную (пример: {default_target})")
        print("   Нажмите Enter для пропуска и перехода к USB-сценарию.")
        raw = input("   IP[:PORT] > ").strip()
        if not raw:
            return None

        if ":" in raw:
            host, port = raw.rsplit(":", 1)
            host = host.strip()
            port = port.strip()
            if not host or not port.isdigit():
                print("   [ERR] Неверный формат. Ожидается IP[:PORT]")
                return None
            return f"{host}:{port}"

        host = raw.strip()
        if not host:
            return None
        return f"{host}:{self.preferred_wifi_port}"

    def bootstrap_connection(self) -> Optional[DeviceInfo]:
        self.print_step("Подготовка ADB")
        if not self.ensure_adb():
            return None
        if not self.start_server():
            return None

        # 1) Уже есть авторизованные устройства
        ready = self.get_ready_devices(verify_shell=True)
        if ready:
            return self.choose_device(ready)

        # 2) Пытаемся auto Wi-Fi/mDNS
        self.print_step("Auto Wi-Fi поиск (mDNS + connect)")
        targets = self.discover_mdns_targets()
        wifi_ready = self.try_connect_targets(targets)
        if wifi_ready:
            return self.choose_device(wifi_ready)

        # 2.1) Ручной ввод IP, если авто-поиск не сработал
        manual_target = self.prompt_manual_wifi_target()
        if manual_target:
            wifi_ready = self.try_connect_targets([manual_target])
            if wifi_ready:
                return self.choose_device(wifi_ready)

        # 3) Ждем авторизацию (если на телефоне запрос)
        ready = self.wait_authorization(timeout=20)
        if ready:
            return self.choose_device(ready)

        # 4) USB fallback
        ready = self.usb_fallback_connect()
        if ready:
            return self.choose_device(ready)

        return None

    # ---------- interactive shell ----------
    @staticmethod
    def show_help() -> None:
        print(
            """
Команды:
  exit, quit          выход
  help                справка
  cls, clear          очистить экран
  status              devices -l + live-check
  install             выбор APK через диалог + adb install -r
  push [dst]          выбор файла через диалог + adb push <file> <dst>
  !<cmd>              выполнить Windows-команду

ADB команды:
  install -r "C:\\path\\app.apk"
  shell
  devices

Поведение:
  - Для обычных adb-команд автоматически добавляется -s <выбранный_девайс>
  - Для глобальных adb-команд (devices/connect/disconnect/...) -s не добавляется
  - Если вы сами укажете -s/-d/-e, скрипт не будет подменять маршрутизацию
""".strip()
        )

    @staticmethod
    def _needs_forced_serial(args: List[str]) -> bool:
        if not args:
            return False
        first = args[0].lower()
        if first in GLOBAL_ADB_COMMANDS:
            return False
        if "-s" in args or "-d" in args or "-e" in args:
            return False
        return True

    def pick_local_file(self, title: str, filetypes: List[tuple]) -> Optional[str]:
        # tkinter нужен только для GUI-диалога выбора файла и импортируется лениво:
        # без него весь остальной (консольный) функционал adb работает как обычно.
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception:
            print("[INFO] tkinter недоступен — укажите путь к файлу вручную.")
            raw = input(f"{title}\n  Путь к файлу > ").strip().strip('"')
            return raw or None
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askopenfilename(title=title, filetypes=filetypes)
            root.destroy()
            selected = (selected or "").strip()
            return selected or None
        except Exception as exc:
            print(f"[ERR] Не удалось открыть диалог выбора файла: {exc}")
            return None

    def show_status(self) -> None:
        devices = self.get_devices()
        if not devices:
            print("[INFO] Устройства не найдены.")
            return

        self.print_devices_table(devices, "ADB devices -l")
        print("Live-check (adb shell echo):")
        for d in devices:
            if d.state != "device":
                print(f"  - {d.serial:<26} state={d.state:<12} live=NO (state)")
                continue
            live = self.is_device_responsive(d.serial)
            print(f"  - {d.serial:<26} state={d.state:<12} live={'YES' if live else 'NO'}")

    def build_special_command(self, args: List[str]) -> Optional[List[str]]:
        if not args:
            return None
        cmd0 = args[0].lower()

        if cmd0 == "status":
            self.show_status()
            return None

        if cmd0 == "install":
            if len(args) == 1:
                apk_path = self.pick_local_file(
                    "Выберите APK для установки",
                    [("APK files", "*.apk"), ("All files", "*.*")],
                )
                if not apk_path:
                    print("[INFO] Установка отменена.")
                    return None
                return ["install", "-r", apk_path]

            if len(args) == 2 and args[1] == "-r":
                apk_path = self.pick_local_file(
                    "Выберите APK для установки",
                    [("APK files", "*.apk"), ("All files", "*.*")],
                )
                if not apk_path:
                    print("[INFO] Установка отменена.")
                    return None
                return ["install", "-r", apk_path]

        if cmd0 == "push":
            if len(args) <= 2:
                local_file = self.pick_local_file(
                    "Выберите файл для копирования на устройство",
                    [("All files", "*.*")],
                )
                if not local_file:
                    print("[INFO] Копирование отменено.")
                    return None
                if len(args) == 2:
                    dst = args[1]
                else:
                    dst = input("Путь назначения на устройстве [/sdcard/Download/]: ").strip() or "/sdcard/Download/"
                return ["push", local_file, dst]

        return args

    def run_interactive(self) -> None:
        if not self.current_device:
            print("[ERR] Нет активного устройства")
            return

        print("\n" + "=" * 49)
        print(f"Активное устройство: {self.current_device.serial}")
        print("Введите 'help' для справки")
        print("=" * 49 + "\n")

        while True:
            try:
                command = input(f"{self.current_device.serial} > ").strip()
                if not command:
                    continue

                lower = command.lower()
                if lower in {"exit", "quit"}:
                    break
                if lower == "help":
                    self.show_help()
                    continue
                if lower in {"cls", "clear"}:
                    os.system("cls" if os.name == "nt" else "clear")
                    continue
                if command.startswith("!"):
                    os.system(command[1:])
                    continue

                if command.startswith("adb "):
                    command = command[4:].strip()

                args = shlex.split(command, posix=False)
                if not args:
                    continue

                special = self.build_special_command(args)
                if special is None:
                    continue
                args = special

                full_cmd = [self.adb]
                if self._needs_forced_serial(args):
                    full_cmd += ["-s", self.current_device.serial]
                full_cmd += args

                subprocess.run(full_cmd)
                print()
            except KeyboardInterrupt:
                print("\n\nВыход...")
                break
            except Exception as exc:
                print(f"[ERR] Ошибка: {exc}")

    def run(self) -> None:
        os.system("cls" if os.name == "nt" else "clear")
        self.print_banner()

        device = self.bootstrap_connection()
        if not device:
            print("\n[ERR] Не удалось найти/подключить авторизованное устройство.")
            return

        self.current_device = device
        print(f"\n[OK] Выбрано устройство: {device.serial} ({device.short_type})")
        self.run_interactive()
        print("\n[OK] До свидания!")


def main() -> int:
    if sys.version_info[0] < 3:
        print("[ERR] Требуется Python 3")
        return 1

    parser = argparse.ArgumentParser(
        description="ADB Connect & Control for Windows (Wi-Fi debugging / mDNS / USB fallback)"
    )
    parser.add_argument(
        "--ip", default=None,
        help="предпочтительный IP для Wi-Fi (иначе $ADB_WIFI_IP; по умолчанию — авто-поиск)",
    )
    parser.add_argument(
        "--port", default=None,
        help="порт Wi-Fi отладки (иначе $ADB_WIFI_PORT; по умолчанию 5555)",
    )
    parser.add_argument(
        "--adb", default=None,
        help="путь к adb (иначе $ADB_PATH; по умолчанию — авто-поиск)",
    )
    args = parser.parse_args()

    app = ADBConnectAndControl(
        adb_path=args.adb,
        preferred_wifi_ip=args.ip,
        preferred_wifi_port=args.port,
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
