#!/usr/bin/env python3
"""
api_client_generator.py — Tkinter API Test Client Generator
============================================================
Reads master_config.yaml and generates a ready-to-run api_client.py
that contains a Tkinter UI pre-populated with every endpoint defined
in the config (auth, CRUD models, FCM, IMAP, RBAC, chat, notifications).

Each generated endpoint entry is a tuple:
    (HTTP_METHOD, path, auth_level, sample_payload_dict)

Auth levels:
    "guest"         — requires only X-API-Key
    "app_token"     — requires app-check token + HMAC signature
    "authenticated" — requires Bearer JWT

Usage (standalone):
    python api_client_generator.py --config master_config.yaml
    python api_client_generator.py --config master_config.yaml --output ./api_client_generated.py

Usage (imported by generator.py):
    from generators.api_client_generator import run
    run(config_path, templates_dir, output_dir)
"""

import os
import sys
import argparse
import yaml
import textwrap
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get(d: dict, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
        if cur is None:
            return default
    return cur


def _enabled(d: dict, *keys) -> bool:
    return bool(_get(d, *keys, default=False))


def _repr(val: Any) -> str:
    """Python repr for a value — used inside the generated source file."""
    return repr(val)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_endpoints(cfg: dict) -> dict:
    """
    Build the full endpoint dictionary for the generated client.

    Returns a dict of { category: { label: (method, path, auth_level, payload) } }
    """
    auth  = cfg.get("authentication", {})
    ep    = auth.get("email_password", {})
    ev    = auth.get("email_verification", {})
    sa    = auth.get("social_auth", {})
    rt    = auth.get("refresh_token", {})

    base  = cfg.get("server", {}).get("port", "3000")
    sections: dict[str, dict] = {}

    # ── Authentication ───────────────────────────────────────────────────────
    auth_section: dict = {}

    # Guest / app-check tokens
    for tok in auth.get("app_check_tokens", []):
        if tok.get("enabled"):
            label = f"Get {tok.get('name', 'App Token')}"
            path  = tok.get('path', '/api/auth/guest-token')
            auth_section[label] = ("POST", path, "guest", {"app_id": "your_app_id"})

    if ep.get("enabled"):
        # Registration fields as sample payload
        reg_fields = _get(cfg, "authentication", "identifier", "register_fields", default=[])
        reg_payload: dict = {}
        type_samples = {
            "string": "example_value",
            "email":  "user@example.com",
            "password": "password123",
            "phone":  "+1234567890",
            "int":    1,
            "bool":   False,
        }
        for f in reg_fields:
            fname = f.get("name", "field")
            ftype = f.get("type", "string")
            reg_payload[fname] = type_samples.get(ftype, "value")

        auth_section["Register"] = ("POST", "/api/auth/register", "app_token", reg_payload)
        auth_section["Login"]    = ("POST", "/api/auth/login",    "app_token", {
            "email":    "user@example.com",
            "password": "password123",
        })

        fp = ep.get("forgot_password", {})
        if fp.get("enabled"):
            auth_section["Forgot Password"] = ("POST", "/api/auth/forgot-password", "app_token", {"email": "user@example.com"})
            auth_section["Reset Password"]  = ("POST", "/api/auth/reset-password",  "app_token", {
                "email": "user@example.com", "otp": "123456", "new_password": "newpassword123"
            })

    if ev.get("enabled"):
        auth_section["Verify Email"]        = ("POST", "/api/user/verify-email",        "authenticated", {"otp": "123456"})
        auth_section["Resend Verification"] = ("POST", "/api/user/resend-verification", "authenticated", {})

    if rt.get("enabled"):
        auth_section["Refresh Token"] = ("POST", "/api/auth/refresh", "app_token", {})

    if sa.get("google", {}).get("enabled"):
        auth_section["Google Login"]   = ("POST", "/api/auth/google",   "app_token", {"id_token": "google_id_token"})
    if sa.get("facebook", {}).get("enabled"):
        auth_section["Facebook Login"] = ("POST", "/api/auth/facebook", "app_token", {"access_token": "fb_access_token"})
    if sa.get("apple", {}).get("enabled"):
        auth_section["Apple Login"]    = ("POST", "/api/auth/apple",    "app_token", {"id_token": "apple_id_token"})

    if auth_section:
        sections["Authentication"] = auth_section

    # ── User Profile ─────────────────────────────────────────────────────────
    user_section: dict = {
        "Get Profile":     ("GET",   "/api/user/profile",          "authenticated", {}),
        "Update Profile":  ("PUT",   "/api/user/profile",          "authenticated", {"name": "Updated Name"}),
        "Change Password": ("POST",  "/api/user/change-password",  "authenticated", {
            "old_password": "old123", "new_password": "new456"
        }),
    }
    sections["User Profile"] = user_section

    # ── Models (dynamic CRUD) ─────────────────────────────────────────────────
    for model in cfg.get("models", []):
        name  = model.get("name", "Model")
        ctrl  = model.get("controller", {})
        bp    = ctrl.get("base_path", f"/api/{name.lower()}s").rstrip("/")
        if not bp.startswith("/api"):
            bp = "/api" + bp

        if not ctrl.get("enabled", True):
            continue

        model_section: dict = {}
        fields = model.get("fields", [])
        sample: dict = {}
        for f in fields:
            ft = f.get("type", "string")
            fn = f.get("name", "field")
            if fn in ("id", "ID", "CreatedAt", "UpdatedAt", "DeletedAt"):
                continue
            sample_val: Any = {
                "string": f"sample_{fn}",
                "int": 1, "int64": 1, "uint": 1, "uint64": 1,
                "float64": 1.0, "float32": 1.0,
                "bool": False,
                "time.Time": "2025-01-01T00:00:00Z",
            }.get(ft, f"sample_{fn}")
            sample[fn] = sample_val

        if ctrl.get("List", {}).get("enabled", True) or ctrl.get("GetList", {}).get("enabled"):
            model_section[f"List {name}s"] = ("GET", f"{bp}", "authenticated", {})
        if ctrl.get("Get", {}).get("enabled", True):
            model_section[f"Get {name}"]   = ("GET", f"{bp}/1", "authenticated", {})
        if ctrl.get("Create", {}).get("enabled", True):
            model_section[f"Create {name}"] = ("POST", f"{bp}", "authenticated", sample)
        if ctrl.get("Update", {}).get("enabled", True):
            model_section[f"Update {name}"] = ("PUT", f"{bp}/1", "authenticated", sample)
        if ctrl.get("Delete", {}).get("enabled", True):
            model_section[f"Delete {name}"] = ("DELETE", f"{bp}/1", "authenticated", {})

        # Custom operations
        for op_key, op in ctrl.items():
            if isinstance(op, dict) and op.get("type") == "custom" and op.get("enabled"):
                method = op.get("method", "GET").upper()
                path   = op.get("path", f"/{op_key.lower()}")
                label  = op.get("name", op_key)
                model_section[label] = (method, f"{bp}{path}", "authenticated", {})

        if model_section:
            sections[name] = model_section

    # ── FCM ──────────────────────────────────────────────────────────────────
    fcm = cfg.get("fcm", {})
    if fcm.get("enabled") and fcm.get("controller", {}).get("enabled"):
        fc   = fcm["controller"]
        bp   = fc.get("base_path", "/api/fcm").replace("/api", "")
        fcm_section: dict = {}
        if fc.get("SendFCM", {}).get("enabled"):
            fcm_section["Send FCM Push"] = ("POST", f"/api{bp}/send", "authenticated", {
                "title": "Test", "body": "Hello!", "topic": "general"
            })
        if fc.get("SubscribeToTopic", {}).get("enabled"):
            fcm_section["Subscribe to Topic"] = ("POST", f"/api{bp}/subscribe", "authenticated", {
                "topic": "general", "token": "fcm_device_token"
            })
        fcm_section["Get FCM Users"] = ("GET", f"/api{bp}/users", "authenticated", {})
        sections["FCM"] = fcm_section

    # ── IMAP / Email ─────────────────────────────────────────────────────────
    imap = cfg.get("imap", {})
    if imap.get("enabled") and imap.get("controller", {}).get("enabled"):
        ic   = imap["controller"]
        bp   = ic.get("base_path", "/api/emails").replace("/api", "")
        imap_section: dict = {}
        if ic.get("GetEmailsList", {}).get("enabled"):
            imap_section["List Emails"]       = ("GET",   f"/api{bp}/",         "authenticated", {})
        if ic.get("GetEmailDetail", {}).get("enabled"):
            imap_section["Get Email Details"] = ("GET",   f"/api{bp}/1",        "authenticated", {})
        if ic.get("SendEmail", {}).get("enabled"):
            imap_section["Send Email"]        = ("POST",  f"/api{bp}/compose",  "authenticated", {
                "to": "recipient@example.com", "subject": "Hello", "body": "Email body"
            })
        if ic.get("MarkEmailRead", {}).get("enabled"):
            imap_section["Mark Email Read"]   = ("PATCH", f"/api{bp}/1/read",   "authenticated", {})
        if ic.get("RefreshEmails", {}).get("enabled"):
            imap_section["Refresh Emails"]    = ("POST",  f"/api{bp}/refresh",  "authenticated", {})
        sections["Email (IMAP)"] = imap_section

    # ── RBAC ─────────────────────────────────────────────────────────────────
    rbac = cfg.get("rbac", {})
    if rbac.get("enabled") and rbac.get("controller", {}).get("enabled"):
        rc   = rbac["controller"]
        bp   = rc.get("base_path", "/api/rbac").replace("/api", "")
        rbac_section: dict = {}
        if rc.get("ListRoles",       {}).get("enabled"): rbac_section["List Roles"]           = ("GET",    f"/api{bp}/roles",               "authenticated", {})
        if rc.get("GetRole",         {}).get("enabled"): rbac_section["Get Role"]             = ("GET",    f"/api{bp}/roles/1",             "authenticated", {})
        if rc.get("CreateRole",      {}).get("enabled"): rbac_section["Create Role"]          = ("POST",   f"/api{bp}/roles",               "authenticated", {"name": "new_role", "display_name": "New Role"})
        if rc.get("UpdateRole",      {}).get("enabled"): rbac_section["Update Role"]          = ("PUT",    f"/api{bp}/roles/1",             "authenticated", {"name": "updated_role"})
        if rc.get("DeleteRole",      {}).get("enabled"): rbac_section["Delete Role"]          = ("DELETE", f"/api{bp}/roles/1",             "authenticated", {})
        if rc.get("ListPermissions", {}).get("enabled"): rbac_section["List Permissions"]     = ("GET",    f"/api{bp}/permissions",         "authenticated", {})
        if rc.get("SyncPermissions", {}).get("enabled"): rbac_section["Sync Permissions"]     = ("POST",   f"/api{bp}/permissions/sync",    "authenticated", {})
        if rc.get("BulkUpdateRolePermissions", {}).get("enabled"):
            rbac_section["Bulk Update Role Perms"] = ("PUT", f"/api{bp}/roles/1/permissions/bulk", "authenticated", {"permissions": ["perm.key"]})
        if rc.get("GetUserOverrides", {}).get("enabled"): rbac_section["Get User Overrides"]  = ("GET",    f"/api{bp}/users/1/overrides",   "authenticated", {})
        if rc.get("SetUserOverride",  {}).get("enabled"): rbac_section["Set User Override"]   = ("POST",   f"/api{bp}/users/1/overrides",   "authenticated", {"permission": "perm.key", "granted": True})
        if rc.get("GetUserPermissions", {}).get("enabled"): rbac_section["Get User Perms Debug"] = ("GET", f"/api{bp}/users/1/permissions/debug", "authenticated", {})
        if rc.get("InvalidateCache",  {}).get("enabled"): rbac_section["Invalidate Cache"]     = ("POST",  f"/api{bp}/cache/invalidate/1",  "authenticated", {})
        if rc.get("CheckPermission",  {}).get("enabled"): rbac_section["Check Permission"]     = ("POST",  f"/api{bp}/check",               "authenticated", {"user_id": 1, "permission": "perm.key"})
        rbac_section["My Permissions"] = ("GET", f"/api{bp}/me/permissions", "authenticated", {})
        sections["RBAC"] = rbac_section

    # ── Notifications ─────────────────────────────────────────────────────────
    notif = cfg.get("notifications", {})
    if notif.get("enabled") and notif.get("controller", {}).get("enabled"):
        nc  = notif["controller"]
        bp  = nc.get("base_path", "/api/notifications").replace("/api", "")
        sections["Notifications"] = {
            "List Notifications":  ("GET",   f"/api{bp}/",   "authenticated", {}),
            "Mark Read":           ("PATCH",  f"/api{bp}/1/read", "authenticated", {}),
        }

    # ── Chat ─────────────────────────────────────────────────────────────────
    chat = cfg.get("chat", {})
    if chat.get("enabled") and chat.get("controller", {}).get("enabled"):
        cc = chat["controller"]
        bp = cc.get("base_path", "/api/chat").replace("/api", "")
        sections["Chat"] = {
            "Get Conversations":   ("GET",  f"/api{bp}/conversations",    "authenticated", {}),
            "Get Chat History":    ("GET",  f"/api{bp}/history/1",        "authenticated", {}),
            "Send Message":        ("POST", f"/api{bp}/send",             "authenticated", {"to_user_id": 1, "content": "Hello!"}),
            "Mark Conversation Read": ("POST", f"/api{bp}/mark-read/1",  "authenticated", {}),
        }

    return sections


# ─────────────────────────────────────────────────────────────────────────────
# Code generator
# ─────────────────────────────────────────────────────────────────────────────

def _generate_source(cfg: dict, sections: dict) -> str:
    """Render the final api_client.py source string."""

    server_cfg = cfg.get("server", {})
    port       = server_cfg.get("port", "3000")
    module     = cfg.get("project", {}).get("module", "github.com/user/project")
    title      = f"{module.split('/')[-1].replace('-', ' ').replace('_', ' ').title()} API Tester"

    # Find app-check token details for defaults
    app_tokens = cfg.get("authentication", {}).get("app_check_tokens", [])
    api_key_env   = ""
    sign_secret_env = ""
    for tok in app_tokens:
        if tok.get("enabled"):
            api_key_env     = tok.get("api_key_env",    "")
            sign_secret_env = tok.get("sign_secret_env", "")
            break

    # Render the endpoints dict block
    ep_lines = ["        self.endpoints = {\n"]
    for category, endpoints in sections.items():
        ep_lines.append(f"            {_repr(category)}: {{\n")
        for label, entry in endpoints.items():
            method, path, auth, payload = entry
            ep_lines.append(
                f"                {_repr(label)}: ({_repr(method)}, {_repr(path)}, {_repr(auth)}, {_repr(payload)}),\n"
            )
        ep_lines.append("            },\n")
    ep_lines.append("        }\n")
    ep_block = "".join(ep_lines)

    return textwrap.dedent(f"""\
#!/usr/bin/env python3
\"\"\"
{title}
Generated by api_client_generator.py — do not edit manually.
Config: {module}
\"\"\"

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import requests
import json
import os
import hmac
import hashlib
import base64
from datetime import datetime, timedelta
import logging
from typing import Optional, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ApiClient:
    def __init__(self, base_url: str = "http://localhost:{port}"):
        self.base_url = base_url
        self.session  = requests.Session()

        # Auth tokens
        self.access_token            = os.getenv("ACCESS_TOKEN", "")
        self.app_token               = ""
        self.access_token_expiration = datetime.now()
        self.app_token_expiration    = datetime.now()

        # App-check credentials (from env or defaults)
        self.api_key     = os.getenv({_repr(api_key_env or "API_KEY")},     "")
        self.app_id      = os.getenv("APP_ID",      "")
        self.sign_secret = os.getenv({_repr(sign_secret_env or "SIGN_SECRET")}, "")

        self.session.headers.update({{
            "Content-Type": "application/json",
            "Accept":       "application/json",
        }})

    # ── Token computation ─────────────────────────────────────────────────────

    def compute_signature(self, app_token: str, timestamp: str) -> str:
        \"\"\"HMAC-SHA256 signature for app-check middleware.\"\"\"
        if not self.sign_secret:
            raise ValueError("SIGN_SECRET not set")
        key       = self.sign_secret.encode()
        message   = (app_token + timestamp).encode()
        signature = hmac.new(key, message, hashlib.sha256).digest()
        return base64.b64encode(signature).decode()

    # ── Auth state ────────────────────────────────────────────────────────────

    @property
    def is_authenticated_user(self) -> bool:
        return bool(self.access_token and datetime.now() < self.access_token_expiration)

    @property
    def is_guest_user(self) -> bool:
        return bool(self.app_token and datetime.now() < self.app_token_expiration
                    and not self.is_authenticated_user)

    @property
    def has_valid_app_token(self) -> bool:
        return bool(self.app_token and datetime.now() < self.app_token_expiration)

    @property
    def auth_state(self) -> str:
        if self.is_authenticated_user: return "authenticated_user"
        if self.is_guest_user:         return "guest_user"
        if self.has_valid_app_token:   return "app_token_only"
        return "no_auth"

    # ── Header builder ────────────────────────────────────────────────────────

    def _prepare_headers(self, endpoint: str) -> Dict[str, str]:
        headers: dict = {{}}
        if self.access_token:
            headers["Authorization"] = f"Bearer {{self.access_token}}"

        if "/auth/guest-token" in endpoint:
            if self.api_key:
                headers["X-API-Key"] = self.api_key
        else:
            if self.app_token:
                if datetime.now() >= self.app_token_expiration:
                    self.get_guest_app_token()
                timestamp = datetime.utcnow().isoformat() + "Z"
                headers.update({{
                    "X-API-Key":          self.api_key,
                    "X-App-Token":        self.app_token,
                    "X-Timestamp":        timestamp,
                    "X-Request-Signature": self.compute_signature(self.app_token, timestamp),
                }})
        return headers

    # ── Guest token ───────────────────────────────────────────────────────────

    def get_guest_app_token(self) -> Dict[str, Any]:
        headers = {{"X-API-Key": self.api_key, "Content-Type": "application/json", "Accept": "application/json"}}
        resp    = self.session.post(
            f"{{self.base_url}}/api/auth/guest-token",
            json={{"app_id": self.app_id}},
            headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json()
            self.app_token             = data.get("app_token", "")
            self.app_token_expiration  = datetime.now() + timedelta(days=1)
            return data
        raise Exception(f"guest-token failed: {{resp.status_code}} {{resp.text}}")

    # ── Request wrapper ───────────────────────────────────────────────────────

    def make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        files: Optional[Dict] = None,
        auth_level: str = "authenticated",
    ) -> requests.Response:
        url     = f"{{self.base_url}}{{endpoint}}"
        headers = self._prepare_headers(endpoint)
        if files:
            headers.pop("Content-Type", None)
        logger.info(f"{{method.upper()}} {{endpoint}} [{{auth_level}}]")
        return self.session.request(method, url, json=data, files=files, headers=headers)


# ─────────────────────────────────────────────────────────────────────────────
# Tkinter UI
# ─────────────────────────────────────────────────────────────────────────────

class ApiTesterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title({_repr(title)})
        self.root.geometry("1200x820")

        self.api = ApiClient()

{ep_block}
        self._build_ui()
        self.root.after(600, self._auto_init_guest_token)

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left  = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        right = ttk.Frame(main)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # ── Credentials ───────────────────────────────────────────────────────
        cred_frame = ttk.LabelFrame(left, text="Credentials", padding=8)
        cred_frame.pack(fill=tk.X, pady=(0, 8))

        for label, attr in [("API Key:", "api_key"), ("App ID:", "app_id"), ("Sign Secret:", "sign_secret")]:
            ttk.Label(cred_frame, text=label).pack(anchor=tk.W)
            show = "*" if "secret" in label.lower() else ""
            entry = ttk.Entry(cred_frame, width=30, show=show)
            entry.insert(0, getattr(self.api, attr))
            entry.pack(fill=tk.X, pady=(0, 4))
            setattr(self, f"_{{attr}}_entry", entry)

        ttk.Label(cred_frame, text="Base URL:").pack(anchor=tk.W)
        self._url_entry = ttk.Entry(cred_frame, width=30)
        self._url_entry.insert(0, self.api.base_url)
        self._url_entry.pack(fill=tk.X, pady=(0, 4))

        btn_row = ttk.Frame(cred_frame)
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="Get Guest Token",  command=self._get_guest_token).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0,2))
        ttk.Button(btn_row, text="Apply Config",     command=self._apply_config   ).pack(side=tk.LEFT, expand=True, fill=tk.X)

        ttk.Label(cred_frame, text="App Token:").pack(anchor=tk.W, pady=(6,0))
        self._app_token_entry = ttk.Entry(cred_frame, width=30, state="readonly")
        self._app_token_entry.pack(fill=tk.X, pady=(0,4))

        ttk.Label(cred_frame, text="Access Token:").pack(anchor=tk.W)
        self._access_token_entry = ttk.Entry(cred_frame, width=30, state="readonly")
        self._access_token_entry.pack(fill=tk.X, pady=(0,4))

        self._status_lbl = ttk.Label(cred_frame, text="Status: Idle", foreground="gray")
        self._status_lbl.pack(anchor=tk.W)

        # ── Endpoint tree ──────────────────────────────────────────────────────
        tree_frame = ttk.LabelFrame(left, text="Endpoints", padding=8)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self._tree = ttk.Treeview(tree_frame)
        self._tree.pack(fill=tk.BOTH, expand=True)

        for cat, eps in self.endpoints.items():
            cat_id = self._tree.insert("", "end", text=cat, values=())
            for name, (m, p, a, d) in eps.items():
                self._tree.insert(cat_id, "end", text=name, values=(m, p, a, json.dumps(d)))

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # ── Request panel ──────────────────────────────────────────────────────
        req_frame = ttk.LabelFrame(right, text="Request", padding=8)
        req_frame.pack(fill=tk.BOTH, expand=True, pady=(0,8))

        row1 = ttk.Frame(req_frame); row1.pack(fill=tk.X, pady=(0,6))
        ttk.Label(row1, text="Method:").pack(side=tk.LEFT)
        self._method_var = tk.StringVar(value="GET")
        ttk.Combobox(row1, textvariable=self._method_var,
                     values=["GET","POST","PUT","PATCH","DELETE"], width=8).pack(side=tk.LEFT, padx=(4,12))
        ttk.Label(row1, text="URL:").pack(side=tk.LEFT)
        self._path_entry = ttk.Entry(row1)
        self._path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4,0))

        row2 = ttk.Frame(req_frame); row2.pack(fill=tk.X, pady=(0,6))
        ttk.Label(row2, text="Auth Level:").pack(side=tk.LEFT)
        self._auth_var = tk.StringVar(value="authenticated")
        ttk.Combobox(row2, textvariable=self._auth_var,
                     values=["guest","app_token","authenticated"], width=14).pack(side=tk.LEFT, padx=(4,0))

        ttk.Label(req_frame, text="Body (JSON):").pack(anchor=tk.W)
        self._body_text = scrolledtext.ScrolledText(req_frame, height=8)
        self._body_text.pack(fill=tk.BOTH, expand=True, pady=(4,8))

        file_row = ttk.Frame(req_frame); file_row.pack(fill=tk.X, pady=(0,8))
        self._file_var = tk.StringVar()
        ttk.Label(file_row, text="File:").pack(side=tk.LEFT)
        ttk.Entry(file_row, textvariable=self._file_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4,4))
        ttk.Button(file_row, text="Browse", command=self._browse_file).pack(side=tk.LEFT)

        ttk.Button(req_frame, text="⚡ Send Request", command=self._send).pack(fill=tk.X)

        # ── Response panel ─────────────────────────────────────────────────────
        resp_frame = ttk.LabelFrame(right, text="Response", padding=8)
        resp_frame.pack(fill=tk.BOTH, expand=True)
        self._resp_text = scrolledtext.ScrolledText(resp_frame)
        self._resp_text.pack(fill=tk.BOTH, expand=True)

    # ── Event handlers ─────────────────────────────────────────────────────────

    def _apply_config(self):
        self.api.api_key     = self._api_key_entry.get()
        self.api.app_id      = self._app_id_entry.get()
        self.api.sign_secret = self._sign_secret_entry.get()
        self.api.base_url    = self._url_entry.get()
        self._update_status()

    def _get_guest_token(self):
        self._apply_config()
        try:
            self._status_lbl.config(text="Status: Getting guest token…", foreground="orange")
            self.root.update()
            self.api.get_guest_app_token()
            self._set_entry(self._app_token_entry, self.api.app_token)
            self._update_status()
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self._update_status()

    def _auto_init_guest_token(self):
        if not self.api.has_valid_app_token and self.api.api_key:
            try:
                self._get_guest_token()
            except Exception:
                pass

    def _update_status(self):
        colors = {{
            "authenticated_user": ("Authenticated User ✓", "green"),
            "guest_user":         ("Guest User",           "blue"),
            "app_token_only":     ("App Token Only",       "orange"),
            "no_auth":            ("Not Authenticated",    "red"),
        }}
        text, color = colors.get(self.api.auth_state, ("Unknown", "gray"))
        self._status_lbl.config(text=f"Status: {{text}}", foreground=color)

    def _on_select(self, _event):
        sel = self._tree.selection()
        if not sel:
            return
        vals = self._tree.item(sel[0])["values"]
        if len(vals) == 4 and vals[0]:
            method, path, auth, body = vals
            self._method_var.set(method)
            self._path_entry.delete(0, tk.END)
            self._path_entry.insert(0, path)
            self._auth_var.set(auth)
            self._body_text.delete("1.0", tk.END)
            try:
                self._body_text.insert("1.0", json.dumps(json.loads(body), indent=2))
            except Exception:
                self._body_text.insert("1.0", body)

    def _browse_file(self):
        path = filedialog.askopenfilename()
        if path:
            self._file_var.set(path)

    def _send(self):
        self._apply_config()
        method    = self._method_var.get()
        path      = self._path_entry.get()
        auth_lvl  = self._auth_var.get()
        raw_body  = self._body_text.get("1.0", tk.END).strip()
        data      = None

        if raw_body:
            try:
                data = json.loads(raw_body)
            except json.JSONDecodeError as e:
                messagebox.showerror("JSON Error", str(e))
                return

        files     = None
        file_path = self._file_var.get()
        try:
            if file_path and os.path.exists(file_path):
                with open(file_path, "rb") as fh:
                    files = {{"file": fh}}
                    resp  = self.api.make_request(method, path, data, files, auth_lvl)
            else:
                resp = self.api.make_request(method, path, data, None, auth_lvl)

            out = {{"status": resp.status_code, "headers": dict(resp.headers)}}
            try:
                out["body"] = resp.json()
            except Exception:
                out["body"] = resp.text

            self._resp_text.delete("1.0", tk.END)
            self._resp_text.insert("1.0", json.dumps(out, indent=2, ensure_ascii=False))

            # Auto-update tokens from response
            body = out.get("body", {{}})
            if isinstance(body, dict):
                for key in ("access_token", "token"):
                    if key in body:
                        self.api.access_token            = body[key]
                        self.api.access_token_expiration = datetime.now() + timedelta(days=1)
                        self._set_entry(self._access_token_entry, self.api.access_token)
                if "app_token" in body:
                    self.api.app_token            = body["app_token"]
                    self.api.app_token_expiration = datetime.now() + timedelta(days=1)
                    self._set_entry(self._app_token_entry, self.api.app_token)
                self._update_status()

        except Exception as e:
            messagebox.showerror("Request Error", str(e))
            self._resp_text.delete("1.0", tk.END)
            self._resp_text.insert("1.0", f"Error: {{e}}")

    @staticmethod
    def _set_entry(entry: ttk.Entry, value: str):
        entry.config(state="normal")
        entry.delete(0, tk.END)
        entry.insert(0, value)
        entry.config(state="readonly")


if __name__ == "__main__":
    root = tk.Tk()
    ApiTesterApp(root)
    root.mainloop()
""")


# ─────────────────────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────────────────────

def run(config_path: str, templates_dir: str, output_dir: str):
    """Called by generator.py"""
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}

    sections = _build_endpoints(cfg)
    source   = _generate_source(cfg, sections)

    os.makedirs(output_dir, exist_ok=True)
    out_file = os.path.join(output_dir, "api_client.py")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(source)

    print(f"  ✅ {out_file}  — {sum(len(v) for v in sections.values())} endpoints across {len(sections)} categories")


def main():
    parser = argparse.ArgumentParser(description="Generate api_client.py from master_config.yaml")
    parser.add_argument("--config",    "-c", default="master_config.yaml")
    parser.add_argument("--templates", "-t", default="./tool/templates")
    parser.add_argument("--output",    "-o", default=".")
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"❌ Config not found: {args.config}")
        sys.exit(1)

    print("=" * 60)
    print("  API CLIENT GENERATOR")
    print("=" * 60)
    run(args.config, args.templates, args.output)
    print("=" * 60 + "\n  DONE\n" + "=" * 60)


if __name__ == "__main__":
    main()
