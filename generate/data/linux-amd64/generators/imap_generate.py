#!/usr/bin/env python3
"""
IMAP Generator — Incoming email fetching service and controller.
Reads from: config.imap  (top-level)

Usage (standalone):
    python imap_generate.py --config config.yaml --templates ./tool/templates --output ./generated

Usage (imported):
    from generators.imap_generate import run
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
    config.setdefault('rbac', {"enabled":False})

    
    imap = config.setdefault('imap', {})
    imap.setdefault('enabled',              False)
    imap.setdefault('host_env',             'IMAP_HOST')
    imap.setdefault('port_env',             'IMAP_PORT')
    imap.setdefault('user_env',             'IMAP_EMAIL')
    imap.setdefault('password_env',         'IMAP_PASSWORD')
    imap.setdefault('use_ssl',              True)
    imap.setdefault('mailbox',              'INBOX')
    imap.setdefault('fetch_interval',       '5 * time.Minute')
    imap.setdefault('mark_as_read',         True)
    imap.setdefault('max_emails_per_fetch', 50)
    imap.setdefault('fetch_sent',           False)
    imap.setdefault('controller',           {'enabled': False})
    imap.setdefault('web_handler',          {'enabled': False})


    email = config.setdefault('email', {})
    email.setdefault('enabled',              False)
     # ── Email / SMTP (top-level) ─────────────────────────────────────────────
    # Also enable automatically if email_verification is on
    email_verification_on = (
        config.get('authentication', {})
              .get('email_password', {})
              .get('email_verification', {})
              .get('enabled', False)
    )
    if email_verification_on:
        email['enabled'] = True
    email.setdefault('smtp_host_env',             'SMTP_HOST')
    email.setdefault('smtp_port_env',             'SMTP_PORT')
    email.setdefault('smtp_user_env',             'SMTP_EMAIL')
    email.setdefault('smtp_password_env',         'SMTP_EMAIL_PASSWORD')

    return config


# ─────────────────────────────────────────────────────────────────────────────
# Template decision table
# ─────────────────────────────────────────────────────────────────────────────

def get_templates(config: dict, t: str, o: str) -> list[tuple[str, str]]:
    imap = config['imap']
    email = config['email']
    result =[]
    if email.get('enabled'):
        result.append((f'{t}/pkg/email/sendMail.go.j2', f'{o}/pkg/email/sendMail.go'))

    if not imap.get('enabled'):
        print("  ℹ️  IMAP disabled — skipping")
        return result
    else:

        result.append((f'{t}/internal/domain/email.go.j2',  f'{o}/internal/domain/email.go'),)
        result.append((f'{t}/pkg/email/service.go.j2',        f'{o}/pkg/email/service.go.go'),)
            
    if imap.get('controller', {}).get('enabled') or imap.get('web_handler', {}).get('enabled') :
       
        result.append((f'{t}/internal/api/handlers/email.go.j2',f'{o}/internal/api/handlers/email.go',))
        
        result.append((f'{t}/internal/repository/email_repository.go.j2',f'{o}/internal/repository/email_repository.go', ))
        
        result.append(( f'{t}/pkg/response/email_response.go.j2',f'{o}/pkg/response/email_response.go', ))
        
        
        if imap["controller"].get('SendEmail', {}).get('enabled',False) or imap["web_handler"].get('SendEmail', {}).get('enabled',False) :
            if config.get('email', {}).get('enabled',False):
                result.append((f'{t}/pkg/dto/email_dto.go.j2',f'{o}/pkg/dto/email_dto.go',))

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────────────────────

def run(config_path: str, templates_dir: str, output_dir: str):
    config    = build_context(config_path)
    templates = get_templates(config, templates_dir, output_dir)
    render_all(config, templates)


def main():
    parser = argparse.ArgumentParser(description='Generate Go IMAP files from YAML config')
    parser.add_argument('--config',    required=True)
    parser.add_argument('--templates', default='./tool/templates')
    parser.add_argument('--output',    default='./generated')
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"❌ Config not found: {args.config}"); sys.exit(1)

    print("=" * 60)
    print("  IMAP GENERATOR")
    print("=" * 60)
    run(args.config, args.templates, args.output)
    print("=" * 60 + "\n  DONE\n" + "=" * 60)


if __name__ == "__main__":
    main()
