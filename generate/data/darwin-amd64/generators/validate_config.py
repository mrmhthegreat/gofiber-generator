#!/usr/bin/env python3
"""
Config Validator & Feature Lister
Validates master_config.yaml before generation and shows exactly what will be generated.

Usage:
    python validate_config.py --config master_config.yaml
    python validate_config.py --config master_config.yaml --list-features
    python validate_config.py --config master_config.yaml --strict   # treat warnings as errors
"""

import sys
import argparse
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Issue collector
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Issue:
    level: str      # "error" | "warning" | "info"
    section: str
    message: str

    def __str__(self):
        icons = {"error": "❌", "warning": "⚠️ ", "info": "ℹ️ "}
        return f"  {icons[self.level]} [{self.section}] {self.message}"


class Result:
    def __init__(self):
        self.issues: list[Issue] = []

    def error(self, section: str, msg: str):
        self.issues.append(Issue("error", section, msg))

    def warn(self, section: str, msg: str):
        self.issues.append(Issue("warning", section, msg))

    def info(self, section: str, msg: str):
        self.issues.append(Issue("info", section, msg))

    @property
    def errors(self):   return [i for i in self.issues if i.level == "error"]
    @property
    def warnings(self): return [i for i in self.issues if i.level == "warning"]
    @property
    def infos(self):    return [i for i in self.issues if i.level == "info"]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get(cfg: dict, *keys, default=None):
    """Safe nested get: _get(cfg, 'a', 'b', 'c')"""
    cur = cfg
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
        if cur is None:
            return default
    return cur


def _enabled(cfg: dict, *keys) -> bool:
    return bool(_get(cfg, *keys, default=False))


def _require_field(r: Result, cfg: dict, section: str, *key_path, label: str = None):
    """Add an error if a required field is missing or empty."""
    val = _get(cfg, *key_path)
    name = label or ".".join(str(k) for k in key_path)
    if not val:
        r.error(section, f"Required field missing: {name}")


def _warn_default(r: Result, cfg: dict, section: str, *key_path, placeholder: str, label: str = None):
    """Warn if a field still has the default placeholder value."""
    val = _get(cfg, *key_path, default="")
    name = label or ".".join(str(k) for k in key_path)
    if str(val) == placeholder:
        r.warn(section, f"{name} is still the default value '{placeholder}' — change before deploying")


# ─────────────────────────────────────────────────────────────────────────────
# Section validators
# ─────────────────────────────────────────────────────────────────────────────

def validate_project(cfg: dict, r: Result):
    _require_field(r, cfg, "project", "project", "module")
    mod = _get(cfg, "project", "module", default="")
    if mod in ("github.com/user/project", "github.com/username/my_api", ""):
        r.warn("project", "project.module looks like a placeholder — set your real Go module path")


def validate_database(cfg: dict, r: Result):
    db = cfg.get("database", {})
    if not db:
        r.error("database", "database section is missing")
        return
    driver = db.get("driver", "")
    if driver not in ("postgres", "mysql", "sqlite"):
        r.error("database", f"database.driver '{driver}' is not valid — use postgres, mysql, or sqlite")
    _require_field(r, cfg, "database", "database", "url_env")


def validate_redis(cfg: dict, r: Result):
    if not _enabled(cfg, "redis", "enabled"):
        return
    _require_field(r, cfg, "redis", "redis", "host_env")
    # session usually needs redis
    if _enabled(cfg, "session", "enabled") and not _enabled(cfg, "redis", "enabled"):
        r.warn("session", "session.enabled is true but redis.enabled is false — sessions will use in-memory store (not production-safe)")


def validate_session(cfg: dict, r: Result):
    if not _enabled(cfg, "session", "enabled"):
        return
    for env_key in ("secret_key_env", "cookies_secret_env", "cookies_secret_key_env"):
        val = _get(cfg, "session", env_key, default="")
        if val and "CHANGE_THIS" in str(val):
            r.warn("session", f"session.{env_key} still contains 'CHANGE_THIS' — set a real secret")


