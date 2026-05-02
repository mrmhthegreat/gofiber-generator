#!/usr/bin/env python3
import os
import yaml
import json
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext

CONFIG_FILE = "master_config.yaml"

class GoFiberNativeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Go Fiber CLI & YAML Configurator")
        self.root.geometry("1100x750")

        # Set theme if available
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
            
        self.config_data = {}
        self.node_map = {} # Maps tree item -> path list (e.g. ['database', 'port'])
        
        self.setup_ui()
        self.load_config()

    def setup_ui(self):
        # ── Toolbar ─────────────────────────────────────────────────────────────
        toolbar = ttk.Frame(self.root, padding=5)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="Load master_config.yaml", command=self.load_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="Save Config", command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        
        gen_btn = ttk.Button(toolbar, text="Run Full Generator", command=self.run_generation)
        gen_btn.pack(side=tk.LEFT, padx=5)
        # Highlight generator button
        style = ttk.Style()
        style.configure("Accent.TButton", foreground="green", font=("Arial", 10, "bold"))
        gen_btn.configure(style="Accent.TButton")

        # ── Main Paned Window ───────────────────────────────────────────────────
        self.paned_main = tk.PanedWindow(self.root, orient=tk.VERTICAL, sashwidth=6, bg="#ccc")
        self.paned_main.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Upper pane: Tree & Edit
        self.upper_pane = tk.PanedWindow(self.paned_main, orient=tk.HORIZONTAL, sashwidth=6, bg="#ccc")
        self.paned_main.add(self.upper_pane, minsize=300)

        # Bottom pane: Console
        self.console_frame = ttk.LabelFrame(self.paned_main, text=" Generator Logs ")
        self.paned_main.add(self.console_frame, minsize=100)

        # ── Tree Frame ──
        tree_frame = ttk.Frame(self.upper_pane)
        self.upper_pane.add(tree_frame, minsize=400)

        tree_scroll = ttk.Scrollbar(tree_frame)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree = ttk.Treeview(tree_frame, columns=("Type", "Value"), yscrollcommand=tree_scroll.set)
        self.tree.heading("#0", text="Key / Property")
        self.tree.heading("Type", text="Type")
        self.tree.heading("Value", text="Value")
        self.tree.column("#0", width=300, minwidth=200)
        self.tree.column("Type", width=80, minwidth=50, stretch=tk.NO)
        self.tree.column("Value", width=250, minwidth=150)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.config(command=self.tree.yview)

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        # ── Editor Frame ──
        self.edit_frame = ttk.LabelFrame(self.upper_pane, text=" Property Editor ", padding=10)
        self.upper_pane.add(self.edit_frame, minsize=250)

        ttk.Label(self.edit_frame, text="Key Path:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.lbl_path = ttk.Label(self.edit_frame, text="", foreground="blue", wraplength=300)
        self.lbl_path.grid(row=0, column=1, sticky=tk.W, pady=2)

        ttk.Label(self.edit_frame, text="Value:").grid(row=1, column=0, sticky=tk.NW, pady=5)
        self.val_entry = tk.Text(self.edit_frame, height=5, width=40, font=("Consolas", 10))
        self.val_entry.grid(row=1, column=1, sticky=tk.EW, pady=5)

        btn_frame = ttk.Frame(self.edit_frame)
        btn_frame.grid(row=2, column=1, sticky=tk.E, pady=10)
        ttk.Button(btn_frame, text="Apply Change", command=self.apply_edit).pack(side=tk.RIGHT)

        ttk.Separator(self.edit_frame, orient=tk.HORIZONTAL).grid(row=3, column=0, columnspan=2, sticky="ew", pady=15)
        
        # Tools to add/remove structure
        struct_frame = ttk.Frame(self.edit_frame)
        struct_frame.grid(row=4, column=0, columnspan=2, sticky=tk.W)
        
        ttk.Label(struct_frame, text="New Key:").grid(row=0, column=0, padx=2)
        self.new_key_var = tk.StringVar()
        ttk.Entry(struct_frame, textvariable=self.new_key_var, width=15).grid(row=0, column=1, padx=2)
        
        self.new_type_var = tk.StringVar(value="String")
        ttk.Combobox(struct_frame, textvariable=self.new_type_var, values=["String", "Dict", "List", "Integer", "Boolean"], width=8, state="readonly").grid(row=0, column=2, padx=2)

        ttk.Button(struct_frame, text="Add Key", command=self.add_dict_key).grid(row=0, column=3, padx=2)
        ttk.Button(struct_frame, text="Add List Item", command=self.add_list_item).grid(row=1, column=3, padx=2, pady=5)
        ttk.Button(struct_frame, text="Delete Selected", command=self.delete_selected).grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=10)

        # ── Console ──
        self.console = scrolledtext.ScrolledText(self.console_frame, wrap=tk.WORD, bg="black", fg="lime", font=("Consolas", 10), state=tk.DISABLED)
        self.console.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            self.log_console(f"[ERROR] {CONFIG_FILE} not found!\n")
            return
        try:
            with open(CONFIG_FILE, "r") as f:
                self.config_data = yaml.safe_load(f)
            self.refresh_tree()
            self.log_console(f"[INFO] Loaded {CONFIG_FILE}\n")
        except Exception as e:
            messagebox.showerror("YAML Load Error", str(e))

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                yaml.dump(self.config_data, f, sort_keys=False, default_flow_style=False)
            self.log_console(f"[INFO] Saved configuration to {CONFIG_FILE}\n")
        except Exception as e:
            messagebox.showerror("YAML Save Error", str(e))

    def refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.node_map.clear()
        self.build_tree("", self.config_data, [])

    def build_tree(self, parent_id, data, path):
        if isinstance(data, dict):
            for k, v in data.items():
                node_id = self.tree.insert(parent_id, "end", text=str(k), values=("dict", ""))
                self.node_map[node_id] = path + [k]
                self.build_tree(node_id, v, path + [k])
        elif isinstance(data, list):
            for i, v in enumerate(data):
                node_id = self.tree.insert(parent_id, "end", text=f"Index [{i}]", values=("list", ""))
                self.node_map[node_id] = path + [i]
                self.build_tree(node_id, v, path + [i])
        else:
            # Scalar value
            t = type(data).__name__
            val_str = str(data) if data is not None else "null"
            self.tree.item(parent_id, values=(t, val_str))
            
    def get_data_at_path(self, path):
        curr = self.config_data
        for p in path:
            curr = curr[p]
        return curr

    def set_data_at_path(self, path, value):
        curr = self.config_data
        for p in path[:-1]:
            curr = curr[p]
        curr[path[-1]] = value

    def on_tree_select(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        
        node_id = selected[0]
        path = self.node_map.get(node_id)
        if path is None:
            return
        
        self.lbl_path.config(text=" -> ".join(str(p) for p in path))
        
        val = self.get_data_at_path(path)
        self.val_entry.delete("1.0", tk.END)

        if not isinstance(val, (dict, list)):
            self.val_entry.insert(tk.END, str(val) if val is not None else "")
            self.val_entry.config(state=tk.NORMAL)
        else:
            self.val_entry.insert(tk.END, f"<{type(val).__name__} node>")
            self.val_entry.config(state=tk.DISABLED)

    def apply_edit(self):
        selected = self.tree.selection()
        if not selected: return
        node_id = selected[0]
        path = self.node_map.get(node_id)
        if not path: return
        
        curr_val = self.get_data_at_path(path)
        if isinstance(curr_val, (dict, list)):
            messagebox.showwarning("Warning", "Cannot edit raw value of a dictionary or list node.")
            return

        new_val_str = self.val_entry.get("1.0", tk.END).strip()
        
        # Determine exact type and cast
        new_val = new_val_str
        if new_val_str.lower() in ("true", "false"):
            new_val = new_val_str.lower() == "true"
        elif new_val_str.isdigit():
            new_val = int(new_val_str)
        elif new_val_str.replace('.','',1).isdigit():
            new_val = float(new_val_str)
        elif new_val_str == "null":
            new_val = None

        self.set_data_at_path(path, new_val)
        self.refresh_tree()
        self.log_console(f"[CMD] Updated property `{' -> '.join(str(p) for p in path)}`\n")
        
        # Reselect
        self.tree.selection_set(node_id)

    def get_initial_value_for_type(self):
        t = self.new_type_var.get()
        if t == "Dict": return {}
        if t == "List": return []
        if t == "Integer": return 0
        if t == "Boolean": return False
        return ""

    def add_dict_key(self):
        selected = self.tree.selection()
        if not selected: return
        node_id = selected[0]
        path = self.node_map.get(node_id)
        
        new_key = self.new_key_var.get().strip()
        if not new_key:
            messagebox.showwarning("Warning", "Key name cannot be empty")
            return
            
        target = self.get_data_at_path(path)
        if not isinstance(target, dict):
            messagebox.showwarning("Warning", "Selected node is not a dictionary. Cannot add key.")
            return

        target[new_key] = self.get_initial_value_for_type()
        self.new_key_var.set("")
        self.refresh_tree()

    def add_list_item(self):
        selected = self.tree.selection()
        if not selected: return
        node_id = selected[0]
        path = self.node_map.get(node_id)
        
        target = self.get_data_at_path(path)
        if not isinstance(target, list):
            messagebox.showwarning("Warning", "Selected node is not a list.")
            return

        target.append(self.get_initial_value_for_type())
        self.refresh_tree()

    def delete_selected(self):
        selected = self.tree.selection()
        if not selected: return
        if messagebox.askyesno("Confirm", "Delete selected property and all its children?"):
            for node_id in selected:
                path = self.node_map.get(node_id)
                if not path: continue
                
                parent_path = path[:-1]
                key = path[-1]
                
                if not parent_path:
                    del self.config_data[key]
                else:
                    curr = self.get_data_at_path(parent_path)
                    if isinstance(curr, list):
                        curr.pop(key)
                    else:
                        del curr[key]
                        
            self.refresh_tree()

    def log_console(self, text):
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, text)
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)

    def run_generation(self):
        self.save_config()
        self.log_console("\n> python generator.py\n")
        
        def pipe_reader(pipe):
            with pipe:
                for line in iter(pipe.readline, ''):
                    self.root.after(0, self.log_console, line)

        def runner():
            try:
                process = subprocess.Popen(
                    ["python", "generator.py"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                
                t = threading.Thread(target=pipe_reader, args=(process.stdout,))
                t.start()
                process.wait()
                t.join()
                
                if process.returncode == 0:
                    self.root.after(0, self.log_console, "\n[SUCCESS] Code Generation Completed!\n")
                else:
                    self.root.after(0, self.log_console, f"\n[ERROR] Process exited with status {process.returncode}\n")
            except Exception as e:
                self.root.after(0, self.log_console, f"\n[ERROR] Execution failed: {e}\n")

        threading.Thread(target=runner, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = GoFiberNativeGUI(root)
    root.mainloop()
