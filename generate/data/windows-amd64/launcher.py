import os
import sys
import threading
import subprocess
import webbrowser
import customtkinter as ctk
from tkinter import filedialog, messagebox

# Set appearance mode and default color theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# List of steps directly scraped from generator.py
ALL_STEPS = [
    "validate", "app", "auth", "middleware", "rbac", "storage", "imap",
    "notifications", "chat", "models", "models_handler", "models_dtos",
    "models_repo", "models_response", "models_controller", "models_graphql",
    "graphql", "grpc", "routes", "api_client", "format"
]

class FiberGeneratorLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("GoFiber Backend Generator - Custom Control Panel")
        self.geometry("900x750")
        
        # Grid layout 1x2 (left sidebar, right content)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        
        # --- Sidebar ---
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(4, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="⚡ GoFiberGen", font=ctk.CTkFont(size=24, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.btn_open_template = ctk.CTkButton(self.sidebar_frame, text="📄 View Template", command=lambda: self.open_file("configexample/config.yaml"))
        self.btn_open_template.grid(row=1, column=0, padx=20, pady=10)
        
        self.btn_open_prompt = ctk.CTkButton(self.sidebar_frame, text="🤖 View AI Prompt", command=lambda: self.open_file("AI_YML_GENERATOR_PROMPT.md"))
        self.btn_open_prompt.grid(row=2, column=0, padx=20, pady=10)
        
        self.btn_open_master = ctk.CTkButton(self.sidebar_frame, text="⚙️ Master Config", command=lambda: self.open_file("master_config.yaml"))
        self.btn_open_master.grid(row=3, column=0, padx=20, pady=10)

        # --- Right Content ---
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(2, weight=1)

        # 1. Config Picker
        self.config_frame = ctk.CTkFrame(self.main_frame)
        self.config_frame.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        self.config_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(self.config_frame, text="Target Config:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=10, pady=10)
        self.config_var = ctk.StringVar(value="master_config.yaml")
        self.config_entry = ctk.CTkEntry(self.config_frame, textvariable=self.config_var)
        self.config_entry.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        
        self.btn_browse = ctk.CTkButton(self.config_frame, text="Browse", width=80, command=self.browse_config)
        self.btn_browse.grid(row=0, column=2, padx=(0, 10))

        # Output Folder Picker
        ctk.CTkLabel(self.config_frame, text="Output Directory:", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, padx=10, pady=(0, 10))
        self.output_var = ctk.StringVar(value="./generated")
        self.output_entry = ctk.CTkEntry(self.config_frame, textvariable=self.output_var)
        self.output_entry.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(0, 10))
        
        self.btn_browse_out = ctk.CTkButton(self.config_frame, text="Browse", width=80, command=self.browse_output)
        self.btn_browse_out.grid(row=1, column=2, padx=(0, 10), pady=(0, 10))

        # 2. Generator Options
        self.opts_frame = ctk.CTkScrollableFrame(self.main_frame, label_text="Generator Modules", height=200)
        self.opts_frame.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        self.opts_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        
        self.step_vars = {}
        for i, step in enumerate(ALL_STEPS):
            var = ctk.BooleanVar(value=True)
            self.step_vars[step] = var
            chk = ctk.CTkCheckBox(self.opts_frame, text=step.replace("_", " ").title(), variable=var)
            chk.grid(row=i // 4, column=i % 4, sticky="w", padx=10, pady=5)

        # 3. Execution Console
        self.console = ctk.CTkTextbox(self.main_frame, font=ctk.CTkFont("Consolas", 12), text_color="#2ECC71", state="disabled", height=200)
        self.console.grid(row=2, column=0, sticky="nsew", pady=(0, 20))

        # 4. Run Button
        self.btn_run = ctk.CTkButton(self.main_frame, text="▶ LAUNCH GENERATOR", font=ctk.CTkFont(size=16, weight="bold"), height=50, fg_color="#27AE60", command=self.run_generation)
        self.btn_run.grid(row=3, column=0, sticky="ew")

    def browse_config(self):
        filename = filedialog.askopenfilename()
        if filename: self.config_var.set(os.path.relpath(filename, os.getcwd()))

    def browse_output(self):
        dirname = filedialog.askdirectory()
        if dirname: self.output_var.set(os.path.relpath(dirname, os.getcwd()))

    def open_file(self, filepath):
        if os.path.exists(filepath):
            webbrowser.open(filepath)

    def log(self, msg):
        self.console.configure(state="normal")
        self.console.insert("end", msg + "\n")
        self.console.see("end")
        self.console.configure(state="disabled")

    def run_generation(self):
        cmd = [sys.executable, "generator.py", "--config", self.config_var.get(), "--output", self.output_var.get()]
        skipped = [s for s, v in self.step_vars.items() if not v.get()]
        if skipped:
            cmd.extend(["--skip"] + skipped)
        
        self.btn_run.configure(state="disabled", text="⏳ RUNNING...")
        self.log(f"⚡ Starting: {' '.join(cmd)}")
        threading.Thread(target=self._execute, args=(cmd,), daemon=True).start()

    def _execute(self, cmd):
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in iter(process.stdout.readline, ""):
            self.after(0, self.log, line.strip())
        process.wait()
        self.after(0, lambda: self.btn_run.configure(state="normal", text="▶ LAUNCH GENERATOR"))
        self.after(0, lambda: self.log("\n✅ Generation Complete!"))

def main():
    app = FiberGeneratorLauncher()
    app.mainloop()

if __name__ == "__main__":
    main()