def validate_auth(cfg: dict, r: Result):
    auth = cfg.get("authentication", {})
    if not auth:
        r.info("auth", "No authentication section — skipping auth generation")
        return

    # JWT
    if _enabled(auth, "jwt", "enabled"):
        _require_field(r, cfg, "auth/jwt", "authentication", "jwt", "secret_key_env")
        algo = _get(auth, "jwt", "algorithm", default="HS256")
        if algo not in ("HS256", "HS384", "HS512", "RS256", "RS384", "RS512"):
            r.error("auth/jwt", f"jwt.algorithm '{algo}' is not valid")
        claims = _get(auth, "jwt", "claims", default=[])
        if not claims:
            r.warn("auth/jwt", "jwt.claims is empty — tokens will have no claims")

    # login methods — exactly one should be enabled
    login_methods = _get(auth, "identifier", "login_methods", default=[])
    enabled_methods = [m for m in login_methods if m.get("enabled")]
    if len(enabled_methods) == 0:
        r.warn("auth/identifier", "No login method is enabled — users won't be able to log in")
    elif len(enabled_methods) > 1:
        r.error("auth/identifier", f"{len(enabled_methods)} login methods are enabled simultaneously — only one should be enabled at a time")

    # email_password
    if _enabled(auth, "email_password", "enabled"):
        # email_verification needs email
        if _enabled(auth, "email_password", "email_verification", "enabled"):
            if not _enabled(cfg, "email", "enabled"):
                r.error("auth/email_verification",
                    "email_password.email_verification is enabled but email.enabled is false — "
                    "verification emails cannot be sent")

        # forgot_password needs email
        if _enabled(auth, "email_password", "forgot_password", "enabled"):
            if not _enabled(cfg, "email", "enabled"):
                r.error("auth/forgot_password",
                    "email_password.forgot_password is enabled but email.enabled is false — "
                    "reset emails cannot be sent")

    # social auth
    for provider in ("google", "facebook"):
        if _enabled(auth, "social_auth", provider, "enabled"):
            for env in ("client_id_env", "client_secret_env", "redirect_url_env"):
                _require_field(r, cfg, f"auth/social/{provider}",
                               "authentication", "social_auth", provider, env)

    # web_auth needs session
    if _enabled(auth, "web_auth", "enabled"):
        if not _enabled(cfg, "session", "enabled") and not _enabled(auth, "session", "enabled"):
            r.error("auth/web_auth",
                "web_auth is enabled but session is disabled — web auth requires sessions")

    # app_check_tokens
    for tok in _get(auth, "app_check_tokens", default=[]):
        name = tok.get("name", "unnamed")
        if not tok.get("secret_key_env"):
            r.error(f"auth/app_check_tokens/{name}", f"app_check_token '{name}' is missing secret_key_env")


def validate_email(cfg: dict, r: Result):
    if not _enabled(cfg, "email", "enabled"):
        return
    for env in ("smtp_host_env", "smtp_port_env", "smtp_user_env", "smtp_password_env"):
        _require_field(r, cfg, "email", "email", env)


def validate_imap(cfg: dict, r: Result):
    if not _enabled(cfg, "imap", "enabled"):
        return
    for env in ("host_env", "port_env", "user_env", "password_env"):
        _require_field(r, cfg, "imap", "imap", env)


def validate_fcm(cfg: dict, r: Result):
    if not _enabled(cfg, "fcm", "enabled"):
        return
    _require_field(r, cfg, "fcm", "fcm", "credentials_path_env")
    _require_field(r, cfg, "fcm", "fcm", "project_id_env")
    # FCM save_to_database needs a database
    if _get(cfg, "fcm", "save_to_database"):
        if not cfg.get("database"):
            r.warn("fcm", "fcm.save_to_database is true but no database section found")


