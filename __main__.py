#!/usr/bin/env python3
# encoding: utf-8
# @MAKEAPPX:AUTOSTART@
import sys
import os
import sqlite3
import threading
import win32clipboard
import pystray
import win32event
import win32api
import winerror
import winreg
from PIL import Image, ImageDraw, ImageFont
import tkinter as tk
import shutil
import logging
import ctypes

import media_processor.common as common
from media_processor.worker import WorkerThread
from media_processor.gui_logs import LogsWindow
from media_processor.gui_config import ConfigWindow
from ui.github_update_checker import GithubUpdateChecker
from ui.licenses_window import LicensesWindow

root = None
log_window = None
config_window = None
licenses_window = None

def init_db():
    os.makedirs(common.CFG_DIR_PATH, exist_ok=True)
    conn = sqlite3.connect(common.DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            status TEXT DEFAULT 'download_pending',
            filepath TEXT,
            size INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.commit()
    conn.close()

def monitor_clipboard():
    if not hasattr(monitor_clipboard, "last_text"):
        monitor_clipboard.last_text = ""
        logging.info("Clipboard monitor started.")

    text = ""
    try:
        win32clipboard.OpenClipboard()
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        elif win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_TEXT):
            text = win32clipboard.GetClipboardData(win32clipboard.CF_TEXT).decode('utf-8', errors='ignore')
        win32clipboard.CloseClipboard()
    except Exception:
        # Clipboard might be locked by another application
        pass

    if text and text != monitor_clipboard.last_text:
        monitor_clipboard.last_text = text
        if "youtube.com" in text or "youtu.be" in text:
            video_id = common.extract_video_id(text)
            if not video_id:
                logging.info(f"Could not extract video ID from: {text}")
            else:
                logging.info(f"Detected YT ID: {video_id}")
                try:
                    conn = sqlite3.connect(common.DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute("SELECT url FROM downloads ORDER BY id DESC LIMIT 1")
                    last_row = cursor.fetchone()
                    if last_row and last_row[0] == video_id:
                        logging.info("Video ID matches last entry in DB, skipping.")
                    else:
                        cursor.execute("SELECT id FROM downloads WHERE url=? AND status IN ('download_pending')", (video_id,))
                        if not cursor.fetchone():
                            cursor.execute("INSERT INTO downloads (url, status) VALUES (?,?)", (video_id,'download_pending'))
                            conn.commit()
                            common.show_toast("Added to download queue")
                        else:
                            logging.info("Video ID already in queue")
                    conn.close()
                except Exception as e:
                    logging.info(f"Database error: {e}")
                    common.show_toast(f"DB Error: {e}", False)

    if root:
        root.after(2000, monitor_clipboard)

def create_image(width, height, color1, color2):
    image = Image.new('RGB', (width, height), color1)
    dc = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", int(height * 0.8))
    except IOError:
        font = ImageFont.load_default()
    dc.text((width // 2, height // 2), "MP", fill=color2, font=font, anchor="mm")
    return image

def ensure_ffmpeg_available():
    # Check system PATH
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        logging.info(f"ffmpeg found in PATH: {ffmpeg_path}")
        return ffmpeg_path

    ctypes.windll.user32.MessageBoxW(0, "ffmpeg not found in PATH, cannot start.\n\nPlease install it. Recommended command:\nwinget install ffmpeg", "ffmpeg missing", 0x30)
    sys.exit(9)

def show_logs_window_callback():
    global log_window
    if not root:
        return
    if log_window and log_window.winfo_exists():
        log_window.lift()
        return
    log_window = LogsWindow(root)

def show_config_window_callback():
    global config_window
    if not root:
        return
    if config_window and config_window.winfo_exists():
        config_window.lift()
        return
    config_window = ConfigWindow(root)

def show_licenses_window_callback():
    global licenses_window
    if not root:
        return
    if licenses_window and licenses_window.winfo_exists():
        licenses_window.lift()
        return
    licenses_window = LicensesWindow(root)

def main():
    mutex = win32event.CreateMutex(None, False, f"Global\\{common.APPNAME}_Instance_Mutex") # type: ignore
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        print("Another instance is already running.")
        return

    os.makedirs(common.LOG_DIR_PATH, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(thread)d]: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(common.LOG_FILE_PATH, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    ensure_ffmpeg_available()
    
    init_db()
    
    cfg = common.get_config()
    os.makedirs(cfg.download_dir, exist_ok=True)
    os.makedirs(os.path.join(cfg.download_dir, 'tmp'), exist_ok=True)

    logging.info("Program started.")
    
    # Set callback for toast notifications to open logs
    common.set_toast_callback(lambda: root.after(0, show_logs_window_callback))
    
    stop_event = threading.Event()

    t_worker = WorkerThread(stop_event)
    t_worker.start()

    global root
    root = tk.Tk()
    root.withdraw()

    uc = GithubUpdateChecker(common.APP_GITHUB_ID, common.APPNAME, common.APP_VERSION, root=root)
    if common.get_config().update_check_enabled == '0':
        uc.stop()

    def on_exit(icon, item):
        logging.info("User requested exit.")
        stop_event.set()
        icon.stop()
        root.after(0, root.quit) # type: ignore

    root.after(2000, monitor_clipboard)

    def on_open_logs(icon, item):
        root.after(0, show_logs_window_callback) # type: ignore

    def on_open_config(icon, item):
        root.after(0, show_config_window_callback) # type: ignore

    def on_open_licenses(icon, item):
        root.after(0, show_licenses_window_callback) # type: ignore

    def on_open_regedit(icon, item):
        if common.is_running_in_sandbox():
            try:
                os.startfile("ms-settings:startupapps")
            except Exception as e:
                common.show_toast(f"Error opening settings: {e}", False)
            return

        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit"
            target = r"Computer\HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run"
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, "LastKey", 0, winreg.REG_SZ, target)
                winreg.CloseKey(key)
            except Exception as e:
                logging.info(f"Failed to set Regedit LastKey: {e}")
            win32api.ShellExecute(0, 'open', 'regedit.exe', None, None, 1)
        except Exception as e:
            common.show_toast(f"Error opening regedit: {e}", False)

    icon = pystray.Icon(common.APPNAME, create_image(64, 64, 'red', 'white'), f"{common.APPNAME} {common.APP_VERSION}", menu=pystray.Menu(
        pystray.MenuItem("Show Logs", on_open_logs),
        pystray.MenuItem("Configuration", on_open_config),
        pystray.MenuItem("Licenses", on_open_licenses),
        pystray.MenuItem("Open Autostart Registry", on_open_regedit),
        pystray.MenuItem("Exit", on_exit)
    ))
    
    t_tray = threading.Thread(target=icon.run)
    t_tray.daemon = True
    t_tray.start()
    
    try:
        root.mainloop()
        logging.info("Program terminated normally.")
    except Exception as e:
        logging.exception("Program terminated unexpectedly: {}".format(e))
    finally:
        stop_event.set()
        t_worker.join()
        t_tray.join()
        icon.stop()
    sys.exit(0)

if __name__ == '__main__':
    main()
