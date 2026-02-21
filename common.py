import os
import sys
import time
import sqlite3
import unicodedata
import re
import winreg
import ctypes
from ctypes import wintypes
from pathlib import Path
from windows_toasts import WindowsToaster, Toast

APPNAME = "media_processor"
APP_GITHUB_ID = "jjYBdx4IL/media_processor"
APP_VERSION = "0.8.0.0"

LAPPDATA_PATH = Path(os.environ.get('LOCALAPPDATA', os.path.join(os.path.expanduser('~'), 'AppData', 'Local')))
LOG_DIR_PATH = LAPPDATA_PATH / 'log'

LOG_FILE_PATH = LOG_DIR_PATH / f'{APPNAME}.log'

CFG_DIR_PATH = LAPPDATA_PATH / 'py_apps' / APPNAME
DB_PATH = CFG_DIR_PATH / 'sqlite.db'


DEFAULT_DOWNLOAD_DIR = os.path.join(os.path.expanduser('~'), 'Downloads', APPNAME)

wintoaster = WindowsToaster(APPNAME)
last_error_toast_time = 0
_toast_callback = None

def set_toast_callback(cb):
    global _toast_callback
    _toast_callback = cb

def show_toast(message, success=True):
    global last_error_toast_time
    try:
        if not success:
            if time.time() - last_error_toast_time < 60:
                print(f"Suppressing error toast: {message}")
                return
            last_error_toast_time = time.time()
        newToast = Toast()
        msg = f"❌ {message}" if not success else f"✅ {message}"
        newToast.text_fields = [msg]
        if _toast_callback:
            newToast.on_activated = lambda _: _toast_callback()
        wintoaster.show_toast(newToast)
    except Exception as e:
        print(f"Toast error: {e}")

def sanitize_filename(filename):
    filename = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
    name, ext = os.path.splitext(filename)
    words = re.split(r'[^a-zA-Z0-9]', name)
    return ''.join(w[0].upper() + w[1:].lower() for w in words if w) + ext

def extract_video_id(url):
    regex = r'(?:https?:\/\/)?(?:www\.)?youtu(?:\.be\/|be\.com\/(?:watch\?v=|embed\/|v\/|shorts\/|.+\?v=))([^&?\/\s]{11})'
    match = re.search(regex, url, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

def is_running_in_sandbox():
    try:
        kernel32 = ctypes.windll.kernel32
        length = wintypes.DWORD(0)
        return kernel32.GetCurrentPackageFullName(ctypes.byref(length), None) != 15700
    except Exception:
        return False

def is_auto_start():
    try:
        if is_running_in_sandbox():
            return True
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APPNAME)
        winreg.CloseKey(key)
        return True
    except OSError:
        return False

def toggle_auto_start():
    if is_running_in_sandbox():
        show_toast("Please manage autostart in Windows Settings")
        try:
            os.startfile("ms-settings:startupapps")
        except Exception:
            pass
        return
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if not is_auto_start():
            if getattr(sys, 'frozen', False):
                command = f'"{sys.executable}"'
            else:
                command = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'
            winreg.SetValueEx(key, APPNAME, 0, winreg.REG_SZ, command)
            show_toast("Autostart enabled")
        else:
            winreg.DeleteValue(key, APPNAME)
            show_toast("Autostart disabled")
        winreg.CloseKey(key)
    except Exception as e:
        show_toast(f"Autostart Error: {e}", False)

class Config:
    def __init__(self):
        self.postprocessing_enabled = '0'
        self.pp_loudness_norm = '1'
        self.pp_mono = '0'
        self.pp_bitrate = '160'
        self.ftp_server = '192.168.1.20'
        self.ftp_port = '2221'
        self.ftp_user = 'android'
        self.ftp_pass = 'android'
        self.ftp_remote_path = '/'
        self.transfer_method = 'ftp'
        self.scp_server = ''
        self.scp_port = '22'
        self.scp_user = ''
        self.scp_key_file = ''
        self.scp_remote_path = '/'
        self.local_target_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        self.update_check_enabled = '1'
        self.download_dir = DEFAULT_DOWNLOAD_DIR

    def load(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM config")
            for key, value in cursor.fetchall():
                if hasattr(self, key):
                    setattr(self, key, value)
            conn.close()
        except Exception as e:
            print(f"Config read error: {e}")

    def save(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            for key, value in self.__dict__.items():
                cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (str(key), str(value)))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Config write error: {e}")

def get_config():
    cfg = Config()
    cfg.load()
    return cfg