def validate_storage(cfg: dict, r: Result):
    if not _enabled(cfg, "storage", "enabled"):
        return
    provider = _get(cfg, "storage", "provider_env", default="")
    # Check that at least one provider block is configured
    has_provider = any(
        cfg.get("storage", {}).get(p)
        for p in ("supabase", "s3", "local")
    )
    if not has_provider:
        r.warn("storage", "storage.enabled is true but no provider block (supabase/s3/local) is configured")

    # file_upload fields need storage
    register_fields = _get(cfg, "authentication", "identifier", "register_fields", default=[])
    has_upload_fields = any(f.get("file_upload") for f in register_fields)
    if has_upload_fields and not _enabled(cfg, "storage", "enabled"):
        r.warn("storage",
            "register_fields has file_upload: true fields but storage.enabled is false — "
            "uploaded files will have nowhere to go")


def validate_rbac(cfg: dict, r: Result):
    # check both possible locations
    rbac = cfg.get("rbac") or _get(cfg, "authentication", "rbac") or {}
    if not rbac.get("enabled"):
        return

    # middleware.rbac should also be enabled
    if not _enabled(cfg, "middleware", "rbac", "enabled"):
        r.warn("rbac",
            "rbac.enabled is true but middleware.rbac.enabled is false — "
            "RBAC service will be generated but the middleware won't enforce it")

    if not rbac.get("roles"):
        r.warn("rbac", "rbac.roles is empty — define at least one role")


def validate_websocket(cfg: dict, r: Result):
    if not _enabled(cfg, "websocket", "enabled"):
        return

    handler_type = _get(cfg, "websocket", "handler_type", default="unified")
    if handler_type not in ("unified", "dedicated"):
        r.error("websocket", f"websocket.handler_type '{handler_type}' is not valid — use 'unified' or 'dedicated'")

    # websocket auth
    ws_auth_method = _get(cfg, "websocket", "authentication", "method", default="")
    if ws_auth_method == "jwt":
        _require_field(r, cfg, "websocket", "websocket", "authentication", "jwt", "secret_key_env")

    # chat needs websocket
    if _enabled(cfg, "chat", "enabled"):
        if not _enabled(cfg, "websocket", "enabled"):
            r.error("chat",
                "chat.enabled is true but websocket.enabled is false — chat requires WebSocket")


def validate_middleware(cfg: dict, r: Result):
    mw = cfg.get("middleware", {})
    if not mw:
        return

    # CSRF + CORS together can cause issues
    if _enabled(mw, "csrf", "enabled") and _enabled(mw, "cors", "enabled"):
        cors_origins = _get(mw, "cors", "allow_origins", default="")
        if cors_origins == "*" and _get(mw, "cors", "allow_credentials"):
            r.warn("middleware/cors",
                "cors.allow_origins is '*' with allow_credentials: true — "
                "browsers will reject this. Set specific origins instead of '*'")

    # check each middleware definition
    definitions = mw.get("definitions", [])
    names_seen = set()
    for mwdef in definitions:
        name = mwdef.get("name", "")
        mw_type = mwdef.get("type", "")

        if not name:
            r.error("middleware/definitions", "A middleware definition is missing 'name'")
            continue
        if name in names_seen:
            r.error("middleware/definitions", f"Duplicate middleware name: '{name}'")
        names_seen.add(name)

        if not mw_type:
            r.error(f"middleware/{name}", f"Middleware '{name}' is missing 'type'")
            continue

        if mw_type == "jwt":
            if not mwdef.get("secret_key_env"):
                r.error(f"middleware/{name}", f"JWT middleware '{name}' is missing secret_key_env")
            algo = mwdef.get("algorithm", "HS256")
            if algo not in ("HS256", "HS384", "HS512", "RS256", "RS384", "RS512"):
                r.error(f"middleware/{name}", f"JWT middleware '{name}' has invalid algorithm '{algo}'")

        elif mw_type == "api_key":
            if not mwdef.get("secret_key_env"):
                r.error(f"middleware/{name}", f"API key middleware '{name}' is missing secret_key_env")
            if not mwdef.get("header"):
                r.error(f"middleware/{name}", f"API key middleware '{name}' is missing header")

        elif mw_type == "rate_limit":
            if not mwdef.get("max_requests"):
                r.error(f"middleware/{name}", f"Rate limit middleware '{name}' is missing max_requests")
            if not mwdef.get("window"):
                r.error(f"middleware/{name}", f"Rate limit middleware '{name}' is missing window")

        elif mw_type == "combined":
            if not mwdef.get("components"):
                r.error(f"middleware/{name}", f"Combined middleware '{name}' has no components")


