#!/usr/bin/env python3
"""
generator.py — Unified Master Orchestrator
==========================================
Runs ALL sub-generators in the correct order for a complete Go-Fiber backend:

    1. validate_config   — gate on config errors
    2. app_generate      — config/, cmd/server/main.go, infra/, permissions.yaml
    3. auth_generate     — JWT, email/password, social auth, web auth, DTOs
    4. middleware_generator — middleware.go
    5. rbac_generate     — RBAC service, controller
    6. storage_generate  — storage provider, file uploader
    7. imap_generate     — IMAP email service, controller
    8. notification_genrator — FCM sender, notification domain/repo/controller
    9. chat_websocket_genrator — Chat domain, WebSocket hub/handlers
   10. repo_model_config_generate — GORM models, repos, DTOs, web handlers
   11. routes            — complete_routes.yaml  (route map)
   12. format_generated_code — goimports / gofmt on all *.go output

Usage:
    python generator.py --config master_config.yaml
    python generator.py --config master_config.yaml --templates ./tool/templates --output ./generated
    python generator.py --config master_config.yaml --skip-validate
    python generator.py --config master_config.yaml --strict
    python generator.py --config master_config.yaml --only routes
"""

import argparse
import os
import sys
import time
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

STEP_SEP = "=" * 62


def _header(title: str):
    print(f"\n{STEP_SEP}")
    print(f"  {title}")
    print(STEP_SEP)


def _ok(label: str, elapsed: float):
    print(f"  ✅ {label}  ({elapsed:.2f}s)")


def _skip(label: str, reason: str = ""):
    print(f"  ⬜ {label} — skipped{(' (' + reason + ')') if reason else ''}")


# ─────────────────────────────────────────────────────────────────────────────
# Step runner
# ─────────────────────────────────────────────────────────────────────────────

def _run_step(label: str, fn, *args, **kwargs):
    """Run fn(*args, **kwargs) and report timing. Propagates exceptions."""
    t0 = time.perf_counter()
    fn(*args, **kwargs)
    _ok(label, time.perf_counter() - t0)


# ─────────────────────────────────────────────────────────────────────────────
# Individual step wrappers (thin — just import the module and delegate)
# ─────────────────────────────────────────────────────────────────────────────

def step_validate(config_path: str, strict: bool):
    from generators.validate_config import validate_or_exit
    validate_or_exit(config_path, strict=strict)


def step_app(config_path: str, templates_dir: str, output_dir: str):
    from generators import app_generate
    app_generate.run(config_path, templates_dir, output_dir)


def step_auth(config_path: str, templates_dir: str, output_dir: str):
    from generators import auth_generate
    auth_generate.run(config_path, templates_dir, output_dir)


def step_middleware(config_path: str, templates_dir: str, output_dir: str):
    from generators.middleware_generator import run as mw_run
    mw_run(config_path, templates_dir, output_dir)


def step_rbac(config_path: str, templates_dir: str, output_dir: str):
    from generators import rbac_generate
    rbac_generate.run(config_path, templates_dir, output_dir)


def step_storage(config_path: str, templates_dir: str, output_dir: str):
    from generators import storage_generate
    storage_generate.run(config_path, templates_dir, output_dir)


def step_imap(config_path: str, templates_dir: str, output_dir: str):
    from generators import imap_generate
    imap_generate.run(config_path, templates_dir, output_dir)


def step_notifications(config_path: str, templates_dir: str, output_dir: str):
    from generators import notification_generator as notif
    notif.run(config_path, templates_dir, output_dir)


def step_chat_websocket(config_path: str, templates_dir: str, output_dir: str):
    from generators import chat_websocket_generator as chat
    chat.run(config_path, templates_dir, output_dir)


def step_models(config_path: str, templates_dir: str, output_dir: str, generate_graphql: bool = False, generate_grpc: bool = False, generate_dtos: bool = False, generate_responses: bool = False, generate_repositories: bool = False, generate_controllers: bool = False, generate_handlers: bool = False, generate_models: bool = False):
    """Run the class-based ModelGenerator for all models in config."""
    import yaml
    from generators.repo_model_config_generate import ModelGenerator

    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}

    module_path = cfg.get("project", {}).get("module", "github.com/user/project")

    gen = ModelGenerator(
        config_path=config_path,
        templates_dir=templates_dir,
        output_dir=output_dir,
    )
    gen.generate_all(module_path=module_path, generate_graphql=generate_graphql, generate_grpc=generate_grpc, generate_dtos=generate_dtos, generate_responses=generate_responses, generate_repositories=generate_repositories, generate_controllers=generate_controllers, generate_handlers=generate_handlers, generate_models=generate_models)


def step_routes(config_path: str, output_dir: str):
    """Run the route extractor — writes complete_routes.yaml next to config."""
    from generators.routes import RouteGenerator

    out_file = str(Path(output_dir) / "complete_routes.yaml")
    gen = RouteGenerator(config_path=config_path)
    gen.generate(output_file=out_file)


