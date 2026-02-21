import os
import tkinter as tk
from tkinter import scrolledtext
import sqlite3
import media_processor.common as common

class LogsWindow:
    def __init__(self, root):
        self.window = tk.Toplevel(root)
        self.window.title(f"{common.APPNAME} Logs")
        self.window.geometry("1240x700")
        self.window.lift()
        self.window.focus_force()
        
        # Files section
        lbl_files = tk.Label(self.window, text="Recent Downloads (Top 10)", font=("Segoe UI", 10, "bold"))
        lbl_files.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(5, 0))
        
        self.st_files = scrolledtext.ScrolledText(self.window, height=10)
        self.st_files.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        
        # Logs section
        lbl_logs = tk.Label(self.window, text="Logs", font=("Segoe UI", 10, "bold"))
        lbl_logs.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(5, 0))
        
        self.st_logs = scrolledtext.ScrolledText(self.window)
        self.st_logs.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.refresh_data()

    def refresh_data(self):
        if not self.window.winfo_exists():
            return
        try:
            conn = sqlite3.connect(common.DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute("SELECT id, created_at, status, url, filepath, size FROM downloads ORDER BY id DESC LIMIT 10")
            files_data = cursor.fetchall()
            conn.close()

            self.st_files.configure(state='normal')
            self.st_files.delete('1.0', tk.END)
            for row in files_data:
                fname = os.path.basename(row[4]) if row[4] else ""
                size_mb = row[5] / (1024 * 1024) if row[5] else 0
                self.st_files.insert(tk.END, f"{row[0]} {row[1]} [{row[2]}] {fname} ({size_mb:.2f} MB) - {row[3]}\n")
            self.st_files.configure(state='disabled')

            self.st_logs.configure(state='normal')
            self.st_logs.delete('1.0', tk.END)
            if os.path.exists(common.LOG_FILE_PATH):
                with open(common.LOG_FILE_PATH, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for line in reversed(lines[-500:]):
                        self.st_logs.insert(tk.END, line)
            self.st_logs.configure(state='disabled')
        except Exception as e:
            print(f"Refresh error: {e}")
            
        self.window.after(1000, self.refresh_data)

    def lift(self):
        self.window.lift()
        self.window.focus_force()
    
    def winfo_exists(self):
        return self.window.winfo_exists()