def validate_swagger(cfg: dict, r: Result):
    if not _enabled(cfg, "swagger", "enabled"):
        return
    sw = cfg.get("swagger", {})
    if sw.get("host", "").startswith("localhost"):
        r.info("swagger", "swagger.host is localhost — remember to update for production")


def validate_models(cfg: dict, r: Result):
    models = cfg.get("models", [])
    if not models:
        r.warn("models", "No models defined — only auth/feature files will be generated")
        return

    names_seen = set()
    for model in models:
        name = model.get("name", "")
        if not name:
            r.error("models", "A model is missing 'name'")
            continue
        if name in names_seen:
            r.error("models", f"Duplicate model name: '{name}'")
        names_seen.add(name)

        if not model.get("fields"):
            r.warn(f"models/{name}", f"Model '{name}' has no fields defined")

        # ownership checks reference a field — make sure it exists
        ctrl = model.get("controller", {})
        for op_name, op in ctrl.items():
            if not isinstance(op, dict):
                continue
            ownership = op.get("ownership", {})
            if ownership.get("enabled") and ownership.get("verify") == "field":
                field_name = ownership.get("field", "")
                model_fields = [f.get("name", "") for f in model.get("fields", [])]
                if field_name and field_name not in model_fields:
                    r.warn(f"models/{name}/{op_name}",
                        f"Ownership field '{field_name}' not found in model fields")


# ─────────────────────────────────────────────────────────────────────────────
# Feature list builder
# ─────────────────────────────────────────────────────────────────────────────

