#!/usr/bin/env python3
"""
RBAC Generator — Role-Based Access Control.
Reads from: config.rbac  (top-level, canonical location)
            config.authentication.rbac  (legacy / auth-only configs — fallback)

Usage (standalone):
    python rbac_generate.py --config config.yaml --templates ./tool/templates --output ./generated

Usage (imported):
    from generators.rbac_generate import run
    run(config_path, templates_dir, output_dir)
"""

import os
import sys
import argparse
import yaml
from generators.help_utils import render_all


# ─────────────────────────────────────────────────────────────────────────────
# Context builder
# ─────────────────────────────────────────────────────────────────────────────

def build_context(config_path: str) -> dict:
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    proj = config.setdefault('project', {})
    proj.setdefault('module',          'github.com/user/project')
    proj.setdefault('user_model_name', 'User')

    # Normalise: top-level rbac is canonical.
    # If only authentication.rbac exists (auth-only yaml), promote it to top-level.
    if not config.get('rbac'):
        config['rbac'] = config.get('authentication', {}).get('rbac', {})

    rbac = config.setdefault('rbac', {})
    rbac.setdefault('enabled',        False)
    rbac.setdefault('service_name',   'RBACService')
    rbac.setdefault('default_role',   'user')
    rbac.setdefault('all_privileges', 'super_admin')
    rbac.setdefault('model_field',    'Role')
    rbac.setdefault('roles',          [])
    rbac.setdefault('controller',     {'enabled': False})
    rbac.setdefault('web_handler',    {'enabled': False})

    # Dependency validation
    if rbac.get('enabled'):
        mw_rbac = config.get('middleware', {}).get('rbac', {})
        if not mw_rbac.get('enabled'):
            print('⚠️  WARNING: rbac.enabled is true but middleware.rbac.enabled is false '
                  '— RBAC service will be generated but the middleware will not enforce it')

    return config


# ─────────────────────────────────────────────────────────────────────────────
# Template decision table
# ─────────────────────────────────────────────────────────────────────────────

def get_templates(config: dict, t: str, o: str) -> list[tuple[str, str]]:
    if not config['rbac'].get('enabled'):
        print("  ℹ️  RBAC disabled — skipping")
        return []

    result = [
        (f'{t}/internal/domain/rbac_model.go.j2',           f'{o}/internal/domain/rbac_model.go'),
        (f'{t}/pkg/rbac/helpers.go.j2',                f'{o}/pkg/rbac/helpers.go'),
        (f'{t}/pkg/rbac/service.go.j2',                f'{o}/pkg/rbac/service.go'),
    ]

    if config['rbac'].get('controller', {}).get('enabled'):
        result.append((
            f'{t}/internal/api/handlers/rbac.go.j2',
            f'{o}/internal/api/handlers/rbac.go',
        ))

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────────────────────

def run(config_path: str, templates_dir: str, output_dir: str):
    config    = build_context(config_path)
    templates = get_templates(config, templates_dir, output_dir)
    render_all(config, templates)


def main():
    parser = argparse.ArgumentParser(description='Generate Go RBAC files from YAML config')
    parser.add_argument('--config',    required=True)
    parser.add_argument('--templates', default='./tool/templates')
    parser.add_argument('--output',    default='./generated')
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"❌ Config not found: {args.config}"); sys.exit(1)

    print("=" * 60)
    print("  RBAC GENERATOR")
    print("=" * 60)
    run(args.config, args.templates, args.output)
    print("=" * 60 + "\n  DONE\n" + "=" * 60)


if __name__ == "__main__":
    main()
