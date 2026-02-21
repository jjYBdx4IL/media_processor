import os
import sys
import time
import subprocess
import threading
import logging
import shutil
import ftplib
import re
import yt_dlp
from bs4 import BeautifulSoup
import pyttsx3
import media_processor.common as common

def upload_file(file_path):
    cfg = common.get_config()
    method = cfg.transfer_method
    
    if method == 'local':
        try:
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

    if method == 'scp':
        try:
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
            common.show_toast(f"SCP Error: {e}", False)
            return False
        except Exception as e:
            logging.info(f"Error uploading via SCP: {e}")
            common.show_toast(f"SCP Error: {e}", False)
            return False
    else:
        try:
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