def step_format(output_dir: str):
    try:
        from generators.format_generated_code import codeFormat
        codeFormat(output_dir)
    except ImportError:
        print("  ⚠️  format_generated_code not found — skipping goimports/gofmt step")
    except Exception as e:
        print(f"  ⚠️  Formatter error (non-fatal): {e}")


def step_api_client(config_path: str, templates_dir: str, output_dir: str):
    """Generate a Tkinter api_client.py test tool from the config."""
    from generators.api_client_generator import run as ac_run
    ac_run(config_path, templates_dir, output_dir)

def step_graphql(config_path: str, templates_dir: str, output_dir: str):
    from generators import graphql_generator
    graphql_generator.run(config_path, templates_dir, output_dir)

def step_grpc(config_path: str, templates_dir: str, output_dir: str):
    from generators import grpc_generator
    grpc_generator.run(config_path, templates_dir, output_dir)

# ─────────────────────────────────────────────────────────────────────────────
# ALL_STEPS — ordered list of (key, label, step_fn)
# Used for --only filtering.
# ─────────────────────────────────────────────────────────────────────────────

ALL_STEP_KEYS = [
    "validate",
    "app",
    "auth",
    "middleware",
    "rbac",
    "storage",
    "imap",
    "notifications",
    "chat",
    "models",
    "models_handler",
    "models_dtos",
    "models_repo",
    "models_response",
    "models_controller",
    "models_graphql",
    "graphql",      # ← Add this
    "grpc",         # ← Add this
    "routes",
    "api_client",
    "format",
]


# ─────────────────────────────────────────────────────────────────────────────
# Master run
# ─────────────────────────────────────────────────────────────────────────────

