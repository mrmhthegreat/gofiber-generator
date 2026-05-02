#!/usr/bin/env python3
"""
Storage Generator — File upload storage provider (Supabase, S3, local).
These are top-level features, not nested under authentication.

Reads from:
    config.storage    — File upload storage provider
    config.authentication.identifier.register_fields  — to detect file upload fields

Usage (standalone):
    python helpers_generate.py --config config.yaml --templates ./tool/templates --output ./generated

Usage (imported):
    from generators.helpers_generate import run
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

    config.setdefault('project', {}).setdefault('module', 'github.com/user/project')

    # ── Storage (top-level) ──────────────────────────────────────────────────
    storage = config.setdefault('storage', {})
    storage.setdefault('enabled', False)

    # ── File upload detection (from register_fields) ─────────────────────────
    register_fields = (
        config.get('authentication', {})
              .get('identifier', {})
              .get('register_fields', [])
    )

    config['_has_file_uploads']   = any(f.get('file_upload') for f in register_fields)
    config['_file_upload_fields'] = [f for f in register_fields if f.get('file_upload')]

    # Dependency validation
    if config['_has_file_uploads'] and not storage.get('enabled'):
        print('⚠️  WARNING: register_fields contain file_upload: true fields '
              'but storage.enabled is false — uploaded files will have nowhere to go')

    return config


# ─────────────────────────────────────────────────────────────────────────────
# Template decision table
# ─────────────────────────────────────────────────────────────────────────────

def get_templates(config: dict, t: str, o: str) -> list[tuple[str, str]]:
    result = []

    # saveUploadFile — storage must be enabled OR a register field has file_upload
    if config['storage'].get('enabled') or config['_has_file_uploads']:
        result.append((
            f'{t}/pkg/storage/uploader.go.j2',
            f'{o}/pkg/storage/uploader.go',
        ))
        if config['storage'].get('enabled'):
            result.append((
                f'{t}/pkg/storage/provider.go.j2',
                f'{o}/pkg/storage/provider.go',
            ))

    # FCM
    
    if not result:
        print("  ℹ️  No helpers to generate (FCM, email, storage all disabled)")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────────────────────

def run(config_path: str, templates_dir: str, output_dir: str):
    config    = build_context(config_path)
    templates = get_templates(config, templates_dir, output_dir)
    render_all(config, templates)


def main():
    parser = argparse.ArgumentParser(description='Generate Go helper files (FCM/email/storage) from YAML config')
    parser.add_argument('--config',    required=True)
    parser.add_argument('--templates', default='./tool/templates')
    parser.add_argument('--output',    default='./generated')
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"❌ Config not found: {args.config}"); sys.exit(1)

    print("=" * 60)
    print("  HELPERS GENERATOR  (Storage)")
    print("=" * 60)
    run(args.config, args.templates, args.output)
    print("=" * 60 + "\n  DONE\n" + "=" * 60)


if __name__ == "__main__":
    main()