def build_feature_list(cfg: dict) -> list[tuple[str, str, list[str]]]:
    """
    Returns list of (status, label, [detail lines])
    status: "on" | "off" | "partial"
    """
    auth  = cfg.get("authentication", {})
    items = []

    def on(label, details=None):
        items.append(("on",      label, details or []))
    def off(label, details=None):
        items.append(("off",     label, details or []))
    def partial(label, details=None):
        items.append(("partial", label, details or []))

    # App scaffold — always
    on("App scaffold", ["config.go", "database.go", "main.go", "routes.go", "contexthelpers.go",
                        "Dockerfile", "docker-compose.yml", "Makefile", ".gitignore"])

    # Redis
    if _enabled(cfg, "redis", "enabled"):
        on("Redis", ["config/redis.go"])
    else:
        off("Redis")

    # Swagger
    if _enabled(cfg, "swagger", "enabled"):
        on("Swagger", [f"title: {_get(cfg, 'swagger', 'title', default='My API')}"])
    else:
        off("Swagger")

    # Models
    models = cfg.get("models", [])
    if models:
        on(f"Models ({len(models)})", [m["name"] for m in models if m.get("name")])
    else:
        off("Models (none defined)")

    # Auth
    if auth:
        details = []
        if _enabled(auth, "jwt", "enabled"):
            algo = _get(auth, "jwt", "algorithm", default="HS256")
            details.append(f"JWT ({algo})")
        if _enabled(auth, "email_password", "enabled"):
            parts = ["email/password"]
            if _enabled(auth, "email_password", "email_verification", "enabled"):
                parts.append("+ email verification")
            if _enabled(auth, "email_password", "forgot_password", "enabled"):
                parts.append("+ forgot password")
            details.append(" ".join(parts))
        for p in ("google", "facebook"):
            if _enabled(auth, "social_auth", p, "enabled"):
                details.append(f"{p.capitalize()} OAuth")
        if _enabled(auth, "refresh_token", "enabled"):
            details.append("refresh tokens")
        if _enabled(auth, "web_auth", "enabled"):
            details.append("web session auth handler")
        tokens = _get(auth, "app_check_tokens", default=[])
        if tokens:
            details.append(f"{len(tokens)} app check token(s)")
        on("Authentication", details) if details else partial("Authentication", ["enabled but no sub-features active"])
    else:
        off("Authentication")

    # RBAC
    rbac = cfg.get("rbac") or _get(cfg, "authentication", "rbac") or {}
    if rbac.get("enabled"):
        roles = [r.get("name", "") for r in rbac.get("roles", [])]
        on("RBAC", [f"roles: {', '.join(roles)}"] if roles else [])
    else:
        off("RBAC")

    # Email
    if _enabled(cfg, "email", "enabled"):
        on("Email (SMTP)", [f"provider: {_get(cfg, 'email', 'provider', default='smtp')}"])
    else:
        off("Email (SMTP)")

    # IMAP
    if _enabled(cfg, "imap", "enabled"):
        details = []
        if _enabled(cfg, "imap", "controller", "enabled"):
            details.append("API controller")
        if _enabled(cfg, "imap", "web_handler", "enabled"):
            details.append("web handler")
        on("IMAP (incoming email)", details)
    else:
        off("IMAP (incoming email)")

    # FCM
    if _enabled(cfg, "fcm", "enabled"):
        details = []
        if _get(cfg, "fcm", "save_to_database"):
            details.append("saves tokens to database")
        if _enabled(cfg, "fcm", "controller", "enabled"):
            details.append("API controller")
        on("FCM (push notifications)", details)
    else:
        off("FCM (push notifications)")

    # Storage
    if _enabled(cfg, "storage", "enabled"):
        provider = next(
            (p for p in ("supabase", "s3", "local") if cfg.get("storage", {}).get(p)),
            "unknown"
        )
        on("Storage", [f"provider: {provider}"])
    else:
        off("Storage")

    # Middleware
    mw = cfg.get("middleware", {})
    if mw:
        active = []
        for key in ("cors", "csrf", "compression", "logging", "rate_limit"):
            if _enabled(mw, key, "enabled"):
                active.append(key)
        defs = mw.get("definitions", [])
        if defs:
            active.append(f"{len(defs)} named middleware definition(s)")
        on("Middleware", active) if active else off("Middleware")
    else:
        off("Middleware")

    # WebSocket
    if _enabled(cfg, "websocket", "enabled"):
        handler_type = _get(cfg, "websocket", "handler_type", default="unified")
        on("WebSocket", [f"handler_type: {handler_type}"])
    else:
        off("WebSocket")

    # Chat
    if _enabled(cfg, "chat", "enabled"):
        on("Chat")
    else:
        off("Chat")

    # Notifications
    if _enabled(cfg, "notifications", "enabled"):
        on("Notifications")
    else:
        off("Notifications")

    # i18n
    if _enabled(cfg, "i18n", "enabled"):
        langs = _get(cfg, "i18n", "languages", default=[])
        on("i18n", [f"languages: {', '.join(langs)}"])
    else:
        off("i18n")

    # Template engine
    if _enabled(cfg, "template_engine", "enabled"):
        on("Template engine", [f"dir: {_get(cfg, 'template_engine', 'template_dir', default='./templates')}"])
    else:
        off("Template engine")

    # Static files
    if _enabled(cfg, "static_files", "enabled"):
        on("Static files", [f"route: {_get(cfg, 'static_files', 'route', default='/static')}"])
    else:
        off("Static files")

    # Cron jobs
    if _get(cfg, "features", "cron_jobs"):
        on("Cron jobs")
    else:
        off("Cron jobs")

    return items


# ─────────────────────────────────────────────────────────────────────────────
# Output
# ─────────────────────────────────────────────────────────────────────────────

