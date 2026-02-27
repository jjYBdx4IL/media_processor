import os
import sys
import time
import subprocess
import threading
import logging
import shutil
import ftplib
import re
import asyncio
import yt_dlp
from bs4 import BeautifulSoup
from urllib.parse import quote
import pyttsx3
import adbutils
from adbutils import adb
import media_processor.common as common

_adb_monitor = None

class AdbDeviceMonitor:
    def __init__(self, adb_path=None):
        if adb_path and os.path.exists(adb_path):
            adbutils.adb_path = adb_path
        self.current_device = None
        self.stop_event = threading.Event()
        self.thread = None
        self.waiting_logged = False
        self.loop = None
        self.async_stop_event = None

    def start(self):
        self.stop_event.clear()
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        if not self.thread:
            return
        self.stop_event.set()
        if self.loop and self.async_stop_event:
            self.loop.call_soon_threadsafe(self.async_stop_event.set)
        self.current_device = None

    def _run(self):
        logging.debug("ADB Monitor thread started")
        try:
            asyncio.run(self._run_async())
        except Exception as e:
            logging.info(f"ADB Monitor thread error: {e}")
            self.current_device = None
        logging.debug("ADB Monitor thread terminated")

    async def _run_async(self):
        self.loop = asyncio.get_running_loop()
        self.async_stop_event = asyncio.Event()
        
        if self.stop_event.is_set():
            return

        writer = None
        try:
            try:
                adb.server_version()
            except Exception:
                pass

            reader, writer = await asyncio.open_connection(adb.host, adb.port)
            
            cmd = "host:track-devices"
            msg = "{:04x}{}".format(len(cmd), cmd).encode("utf-8")
            writer.write(msg)
            await writer.drain()
            
            try:
                okay = await asyncio.wait_for(reader.readexactly(4), timeout=20.0)
            except asyncio.TimeoutError:
                logging.error("ADB track-devices handshake timed out")
                return

            if okay != b"OKAY":
                logging.error(f"ADB track-devices failed: {okay}")
                return

            while not self.async_stop_event.is_set():
                read_len_task = asyncio.create_task(reader.readexactly(4))
                stop_task = asyncio.create_task(self.async_stop_event.wait())
                
                done, pending = await asyncio.wait(
                    [read_len_task, stop_task], 
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                for t in pending:
                    t.cancel()

                if stop_task in done:
                    break
                
                len_bytes = read_len_task.result()
                length = int(len_bytes.decode("utf-8"), 16)
                
                read_payload_task = asyncio.create_task(reader.readexactly(length))
                stop_task = asyncio.create_task(self.async_stop_event.wait())
                
                done, pending = await asyncio.wait(
                    [read_payload_task, stop_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                for t in pending:
                    t.cancel()

                if stop_task in done:
                    break
                
                payload = read_payload_task.result()
                self._process_device_list(payload.decode("utf-8"))
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not self.async_stop_event.is_set():
                logging.info(f"ADB Monitor loop error: {e}")
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    def _process_device_list(self, output):
        for line in output.splitlines():
            parts = line.split('\t')
            if len(parts) >= 2:
                serial, state = parts[0], parts[1]
                if not serial.startswith('emulator-'):
                    if state == 'device':
                        if self.current_device != serial:
                            logging.info(f"ADB device connected: {serial}")
                            self.current_device = serial
                    else:
                        if self.current_device != None:
                            logging.info(f"ADB device disconnected: {self.current_device}")
                            self.current_device = None

    def get_device(self):
        return self.current_device
    
    def report_failure(self, serial):
        if self.current_device == serial:
            self.current_device = None

def start_adb_monitor(cfg):
    global _adb_monitor
    adb_exe = None
    if cfg.adb_tools_path:
        adb_exe = os.path.join(cfg.adb_tools_path, "adb.exe" if sys.platform == 'win32' else "adb")
    
    if _adb_monitor is None:
        _adb_monitor = AdbDeviceMonitor(adb_exe)
    
    _adb_monitor.start()

def stop_adb_monitor():
    global _adb_monitor
    if _adb_monitor:
        _adb_monitor.stop()
        _adb_monitor = None

def try_adb_push(file_path, cfg):
    if cfg.adb_tools_path:
        adb_exe = os.path.join(cfg.adb_tools_path, "adb.exe" if sys.platform == 'win32' else "adb")
        if os.path.exists(adb_exe):
            adbutils.adb_path = adb_exe
        
    remote_path = cfg.adb_remote_path
    if not remote_path:
        remote_path = "/sdcard/Download/"
        
    filename = os.path.basename(file_path)

    device_serial = None
    
    if _adb_monitor:
        device_serial = _adb_monitor.get_device()
        if not device_serial:
            if not _adb_monitor.waiting_logged:
                logging.info(f"Uploading: {file_path}")
                logging.info("Attempting ADB push...")
                logging.info("ADB Monitor active but no device detected yet.")
                _adb_monitor.waiting_logged = True
            return False
        _adb_monitor.waiting_logged = False
    
    logging.info(f"Uploading: {file_path}")
    logging.info("Attempting ADB push...")

    if not device_serial:
        logging.info("No ADB device found.")
        return False

    logging.info(f"Using ADB device: {device_serial}")
    
    try:
        device = adb.device(serial=device_serial)
        file_size = os.path.getsize(file_path)
        start_time = time.time()
        
        final_remote_path = remote_path
        if not final_remote_path.endswith('/') and not os.path.splitext(final_remote_path)[1]:
             final_remote_path += "/"
        if final_remote_path.endswith('/'):
            final_remote_path = final_remote_path + filename
            
        device.sync.push(file_path, final_remote_path)
        
        duration = time.time() - start_time
        speed = (file_size / (1024 * 1024)) / duration if duration > 0 else 0
        logging.info(f"Successfully uploaded {file_path} via ADB. ({file_size / (1024*1024):.2f} MB, {speed:.2f} MB/s)")
        
        # Trigger media scan
        uri = f"file://{quote(final_remote_path, safe='/')}"
        device.shell(f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d {uri}")
        
        logging.info(f"Triggered media scan for {final_remote_path}")

        common.show_toast(f"Uploaded via ADB: {filename}")
        os.remove(file_path)
        return True
    except Exception as e:
        logging.info(f"ADB push failed: {e}")
        if _adb_monitor and device_serial:
            _adb_monitor.report_failure(device_serial)
        return False

def upload_file(file_path):
    cfg = common.get_config()

    method = cfg.transfer_method
    
    if method == 'local':
        try:
            logging.info(f"Uploading (Local move): {file_path}")
            target_dir = cfg.local_target_dir
            if not target_dir:
                target_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
            
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
                
            filename = os.path.basename(file_path)
            dest_path = os.path.join(target_dir, filename)
            
            if os.path.exists(dest_path):
                base, ext = os.path.splitext(filename)
                dest_path = os.path.join(target_dir, f"{base}_{int(time.time())}{ext}")
            
            shutil.move(file_path, dest_path)
            logging.info(f"Moved {file_path} to {dest_path}")
            common.show_toast(f"Moved to {os.path.basename(dest_path)}")
            return True
        except Exception as e:
            logging.info(f"Error moving file locally: {e}")
            common.show_toast(f"Move Error: {e}", False)
            return False

    if method == 'adb':
        return try_adb_push(file_path, cfg)

    if method == 'scp':
        try:
            logging.info(f"Uploading (SCP): {file_path}")
            server = cfg.scp_server
            port = cfg.scp_port
            user = cfg.scp_user
            key_file = cfg.scp_key_file
            remote_path = cfg.scp_remote_path
            
            if not all([server, user, key_file]):
                logging.info("SCP configuration missing")
                return False

            remote_filename = os.path.basename(file_path)
            if remote_path.endswith('/'):
                dest_path = f"{remote_path}{remote_filename}"
            else:
                dest_path = f"{remote_path}/{remote_filename}"
            
            destination = f"{user}@{server}:{dest_path}"
            
            cmd = ['scp', '-P', port, '-i', key_file, file_path, destination]
            
            start_time = time.time()
            startupinfo = None
            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            subprocess.run(cmd, check=True, startupinfo=startupinfo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            def run_media_scan():
                try:
                    ssh_cmd = ['ssh', '-p', port, '-i', key_file, f"{user}@{server}", f"termux-media-scan \"{dest_path}\""]
                    subprocess.run(ssh_cmd, startupinfo=startupinfo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
                except Exception as e:
                    logging.warning(f"Failed to run termux-media-scan: {e}")
            threading.Thread(target=run_media_scan, daemon=True).start()

            duration = time.time() - start_time
            file_size = os.path.getsize(file_path)
            speed = (file_size / (1024 * 1024)) / duration if duration > 0 else 0
            
            logging.info(f"Successfully uploaded {file_path} via SCP. ({file_size / (1024*1024):.2f} MB, {speed:.2f} MB/s)")
            common.show_toast(f"Uploaded {remote_filename}")
            os.remove(file_path)
            return True
        except subprocess.CalledProcessError as e:
            logging.info(f"Error uploading via SCP: {e}")
            if e.stderr:
                logging.info(f"SCP stderr: {e.stderr}")
            if cfg.adb_fallback_enabled == '1' and try_adb_push(file_path, cfg):
                return True
            common.show_toast(f"SCP Error: {e}", False)
            return False
        except Exception as e:
            logging.info(f"Error uploading via SCP: {e}")
            if cfg.adb_fallback_enabled == '1' and try_adb_push(file_path, cfg):
                return True
            common.show_toast(f"SCP Error: {e}", False)
            return False
    else:
        try:
            logging.info(f"Uploading (FTP): {file_path}")
            ftp = ftplib.FTP()
            ftp.connect(cfg.ftp_server, int(cfg.ftp_port)) # type: ignore
            ftp.login(cfg.ftp_user, cfg.ftp_pass) # type: ignore
            remote_path = cfg.ftp_remote_path
            if remote_path and remote_path != '/':
                ftp.cwd(remote_path)
            remote_filename = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            start_time = time.time()
            with open(file_path, 'rb') as f:
                ftp.storbinary(f'STOR {remote_filename}', f)
            duration = time.time() - start_time
            ftp.quit()
            
            speed = (file_size / (1024 * 1024)) / duration if duration > 0 else 0
            logging.info(f"Successfully uploaded {file_path} as {remote_filename} to FTP server. ({file_size / (1024*1024):.2f} MB, {speed:.2f} MB/s)")
            common.show_toast(f"Uploaded {remote_filename}")
            os.remove(file_path)
            return True
        except Exception as e:
            logging.info(f"Error uploading to FTP: {e}")
            if cfg.adb_fallback_enabled == '1' and try_adb_push(file_path, cfg):
                return True
            common.show_toast(f"FTP Error: {e}", False)
            return False

def normalize_audio(filepath):
    logging.info(f"Normalizing audio: {filepath}")
    
    cfg = common.get_config()
    if cfg.postprocessing_enabled != '1':
        logging.info("Postprocessing disabled, skipping.")
        return filepath

    base, _ = os.path.splitext(filepath)
    new_filepath = f"{base}.mp3"
    temp_path = f"{base}.tmp.mp3"
    
    audio_filters = []
    if cfg.pp_mono == '1':
        audio_filters.append('aformat=channel_layouts=mono')
    if cfg.pp_loudness_norm == '1':
        audio_filters.append('loudnorm')
    
    cmd = ['ffmpeg', '-y', '-i', filepath]
    
    if audio_filters:
        cmd.extend(['-af', ','.join(audio_filters)])
        
    cmd.extend(['-c:a', 'libmp3lame'])
    cmd.extend(['-b:a', f'{cfg.pp_bitrate}k'])
    cmd.append(temp_path)
    
    try:
        logging.info(f"Command: {cmd}")
        startupinfo = None
        if sys.platform == 'win32':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        shutil.move(temp_path, new_filepath)
        if filepath != new_filepath and os.path.exists(filepath):
            os.remove(filepath)
        logging.info(f"Normalization successful. New file: {new_filepath}")
        return new_filepath
    except Exception as e:
        logging.info(f"Normalization failed: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return None

def download_audio(url):
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={url}"
    
    def progress_hook(d):
        if d['status'] == 'finished':
            elapsed = d.get('elapsed')
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            if elapsed and total_bytes and elapsed > 0:
                speed = (total_bytes / (1024 * 1024)) / elapsed
                logging.info(f"Download finished. Size: {total_bytes / (1024*1024):.2f} MB, Speed: {speed:.2f} MB/s")
    
    cfg = common.get_config()
    tmp_dir = os.path.join(cfg.download_dir, 'tmp')

    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': os.path.join(tmp_dir, '%(title)s.%(ext)s'),
        'progress_hooks': [progress_hook],
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'm4a',
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: # type: ignore
            info_dict = ydl.extract_info(url, download=True)
            filepath = None
            if 'requested_downloads' in info_dict:
                filepath = info_dict['requested_downloads'][0]['filepath']
            else:
                for file in os.listdir(tmp_dir):
                    if file.startswith(info_dict['title'].replace('|','｜')): # type: ignore
                        filepath = os.path.join(tmp_dir, file)
                        break
            
            if filepath:
                dirname, filename = os.path.split(filepath)
                sanitized_name = common.sanitize_filename(filename)
                new_filepath = os.path.join(dirname, sanitized_name)
                if new_filepath != filepath:
                    try:
                        os.rename(filepath, new_filepath)
                        filepath = new_filepath
                    except OSError as e:
                        logging.info(f"Failed to rename file to sanitized version: {e}")
            
            return filepath
    except Exception as e:
        logging.info(f"Error downloading audio: {e}")
        common.show_toast(f"Download Error: {e}", False)
        return None

def process_tts(filepath):
    logging.info(f"Processing TTS for: {filepath}")
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            html_content = f.read()
    except Exception as e:
        logging.info(f"Failed to read HTML: {e}")
        return None

    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        text = soup.get_text(separator=' ')
        text = re.sub(r'(?:http[s]?|ftp)://\S+', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
    except Exception as e:
        logging.info(f"HTML parsing error: {e}")
        return None

    if not text:
        logging.info("No text extracted.")
        return None

    base_path = os.path.splitext(filepath)[0]
    wav_path = f"{base_path}.wav"
    
    cfg = common.get_config()
    if cfg.postprocessing_enabled == '1':
        dest_path = wav_path
    else:
        dest_path = f"{base_path}.mp3"

    audio_source = None
    startupinfo = None
    if sys.platform == 'win32':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    try:
        engine = pyttsx3.init()
        engine.save_to_file(text, wav_path)
        engine.runAndWait()
        if os.path.exists(wav_path):
            audio_source = wav_path
    except Exception as e:
        logging.info(f"pyttsx3 TTS failed: {e}")

    if audio_source:
        if cfg.postprocessing_enabled == '1':
            return audio_source

        try:
            cmd = ['ffmpeg', '-y', '-i', audio_source, '-c:a', 'libmp3lame', '-b:a', '128k', dest_path]
            subprocess.run(cmd, check=True, startupinfo=startupinfo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            os.remove(audio_source)
            return dest_path
        except Exception as e:
            logging.info(f"FFmpeg conversion failed: {e}")
            if os.path.exists(audio_source):
                os.remove(audio_source)
            return None
    
    if audio_source:
        os.remove(audio_source)
    return None