def run_all(
    config_path: str,
    templates_dir: str,
    output_dir: str,
    skip_validate: bool = False,
    strict: bool = False,
    only: list = None,
):
    """
    Run the full generation pipeline.

    Args:
        config_path:   Path to master_config.yaml
        templates_dir: Root of Jinja2 template tree  (./tool/templates)
        output_dir:    Root output directory          (./generated)
        skip_validate: If True, skip pre-flight config validation
        strict:        Treat validation warnings as errors
        only:          If non-empty, run only these step keys
    """

    def _should(key: str) -> bool:
        return (not only) or (key in only)

    total_start = time.perf_counter()

    _header("GO-FIBER BACKEND GENERATOR")
    print(f"  Config    : {config_path}")
    print(f"  Templates : {templates_dir}")
    print(f"  Output    : {output_dir}")
    if only:
        print(f"  Only steps: {', '.join(only)}")
    print()

    # ── 1. Validate ──────────────────────────────────────────────────────────
    if _should("validate"):
        if skip_validate:
            _skip("Validate config", "--skip-validate")
        else:
            _header("Step 1 / 12 — Validate Config")
            _run_step("Config validation", step_validate, config_path, strict)
    
    # ── 2. App scaffold ───────────────────────────────────────────────────────
    if _should("app"):
        _header("Step 2 / 12 — App Scaffold  (config, main, infra)")
        _run_step("App scaffold", step_app, config_path, templates_dir, output_dir)

    # ── 3. Auth ───────────────────────────────────────────────────────────────
    if _should("auth"):
        _header("Step 3 / 12 — Authentication")
        _run_step("Auth generator", step_auth, config_path, templates_dir, output_dir)

    # ── 4. Middleware ─────────────────────────────────────────────────────────
    if _should("middleware"):
        _header("Step 4 / 12 — Middleware")
        _run_step("Middleware generator", step_middleware, config_path, templates_dir, output_dir)

    # ── 5. RBAC ───────────────────────────────────────────────────────────────
    if _should("rbac"):
        _header("Step 5 / 12 — RBAC")
        _run_step("RBAC generator", step_rbac, config_path, templates_dir, output_dir)

    # ── 6. Storage ────────────────────────────────────────────────────────────
    if _should("storage"):
        _header("Step 6 / 12 — Storage")
        _run_step("Storage generator", step_storage, config_path, templates_dir, output_dir)

    # ── 7. IMAP / Email ───────────────────────────────────────────────────────
    if _should("imap"):
        _header("Step 7 / 12 — IMAP / Email")
        _run_step("IMAP generator", step_imap, config_path, templates_dir, output_dir)

    # ── 8. Notifications / FCM ────────────────────────────────────────────────
    if _should("notifications"):
        _header("Step 8 / 12 — Notifications / FCM")
        _run_step("Notification generator", step_notifications, config_path, templates_dir, output_dir)

    # ── 9. Chat / WebSocket ───────────────────────────────────────────────────
    if _should("chat"):
        _header("Step 9 / 12 — Chat / WebSocket")
        _run_step("Chat/WebSocket generator", step_chat_websocket, config_path, templates_dir, output_dir)

    # ── 10. Models ────────────────────────────────────────────────────────────
    if _should("models"):
        _header("Step 10 / 12 — Models, Repositories, DTOs")
        _run_step("Model generator", step_models, config_path, templates_dir, output_dir, generate_models=True)
    if _should("models_response"):
        _header("Step 10 / 12 — Models, Repositories, DTOs")
        _run_step("Model generator", step_models, config_path, templates_dir, output_dir, generate_responses=True)
    if _should("models_repo"):
        _header("Step 10 / 12 — Models, Repositories, DTOs")
        _run_step("Model generator", step_models, config_path, templates_dir, output_dir, generate_repositories=True)
    if _should("models_controller"):
        _header("Step 10 / 12 — Models, Repositories, DTOs")
        _run_step("Model generator", step_models, config_path, templates_dir, output_dir, generate_controllers=True)
    if _should("models_handler"):
        _header("Step 10 / 12 — Models, Repositories, DTOs")
        _run_step("Model generator", step_models, config_path, templates_dir, output_dir, generate_handlers=True)
    if _should("models_dtos"):
        _header("Step 10 / 12 — Models, Repositories, DTOs")
        _run_step("Model generator", step_models, config_path, templates_dir, output_dir, generate_dtos=True)
    if _should("models_graphql"):
        _header("Step 10 / 12 — Models, Repositories, DTOs")
        _run_step("Model generator", step_models, config_path, templates_dir, output_dir, generate_graphql=True)
    # ── 11. Routes ────────────────────────────────────────────────────────────
    if _should("routes"):
        _header("Step 11 / 13 — Route Map  (complete_routes.yaml)")
        _run_step("Route extractor", step_routes, config_path, output_dir)

    # ── 12. API Client ────────────────────────────────────────────────────────
    if _should("api_client"):
        _header("Step 12 / 13 — API Client  (api_client.py)")
        _run_step("API client generator", step_api_client, config_path, templates_dir, output_dir)

    # ── 13. Format ────────────────────────────────────────────────────────────
    if _should("format"):
        _header("Step 13 / 13 — Format Go Code")
        step_format(output_dir)
        _ok("Code formatter", 0.0)
    if _should("graphql"):
        _header("Step X / Y — GraphQL Schema & Resolvers")
        _run_step("GraphQL generator", step_graphql, config_path, templates_dir, output_dir)

    if _should("grpc"):
        _header("Step X / Y — gRPC Protocol & Services")
        _run_step("gRPC generator", step_grpc, config_path, templates_dir, output_dir)
    
    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = time.perf_counter() - total_start
    print(f"\n{STEP_SEP}")
    print(f"  ✅ ALL DONE  —  {elapsed:.2f}s")
    print(f"  Output: {output_dir}")
    print(STEP_SEP + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Unified Go-Fiber backend generator — runs ALL sub-generators",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available step keys for --only / --skip:
  {", ".join(ALL_STEP_KEYS)}

Examples:
  python generator.py --config master_config.yaml
  python generator.py --config master_config.yaml --strict
  python generator.py --config master_config.yaml --only routes
  python generator.py --config master_config.yaml --skip validate format
  python generator.py --config master_config.yaml --output ./my_project
""",
    )

    parser.add_argument(
        "--config", "-c",
        default="master_config.yaml",
        help="Path to master_config.yaml  (default: master_config.yaml)",
    )
    base_dir = os.path.dirname(os.path.abspath(__file__))
    parser.add_argument(
        "--templates", "-t",
        default=os.path.join(base_dir, "tool", "templates"),
        help="Root of Jinja2 template tree  (default: [package_dir]/tool/templates)",
    )
    parser.add_argument(
        "--output", "-o",
        default="./generated",
        help="Root output directory  (default: ./generated)",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip pre-flight config validation",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat config validation warnings as errors",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="STEP",
        help=f"Run only these steps  (choices: {', '.join(ALL_STEP_KEYS)})",
    )
    parser.add_argument(
        "--skip",
        nargs="+",
        metavar="STEP",
        help="Skip specific steps  (choices: see --only)",
    )

    args = parser.parse_args()

    # Resolve config path
    if not os.path.exists(args.config):
        print(f"❌ Config not found: {args.config}")
        sys.exit(1)

    # Determine step set
    only_steps = None
    if args.only:
        invalid = [s for s in args.only if s not in ALL_STEP_KEYS]
        if invalid:
            print(f"❌ Unknown step(s): {', '.join(invalid)}")
            print(f"   Valid steps: {', '.join(ALL_STEP_KEYS)}")
            sys.exit(1)
        only_steps = args.only
    elif args.skip:
        invalid = [s for s in args.skip if s not in ALL_STEP_KEYS]
        if invalid:
            print(f"❌ Unknown step(s) in --skip: {', '.join(invalid)}")
            sys.exit(1)
        only_steps = [s for s in ALL_STEP_KEYS if s not in args.skip]

    run_all(
        config_path=args.config,
        templates_dir=args.templates,
        output_dir=args.output,
        skip_validate=args.skip_validate,
        strict=args.strict,
        only=only_steps,
    )


if __name__ == "__main__":
    main()
