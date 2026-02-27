import tkinter as tk
from tkinter import filedialog, messagebox
import os
import sys
import re
import ftplib
import subprocess
from media_processor import APP_VERSION, APPNAME
import media_processor.common as common
from ui.github_update_checker import GithubUpdateChecker
from ui.tools import Tools


class ConfigWindow:
    def __init__(self, root):
        self.window = tk.Toplevel(root)
        self.window.title(f"{APPNAME} {APP_VERSION} - Configuration")

        # Scrollable container
        main_frame = tk.Frame(self.window)
        main_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(main_frame)
        scrollbar = tk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        canvas_frame = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def on_canvas_configure(event):
            canvas.itemconfig(canvas_frame, width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        self.window.bind("<MouseWheel>", _on_mousewheel)
        
        cfg = common.get_config()
        
        # General
        lf_general = tk.LabelFrame(scrollable_frame, text="General")
        lf_general.pack(fill='x', padx=10, pady=10)
        
        tk.Label(lf_general, text="Scan/Input Dir:").grid(row=0, column=0, sticky='e', padx=5, pady=2)
        self.var_download_dir = tk.StringVar(value=cfg.download_dir)
        ent_dl_dir = tk.Entry(lf_general, textvariable=self.var_download_dir)
        ent_dl_dir.grid(row=0, column=1, sticky='ew', padx=5, pady=2)
        
        tk.Button(lf_general, text="...", command=lambda: self.var_download_dir.set(filedialog.askdirectory(initialdir=self.var_download_dir.get()) or self.var_download_dir.get()), width=3).grid(row=0, column=2, sticky='w', padx=5, pady=2)
        lf_general.columnconfigure(1, weight=1)

        # Autostart
        self.var_autostart = tk.BooleanVar(value=common.is_auto_start())

        chk_autostart = tk.Checkbutton(scrollable_frame, text="Run on startup", variable=self.var_autostart)
        if common.is_running_in_sandbox():
            chk_autostart.configure(state="disabled", text="Run on startup")
            chk_autostart.pack(anchor='w', padx=10, pady=(10, 0))
            
            link = tk.Label(scrollable_frame, text="Manage in Windows Settings", fg="blue", cursor="hand2")
            link.pack(anchor='w', padx=28, pady=(0, 10))
            link.bind("<Button-1>", lambda e: common.toggle_auto_start())
        else:
            chk_autostart.pack(anchor='w', padx=10, pady=10)
        
        # Update Check
        self.var_update_check = tk.BooleanVar(value=cfg.update_check_enabled == '1')
        chk_update = tk.Checkbutton(scrollable_frame, text="Check for updates", variable=self.var_update_check)
        chk_update.pack(anchor='w', padx=10, pady=(0, 10))

        # Postprocessing
        lf_pp = tk.LabelFrame(scrollable_frame, text="Postprocessing")
        lf_pp.pack(fill='x', padx=10, pady=10)
        
        self.var_pp_enabled = tk.BooleanVar(value=cfg.postprocessing_enabled == '1')
        self.var_pp_norm = tk.BooleanVar(value=cfg.pp_loudness_norm == '1')
        self.var_pp_mono = tk.BooleanVar(value=cfg.pp_mono == '1')
        self.var_pp_bitrate = tk.StringVar(value=cfg.pp_bitrate)
        
        def update_pp_state():
            state = 'normal' if self.var_pp_enabled.get() else 'disabled'
            chk_norm.configure(state=state)
            chk_mono.configure(state=state)
            ent_bitrate.configure(state=state)

        chk_pp_enabled = tk.Checkbutton(lf_pp, text="Enable postprocessing", variable=self.var_pp_enabled, command=update_pp_state)
        chk_pp_enabled.pack(anchor='w', padx=5, pady=5)
        
        tk.Label(lf_pp, text="(Output will be converted to MP3)", fg="gray").pack(anchor='w', padx=25, pady=(0, 5))
        
        frame_subs = tk.Frame(lf_pp)
        frame_subs.pack(fill='x', padx=20)
        
        chk_norm = tk.Checkbutton(frame_subs, text="Loudness normalization", variable=self.var_pp_norm)
        chk_norm.pack(anchor='w')
        
        chk_mono = tk.Checkbutton(frame_subs, text="Convert to mono", variable=self.var_pp_mono)
        chk_mono.pack(anchor='w')
        
        frame_bitrate = tk.Frame(frame_subs)
        frame_bitrate.pack(anchor='w', pady=5)
        tk.Label(frame_bitrate, text="Bitrate (kbps):").pack(side='left')
        ent_bitrate = tk.Entry(frame_bitrate, textvariable=self.var_pp_bitrate, width=5, validate='key', validatecommand=(self.window.register(lambda P: P.isdigit() or P == ""), '%P'))
        ent_bitrate.pack(side='left', padx=5)

        # Transfer Method
        lf_method = tk.LabelFrame(scrollable_frame, text="Transfer Method")
        lf_method.pack(fill='x', padx=10, pady=10)
        
        self.var_method = tk.StringVar(value=cfg.transfer_method)
        
        rb_ftp = tk.Radiobutton(lf_method, text="FTP (internal)", variable=self.var_method, value='ftp')
        rb_ftp.pack(side='left', padx=10, pady=5)
        
        rb_scp = tk.Radiobutton(lf_method, text="SCP (external scp.exe (SSH))", variable=self.var_method, value='scp')
        rb_scp.pack(side='left', padx=10, pady=5)

        rb_local = tk.Radiobutton(lf_method, text="Local Folder", variable=self.var_method, value='local')
        rb_local.pack(side='left', padx=10, pady=5)

        rb_adb = tk.Radiobutton(lf_method, text="ADB", variable=self.var_method, value='adb')
        rb_adb.pack(side='left', padx=10, pady=5)

        # Local Settings
        lf_local = tk.LabelFrame(scrollable_frame, text="Local Output Folder")
        lf_local.pack(fill='x', padx=10, pady=10)

        tk.Label(lf_local, text="Path:").grid(row=0, column=0, sticky='e', padx=5, pady=2)
        self.var_local_path = tk.StringVar(value=cfg.local_target_dir)
        ent_local_path = tk.Entry(lf_local, textvariable=self.var_local_path)
        ent_local_path.grid(row=0, column=1, sticky='ew', padx=5, pady=2)
        
        def browse_local():
            d = filedialog.askdirectory(initialdir=self.var_local_path.get())
            if d:
                self.var_local_path.set(d)
                
        tk.Button(lf_local, text="...", command=browse_local, width=3).grid(row=0, column=2, sticky='w', padx=5, pady=2)
        lf_local.columnconfigure(1, weight=1)

        # FTP Settings
        lf_ftp = tk.LabelFrame(scrollable_frame, text="FTP Settings")
        lf_ftp.pack(fill='x', padx=10, pady=10)

        # Server
        tk.Label(lf_ftp, text="Server:").grid(row=0, column=0, sticky='e', padx=5, pady=2)
        self.var_ftp_server = tk.StringVar(value=cfg.ftp_server)
        ent_ftp_server = tk.Entry(lf_ftp, textvariable=self.var_ftp_server)
        ent_ftp_server.grid(row=0, column=1, sticky='ew', padx=5, pady=2)

        # Port
        tk.Label(lf_ftp, text="Port:").grid(row=0, column=2, sticky='e', padx=5, pady=2)
        self.var_ftp_port = tk.StringVar(value=cfg.ftp_port)
        ent_ftp_port = tk.Entry(lf_ftp, textvariable=self.var_ftp_port, width=6)
        ent_ftp_port.grid(row=0, column=3, sticky='w', padx=5, pady=2)

        # User
        tk.Label(lf_ftp, text="User:").grid(row=1, column=0, sticky='e', padx=5, pady=2)
        self.var_ftp_user = tk.StringVar(value=cfg.ftp_user)
        ent_ftp_user = tk.Entry(lf_ftp, textvariable=self.var_ftp_user)
        ent_ftp_user.grid(row=1, column=1, sticky='ew', padx=5, pady=2)

        # Password
        tk.Label(lf_ftp, text="Pass:").grid(row=1, column=2, sticky='e', padx=5, pady=2)
        self.var_ftp_pass = tk.StringVar(value=cfg.ftp_pass)
        ent_ftp_pass = tk.Entry(lf_ftp, textvariable=self.var_ftp_pass, show="*")
        ent_ftp_pass.grid(row=1, column=3, sticky='ew', padx=5, pady=2)

        var_show_pass = tk.BooleanVar(value=False)
        def toggle_pass():
            ent_ftp_pass.config(show="" if var_show_pass.get() else "*")
        tk.Checkbutton(lf_ftp, text="Show", variable=var_show_pass, command=toggle_pass).grid(row=1, column=4, sticky='w', padx=2)

        # Remote Path
        tk.Label(lf_ftp, text="Path:").grid(row=2, column=0, sticky='e', padx=5, pady=2)
        self.var_ftp_path = tk.StringVar(value=cfg.ftp_remote_path)
        ent_ftp_path = tk.Entry(lf_ftp, textvariable=self.var_ftp_path)
        ent_ftp_path.grid(row=2, column=1, columnspan=4, sticky='ew', padx=5, pady=2)
        
        def test_ftp():
            try:
                ftp = ftplib.FTP(timeout=5)
                ftp.connect(self.var_ftp_server.get(), int(self.var_ftp_port.get()))
                ftp.login(self.var_ftp_user.get(), self.var_ftp_pass.get())
                ftp.cwd(self.var_ftp_path.get())
                ftp.quit()
                messagebox.showinfo("Success", "FTP connection successful.")
            except Exception as e:
                messagebox.showerror("Error", f"FTP connection failed: {e}")

        tk.Button(lf_ftp, text="Test Connection", command=test_ftp).grid(row=3, column=1, sticky='w', padx=5, pady=5)
        lf_ftp.columnconfigure(1, weight=1)

        # SCP Settings
        lf_scp = tk.LabelFrame(scrollable_frame, text="SCP Settings")
        lf_scp.pack(fill='x', padx=10, pady=10)

        # Server
        tk.Label(lf_scp, text="Server:").grid(row=0, column=0, sticky='e', padx=5, pady=2)
        self.var_scp_server = tk.StringVar(value=cfg.scp_server)
        ent_scp_server = tk.Entry(lf_scp, textvariable=self.var_scp_server)
        ent_scp_server.grid(row=0, column=1, sticky='ew', padx=5, pady=2)

        # Port
        tk.Label(lf_scp, text="Port:").grid(row=0, column=2, sticky='e', padx=5, pady=2)
        self.var_scp_port = tk.StringVar(value=cfg.scp_port)
        ent_scp_port = tk.Entry(lf_scp, textvariable=self.var_scp_port, width=6)
        ent_scp_port.grid(row=0, column=3, sticky='w', padx=5, pady=2)

        # User
        tk.Label(lf_scp, text="User:").grid(row=1, column=0, sticky='e', padx=5, pady=2)
        self.var_scp_user = tk.StringVar(value=cfg.scp_user)
        ent_scp_user = tk.Entry(lf_scp, textvariable=self.var_scp_user)
        ent_scp_user.grid(row=1, column=1, sticky='ew', padx=5, pady=2)

        # Key File
        tk.Label(lf_scp, text="Key:").grid(row=2, column=0, sticky='e', padx=5, pady=2)
        self.var_scp_key = tk.StringVar(value=cfg.scp_key_file)
        ent_scp_key = tk.Entry(lf_scp, textvariable=self.var_scp_key)
        ent_scp_key.grid(row=2, column=1, columnspan=2, sticky='ew', padx=5, pady=2)
        
        def browse_key():
            filename = filedialog.askopenfilename(title="Select Private Key")
            if filename:
                self.var_scp_key.set(filename)
                
        tk.Button(lf_scp, text="...", command=browse_key, width=3).grid(row=2, column=3, sticky='w', padx=5, pady=2)

        # Remote Path
        tk.Label(lf_scp, text="Path:").grid(row=3, column=0, sticky='e', padx=5, pady=2)
        self.var_scp_path = tk.StringVar(value=cfg.scp_remote_path)
        ent_scp_path = tk.Entry(lf_scp, textvariable=self.var_scp_path)
        ent_scp_path.grid(row=3, column=1, columnspan=3, sticky='ew', padx=5, pady=2)

        def test_scp():
            server = self.var_scp_server.get()
            port = self.var_scp_port.get()
            user = self.var_scp_user.get()
            key = self.var_scp_key.get()
            path = self.var_scp_path.get()
            
            cmd = ['ssh', '-p', port, '-i', key, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', f"{user}@{server}", f"cd \"{path}\""]
            
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                subprocess.run(cmd, check=True, startupinfo=startupinfo, capture_output=True, text=True)
                messagebox.showinfo("Success", "SSH connection successful.")
            except subprocess.CalledProcessError as e:
                messagebox.showerror("Error", f"SSH connection failed:\n{e.stderr}")
            except Exception as e:
                messagebox.showerror("Error", f"SSH connection failed: {e}")

        tk.Button(lf_scp, text="Test Connection", command=test_scp).grid(row=4, column=1, sticky='w', padx=5, pady=5)
        lf_scp.columnconfigure(1, weight=1)

        # ADB Fallback
        lf_adb = tk.LabelFrame(scrollable_frame, text="ADB Transfer")
        lf_adb.pack(fill='x', padx=10, pady=10)
        
        self.var_adb_enabled = tk.BooleanVar(value=cfg.adb_fallback_enabled == '1')
        chk_adb = tk.Checkbutton(lf_adb, text="Enable ADB Fallback (if other methods fail)", variable=self.var_adb_enabled)
        chk_adb.grid(row=0, column=0, columnspan=3, sticky='w', padx=5, pady=5)
        
        tk.Label(lf_adb, text="Tools Path:").grid(row=2, column=0, sticky='e', padx=5, pady=2)
        self.var_adb_path = tk.StringVar(value=cfg.adb_tools_path)
        ent_adb_path = tk.Entry(lf_adb, textvariable=self.var_adb_path)
        ent_adb_path.grid(row=2, column=1, sticky='ew', padx=5, pady=2)
        
        def browse_adb():
            d = filedialog.askdirectory(initialdir=self.var_adb_path.get())
            if d:
                self.var_adb_path.set(d)
        
        tk.Button(lf_adb, text="...", command=browse_adb, width=3).grid(row=2, column=2, sticky='w', padx=5, pady=2)
        
        tk.Label(lf_adb, text="Remote Path:").grid(row=3, column=0, sticky='e', padx=5, pady=2)
        self.var_adb_remote = tk.StringVar(value=cfg.adb_remote_path)
        ent_adb_remote = tk.Entry(lf_adb, textvariable=self.var_adb_remote)
        ent_adb_remote.grid(row=3, column=1, columnspan=2, sticky='ew', padx=5, pady=2)
        
        def test_adb():
            adb_exe = "adb"
            tools_path = self.var_adb_path.get()
            if tools_path:
                adb_exe = os.path.join(tools_path, "adb")
            
            remote_path = self.var_adb_remote.get()
            if not remote_path:
                remote_path = "/sdcard/Download/"
            
            startupinfo = None
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            except AttributeError:
                pass

            if sys.platform == 'win32':
                try:
                    proc_ver = subprocess.run([adb_exe, "--version"], capture_output=True, text=True, startupinfo=startupinfo)
                    if re.search(r"36\.0\.1(?!\d)", proc_ver.stdout):
                         messagebox.showwarning("ADB Warning", "ADB version 36.0.1 detected.\nThis version is known to be buggy on Windows.\nPlease update your platform-tools.")
                except Exception:
                    pass

            device_serial = None
            try:
                proc = subprocess.run([adb_exe, "devices"], capture_output=True, text=True, startupinfo=startupinfo)
                for line in proc.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == 'device':
                        if not parts[0].startswith("emulator-"):
                            device_serial = parts[0]
                            break
            except Exception:
                pass

            cmd = [adb_exe]
            if device_serial:
                cmd.extend(["-s", device_serial])
            cmd.extend(["shell", f"cd \"{remote_path}\""])
            
            try:
                subprocess.run(cmd, check=True, startupinfo=startupinfo, capture_output=True, text=True)
                messagebox.showinfo("Success", f"ADB connection successful.\nDirectory '{remote_path}' exists.")
            except subprocess.CalledProcessError as e:
                messagebox.showerror("Error", f"ADB connection failed:\n{e.stderr}")
            except Exception as e:
                messagebox.showerror("Error", f"ADB connection failed: {e}")

        tk.Button(lf_adb, text="Test Connection", command=test_adb).grid(row=4, column=1, sticky='w', padx=5, pady=5)
        
        lf_adb.columnconfigure(1, weight=1)

        update_pp_state()

        # Buttons Frame
        btn_frame = tk.Frame(self.window)
        btn_frame.pack(fill='x', padx=10, pady=10)

        tk.Button(btn_frame, text="Save", command=self.on_save, width=10).pack(side='right', padx=5)
        tk.Button(btn_frame, text="Cancel", command=self.window.destroy, width=10).pack(side='right', padx=5)

        Tools.center_window(self.window, 600, 800)


    def on_save(self):
        # Autostart
        if not common.is_running_in_sandbox():
            current_auto = common.is_auto_start()
            desired_auto = self.var_autostart.get()
            if current_auto != desired_auto:
                common.toggle_auto_start()

        # DB Config
        cfg = common.get_config()
        cfg.download_dir = self.var_download_dir.get()
        cfg.update_check_enabled = '1' if self.var_update_check.get() else '0'
        cfg.postprocessing_enabled = '1' if self.var_pp_enabled.get() else '0'
        cfg.pp_loudness_norm = '1' if self.var_pp_norm.get() else '0'
        cfg.pp_mono = '1' if self.var_pp_mono.get() else '0'
        cfg.pp_bitrate = self.var_pp_bitrate.get()
        cfg.transfer_method = self.var_method.get()
        cfg.ftp_server = self.var_ftp_server.get()
        cfg.ftp_port = self.var_ftp_port.get()
        cfg.ftp_user = self.var_ftp_user.get()
        cfg.ftp_pass = self.var_ftp_pass.get()
        cfg.ftp_remote_path = self.var_ftp_path.get()
        cfg.scp_server = self.var_scp_server.get()
        cfg.scp_port = self.var_scp_port.get()
        cfg.scp_user = self.var_scp_user.get()
        cfg.scp_key_file = self.var_scp_key.get()
        cfg.scp_remote_path = self.var_scp_path.get()
        cfg.local_target_dir = self.var_local_path.get()
        cfg.adb_fallback_enabled = '1' if self.var_adb_enabled.get() else '0'
        cfg.adb_tools_path = self.var_adb_path.get()
        cfg.adb_remote_path = self.var_adb_remote.get()
        
        cfg.save()
        
        uc = GithubUpdateChecker.get_instance()
        if uc:
            if cfg.update_check_enabled == '1':
                uc.start()
            else:
                uc.stop()

        self.window.destroy()

    def winfo_exists(self):
        return self.window.winfo_exists()