def print_feature_list(cfg: dict):
    items = build_feature_list(cfg)
    print(f"\n{'─'*52}")
    print(f"  FEATURE PLAN")
    print(f"  Config: {cfg.get('_config_path', '')}")
    print(f"  Project: {_get(cfg, 'project', 'module', default='(not set)')}")
    print(f"{'─'*52}")

    icons = {"on": "✅", "off": "⬜", "partial": "🟡"}
    for status, label, details in items:
        print(f"  {icons[status]} {label}")
        for d in details:
            print(f"       {d}")
    print()


def print_validation_results(r: Result, strict: bool = False):
    print(f"\n{'─'*52}")
    print(f"  VALIDATION RESULTS")
    print(f"{'─'*52}")

    if not r.issues:
        print("  ✅ All checks passed — config looks good!\n")
        return

    if r.errors:
        print(f"\n  ❌ ERRORS ({len(r.errors)})  — must fix before generating:\n")
        for issue in r.errors:
            print(issue)

    if r.warnings:
        print(f"\n  ⚠️  WARNINGS ({len(r.warnings)})  — review before generating:\n")
        for issue in r.warnings:
            print(issue)

    if r.infos:
        print(f"\n  ℹ️  INFO ({len(r.infos)}):\n")
        for issue in r.infos:
            print(issue)

    print()
    if r.errors:
        print(f"  ❌ {len(r.errors)} error(s) found — fix these before running the generator\n")
    elif r.warnings and strict:
        print(f"  ⚠️  {len(r.warnings)} warning(s) found — --strict mode treats these as errors\n")
    elif r.warnings:
        print(f"  ⚠️  {len(r.warnings)} warning(s) found — generation may proceed but review these\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main validator
# ─────────────────────────────────────────────────────────────────────────────

def validate(config_path: str, strict: bool = False) -> tuple[dict, Result]:
    """Load config and run all validators. Returns (config, result)."""
    try:
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(f"❌ Config file not found: {config_path}")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"❌ YAML parse error in {config_path}:\n   {e}")
        sys.exit(1)

    cfg['_config_path'] = config_path

    r = Result()
    validate_project(cfg, r)
    validate_database(cfg, r)
    validate_redis(cfg, r)
    validate_session(cfg, r)
    validate_auth(cfg, r)
    validate_email(cfg, r)
    validate_imap(cfg, r)
    validate_fcm(cfg, r)
    validate_storage(cfg, r)
    validate_rbac(cfg, r)
    validate_websocket(cfg, r)
    validate_middleware(cfg, r)
    validate_swagger(cfg, r)
    validate_models(cfg, r)

    return cfg, r


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Validate master_config.yaml and preview what will be generated"
    )
    parser.add_argument("--config", "-c", default="master_config.yaml",
                        help="Path to config YAML (default: master_config.yaml)")
    parser.add_argument("--list-features", "-l", action="store_true",
                        help="Show what will and won't be generated")
    parser.add_argument("--strict", action="store_true",
                        help="Treat warnings as errors")
    args = parser.parse_args()

    cfg, r = validate(args.config, strict=args.strict)

    if args.list_features:
        print_feature_list(cfg)

    print_validation_results(r, strict=args.strict)

    # Exit code
    if r.errors:
        sys.exit(1)
    if args.strict and r.warnings:
        sys.exit(1)
    sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────
# Called by master_generator before generation
# ─────────────────────────────────────────────────────────────────────────────

def validate_or_exit(config_path: str, strict: bool = False):
    """Import this in master_generator to gate generation on a clean config."""
    cfg, r = validate(config_path, strict=strict)
    print_feature_list(cfg)
    print_validation_results(r, strict=strict)

    if r.errors:
        print("❌ Generation blocked — fix errors above first\n")
        sys.exit(1)
    if strict and r.warnings:
        print("❌ Generation blocked — --strict mode requires no warnings\n")
        sys.exit(1)

    return cfg


if __name__ == "__main__":
    main()
