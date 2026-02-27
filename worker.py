import os
import time
import sqlite3
import logging
import shutil
import zipfile
import threading
import media_processor.common as common
import media_processor.download_logic as dl_logic

class WorkerThread(threading.Thread):
    def __init__(self, stop_event):
        super().__init__()
        self.stop_event = stop_event
        self.daemon = True

    def run(self):
        logging.info("Worker thread started.")
        conn = sqlite3.connect(common.DB_PATH)
        last_dl_time = 0
        failed_downloads = {}

        while not self.stop_event.is_set():
            did_work = False
            try:
                cfg = common.get_config()
                download_dir = cfg.download_dir
                tmp_dir = os.path.join(download_dir, 'tmp')
                
                # 0. Scan for manual files
                try:
                    for filename in os.listdir(download_dir):
                        if filename.lower().endswith('.crdownload') or filename.lower().endswith('.tmp'):
                            continue

                        filepath = os.path.join(download_dir, filename)
                        if os.path.isfile(filepath):
                            try:
                                if os.path.getsize(filepath) == 0:
                                    continue
                            except OSError:
                                continue
                            ext = os.path.splitext(filename)[1].lower()
                            if ext in ['.mp3', '.m4a']:
                                sanitized_name = common.sanitize_filename(filename)
                                dest_path = os.path.join(tmp_dir, sanitized_name)
                                
                                if os.path.exists(dest_path):
                                    base, extension = os.path.splitext(sanitized_name)
                                    dest_path = os.path.join(tmp_dir, f"{base}_{int(time.time())}{extension}")
                                
                                shutil.move(filepath, dest_path)
                                logging.info(f"Picked up manual file: {filename}")
                                
                                file_size = os.path.getsize(dest_path)
                                # cfg loaded at start of loop
                                status = 'postprocessing_pending' if cfg.postprocessing_enabled == '1' else 'upload_pending'
                                cursor = conn.cursor()
                                cursor.execute("INSERT INTO downloads (url, status, filepath, size) VALUES (?, ?, ?, ?)", 
                                            (f"manual:{filename}", status, os.path.relpath(dest_path, download_dir), file_size))
                                conn.commit()
                                did_work = True
                            elif ext == '.html':
                                sanitized_name = common.sanitize_filename(filename)
                                dest_path = os.path.join(tmp_dir, sanitized_name)
                                
                                if os.path.exists(dest_path):
                                    base, extension = os.path.splitext(sanitized_name)
                                    dest_path = os.path.join(tmp_dir, f"{base}_{int(time.time())}{extension}")
                                
                                shutil.move(filepath, dest_path)
                                logging.info(f"Picked up manual HTML file: {filename}")
                                
                                file_size = os.path.getsize(dest_path)
                                cursor = conn.cursor()
                                cursor.execute("INSERT INTO downloads (url, status, filepath, size) VALUES (?, ?, ?, ?)", 
                                            (f"manual:{filename}", 'tts_pending', os.path.relpath(dest_path, download_dir), file_size))
                                conn.commit()
                                did_work = True
                            elif ext == '.zip':
                                sanitized_name = common.sanitize_filename(filename)
                                dest_path = os.path.join(tmp_dir, sanitized_name)
                                
                                if os.path.exists(dest_path):
                                    base, extension = os.path.splitext(sanitized_name)
                                    dest_path = os.path.join(tmp_dir, f"{base}_{int(time.time())}{extension}")
                                
                                shutil.move(filepath, dest_path)
                                logging.info(f"Picked up manual ZIP file: {filename}")

                                try:
                                    with zipfile.ZipFile(dest_path, 'r') as z:
                                        file_list = z.namelist()
                                        real_files = [f for f in file_list if not f.endswith('/')]
                                        if len(real_files) == 1 and real_files[0].lower().endswith('.html'):
                                            html_filename = real_files[0]
                                            z.extract(html_filename, tmp_dir)
                                            extracted_path = os.path.join(tmp_dir, html_filename)
                                            
                                            sanitized_html_name = common.sanitize_filename(os.path.basename(html_filename))
                                            dest_html_path = os.path.join(tmp_dir, sanitized_html_name)
                                            if os.path.exists(dest_html_path) and os.path.abspath(dest_html_path) != os.path.abspath(extracted_path):
                                                base, extension = os.path.splitext(sanitized_html_name)
                                                dest_html_path = os.path.join(tmp_dir, f"{base}_{int(time.time())}{extension}")
                                            
                                            if os.path.abspath(extracted_path) != os.path.abspath(dest_html_path):
                                                shutil.move(extracted_path, dest_html_path)
                                            
                                            html_size = os.path.getsize(dest_html_path)
                                            cursor = conn.cursor()
                                            cursor.execute("INSERT INTO downloads (url, status, filepath, size) VALUES (?, ?, ?, ?)", 
                                            (f"manual:{html_filename}", 'tts_pending', os.path.relpath(dest_html_path, download_dir), html_size))
                                            conn.commit()
                                            logging.info(f"Extracted HTML from ZIP: {html_filename}")
                                except Exception as e:
                                    logging.info(f"Error processing zip {filename}: {e}")
                                
                                file_size = os.path.getsize(dest_path)
                                cursor = conn.cursor()
                                cursor.execute("INSERT INTO downloads (url, status, filepath, size) VALUES (?, ?, ?, ?)", 
                                            (f"manual:{filename}", 'upload_pending', os.path.relpath(dest_path, download_dir), file_size))
                                conn.commit()
                                did_work = True
                            else:
                                sanitized_name = common.sanitize_filename(filename)
                                dest_path = os.path.join(tmp_dir, sanitized_name)
                                
                                if os.path.exists(dest_path):
                                    base, extension = os.path.splitext(sanitized_name)
                                    dest_path = os.path.join(tmp_dir, f"{base}_{int(time.time())}{extension}")
                                
                                shutil.move(filepath, dest_path)
                                logging.info(f"Picked up manual file: {filename}")
                                
                                file_size = os.path.getsize(dest_path)
                                cursor = conn.cursor()
                                cursor.execute("INSERT INTO downloads (url, status, filepath, size) VALUES (?, ?, ?, ?)", 
                                            (f"manual:{filename}", 'upload_pending', os.path.relpath(dest_path, download_dir), file_size))
                                conn.commit()
                                did_work = True
                except Exception as e:
                    logging.info(f"Manual scan error: {e}")

                # 0.5 TTS (TTS Pending -> Upload Pending)
                if not did_work:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id, filepath FROM downloads WHERE status='tts_pending' LIMIT 1")
                    row = cursor.fetchone()
                    if row:
                        id, filename = row
                        filepath = os.path.join(download_dir, filename) if filename else None
                        
                        if filepath and os.path.exists(filepath):
                            m4a_path = dl_logic.process_tts(filepath)
                            
                            cursor = conn.cursor()
                            cursor.execute("UPDATE downloads SET status=? WHERE id=?", ('upload_pending', id))
                            conn.commit()
                            
                            if m4a_path:
                                file_size = os.path.getsize(m4a_path)
                                # cfg loaded
                                status = 'postprocessing_pending' if cfg.postprocessing_enabled == '1' else 'upload_pending'
                                cursor.execute("INSERT INTO downloads (url, status, filepath, size) VALUES (?, ?, ?, ?)", 
                                            (f"tts:{os.path.basename(m4a_path)}", status, os.path.relpath(m4a_path, download_dir), file_size))
                                conn.commit()
                                logging.info(f"TTS generated: {m4a_path}")
                            else:
                                logging.info(f"TTS failed for {filename}")
                            
                            did_work = True
                        else:
                            cursor = conn.cursor()
                            cursor.execute("UPDATE downloads SET status=? WHERE id=?", ('missing', id))
                            conn.commit()
                            did_work = True

                # 1. Uploads (Upload Pending -> Uploaded)
                cursor = conn.cursor()
                cursor.execute("SELECT id, filepath FROM downloads WHERE status='upload_pending' LIMIT 1")
                row = cursor.fetchone()
                if row:
                    if cfg.transfer_method == 'adb':
                        dl_logic.start_adb_monitor(cfg)

                    id, filename = row
                    filepath = os.path.join(download_dir, filename) if filename else None
                    
                    if filepath and os.path.exists(filepath):
                        if dl_logic.upload_file(filepath):
                            cursor = conn.cursor()
                            cursor.execute("UPDATE downloads SET status=? WHERE id=?", ('uploaded', id))
                            conn.commit()
                            did_work = True
                    else:
                        logging.info(f"File missing for upload id {id}: {filepath}")
                        cursor = conn.cursor()
                        cursor.execute("UPDATE downloads SET status=? WHERE id=?", ('missing', id))
                        conn.commit()
                        did_work = True
                else:
                    dl_logic.stop_adb_monitor()

                if not did_work:
                    # 2. Normalization (Postprocessing Pending -> Upload Pending)
                    cursor = conn.cursor()
                    cursor.execute("SELECT id, filepath FROM downloads WHERE status='postprocessing_pending' LIMIT 1")
                    row = cursor.fetchone()
                    if row:
                        id, filename = row
                        filepath = os.path.join(download_dir, filename) if filename else None
                        
                        if filepath and os.path.exists(filepath):
                            new_filepath = dl_logic.normalize_audio(filepath)
                            if new_filepath:
                                try:
                                    file_size = os.path.getsize(new_filepath)
                                    cursor = conn.cursor()
                                    cursor.execute("UPDATE downloads SET status=?, size=?, filepath=? WHERE id=?", ('upload_pending', file_size, os.path.relpath(new_filepath, download_dir), id))
                                    conn.commit()
                                    did_work = True
                                except OSError:
                                    logging.info(f"Could not get file size for {new_filepath}")
                            else:
                                logging.info(f"Normalization failed for id {id}: {filepath}")
                                cursor = conn.cursor()
                                cursor.execute("UPDATE downloads SET status=? WHERE id=?", ('normalization_failed', id))
                                conn.commit()
                                did_work = True
                        else:
                            logging.info(f"File missing for normalization id {id}: {filepath}")
                            cursor = conn.cursor()
                            cursor.execute("UPDATE downloads SET status=? WHERE id=?", ('file_missing', id))
                            conn.commit()
                            did_work = True

                if not did_work:
                    # 3. Downloads (Download Pending -> Postprocessing Pending)
                    cursor = conn.cursor()
                    cursor.execute("SELECT id, url FROM downloads WHERE status='download_pending'")
                    rows = cursor.fetchall()
                    
                    target_row = None
                    for row in rows:
                        r_id, r_url = row
                        if r_url in failed_downloads:
                            if time.time() < failed_downloads[r_url]['next_retry']:
                                continue
                        target_row = row
                        break
                    
                    if target_row:
                        id, url = target_row

                        logging.info(f"Processing URL from queue: {url}")
                        now = time.time()
                        if now - last_dl_time < 10:
                            time.sleep(10)
                        filepath = dl_logic.download_audio(url)
                        last_dl_time = time.time()
                        
                        if filepath:
                            try:
                                file_size = os.path.getsize(filepath)
                            except OSError:
                                file_size = 0
                            # cfg loaded
                            status = 'postprocessing_pending' if cfg.postprocessing_enabled == '1' else 'upload_pending'
                            cursor = conn.cursor()
                            cursor.execute("UPDATE downloads SET status=?, filepath=?, size=? WHERE id=?", (status, os.path.relpath(filepath, download_dir), file_size, id))
                            conn.commit()
                            if url in failed_downloads:
                                del failed_downloads[url]
                        else:
                            if url not in failed_downloads:
                                failed_downloads[url] = {'count': 0, 'next_retry': 0}
                            
                            failed_downloads[url]['count'] += 1
                            count = failed_downloads[url]['count']
                            
                            if count > 10:
                                logging.info(f"Max retries reached for {url}. Marking as error.")
                                cursor = conn.cursor()
                                cursor.execute("UPDATE downloads SET status='error' WHERE id=?", (id,))
                                conn.commit()
                                del failed_downloads[url]
                            else:
                                backoff = count * 60
                                failed_downloads[url]['next_retry'] = time.time() + backoff
                                logging.info(f"Download failed for {url}. Retry {count}/10 in {backoff}s.")
                        did_work = True

                if not did_work:
                    time.sleep(5)
            except Exception as e:
                logging.info(f"Worker error: {e}")
                time.sleep(10)