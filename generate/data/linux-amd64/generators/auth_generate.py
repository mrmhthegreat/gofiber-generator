#!/usr/bin/env python3
"""
Auth Generator — JWT, email/password, social auth, web auth, app check tokens.
Reads from: config.authentication

Usage (standalone):
    python auth_generate.py --config config.yaml --templates ./tool/templates --output ./generated

Usage (imported):
    from generators.auth_generate import run
    run(config_path, templates_dir, output_dir)
"""

import os
import sys
import argparse
import yaml
from jinja2 import Environment, FileSystemLoader
from generators.help_utils import render_all

def build_context(config_path: str) -> dict:
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    proj = config.setdefault('project', {})
    proj.setdefault('module',          'github.com/user/project')
    proj.setdefault('user_model_name', 'User')
    config.setdefault('session',{'enabled': False})
    auth = config.setdefault('authentication', {})
    auth.setdefault('session',          {'enabled': True})
    auth.setdefault('jwt',              {'enabled': False})
    auth.setdefault('refresh_token',    {'enabled': False})
    auth.setdefault('logout',           {'enabled': False})
    auth.setdefault('app_check_tokens', [])
    auth.setdefault('social_auth', {
        'google':   {'enabled': False},
        'facebook': {'enabled': False},
    })
    
    ep = auth.setdefault('email_password', {'enabled': False, })
    ep.setdefault('forgot_password',    {'enabled': False, })
    ep.setdefault('change_password',    {'enabled': False, })
    ep.setdefault('password_validation', {'min_length': 8})
    auth.setdefault('email_verification', {'enabled': False, })

    ident = auth.setdefault('identifier', {'login_methods': [], 'register_fields': []})

    # computed helpers
    register_fields = ident.get('register_fields', [])
    login_methods   = ident.get('login_methods',   [])
   
    # Helper function: Get all file upload fields
    config['_has_file_uploads']     = any(f.get('file_upload') for f in register_fields)
    config['_file_upload_fields']   = [f for f in register_fields if f.get('file_upload')]
    config['_enabled_login_method'] = next((m for m in login_methods if m.get('enabled')), None)
    rbac = config.setdefault('rbac', {'enabled': False, "service_name": "RBACService", "model_field" : "Role"})
    
    email = config.setdefault('email', {})
    email.setdefault('enabled',              False)

    webauth= auth.setdefault('web_auth', {})
    webauth.setdefault('enabled',False)
    # Ensure endpoint path defaults exist so templates can use them safely
    web_auth_endpoints = webauth.setdefault('endpoints', {})
    web_auth_endpoints.setdefault('login',          {'enabled': True,  'path': '/login'})
    web_auth_endpoints.setdefault('signup',         {'enabled': True,  'path': '/signup'})
    web_auth_endpoints.setdefault('logout',         {'enabled': True,  'path': '/logout'})
    web_auth_endpoints.setdefault('forgot_password',{'enabled': True,  'path': '/account/forget-password/'})
    web_auth_endpoints.setdefault('reset_password', {'enabled': True,  'path': '/account/reset-password/'})
    web_auth_endpoints.setdefault('resend_otp',     {'enabled': True,  'path': '/account/resend-reset-otp/'})
    web_auth_endpoints.setdefault('verify_email',       {'enabled': True,  'path': '/auth/user/verify-account/'})
    web_auth_endpoints.setdefault('resend_verify_email', {'enabled': True,  'path': '/auth/user/resend-verify-email/'})

    # ── Robust Field Detection ──────────────────────────────────────────────
    uses_email = False
    uses_username = False
    
    # 1. Check Login Methods
    for lm in login_methods:
        if lm.get('enabled', False):
            fname = lm.get('field', '')
            if fname == 'email':
                uses_email = True
            elif fname == 'username':
                uses_username = True
            elif fname in ['email_or_username', 'username_or_email']:
                uses_email = True
                uses_username = True
    
    # 2. Check Registration Fields
    for rf in register_fields:
        fname = rf.get('field', '')
        if fname == 'email':
            uses_email = True
        elif fname == 'username':
            uses_username = True

    # 3. Check Verification
    if auth.get('email_verification', {}).get('enabled'):
        uses_email = True

    config['_uses_email'] = uses_email
    config['_uses_username'] = uses_username
    config['_uses_fcm'] = config.get('fcm', {}).get('enabled', False)

    # 4. Detect Name Field
    name_field = None
    # User-defined pool or default common name fields
    pool = ident.get('name_pool', ["fullname", "name", "display_name", "first_name"])
    # Check if any field in the pool is actually in register_fields
    for pf in pool:
        if any(rf.get('field') == pf for rf in register_fields):
            name_field = pf
            break
    
    config['_name_field'] = name_field

    #  # ── Email / SMTP (top-level) ─────────────────────────────────────────────
    # # Also enable automatically if email_verification is on
    email_verification_on =  auth['email_verification']['enabled']
    if email_verification_on and not email['enabled']:
        print('❌ ERROR: authentication.email_verification.enabled is true but email.enabled is false')
        print('Please enable email.enabled in config.yaml')
        sys.exit(1)

    if  not config['session']['enabled'] and auth['session']['enabled']:
       print('❌ ERROR: authentication.session.enabled is true but session.enabled is false')
       print('Please enable session.enabled in your_config.yaml')
       sys.exit(1)
   
       
            
    return config

# ─────────────────────────────────────────────────────────────────────────────
# Template decision table
# ─────────────────────────────────────────────────────────────────────────────

def get_templates(config: dict, t: str, o: str) -> list[tuple[str, str]]:
    auth   = config.get('authentication', {})
    if not auth.get('enabled', False):
        return []

    social = auth.get('social_auth', {})

    result = [
        (f'{t}/pkg/dto/auth_dto.go.j2',                        f'{o}/pkg/dto/auth_dto.go'),
        (f'{t}/internal/api/handlers/auth.go.j2',               f'{o}/internal/api/handlers/auth.go'),
        (f'{t}/pkg/jwt/jwt.go.j2',                              f'{o}/pkg/jwt/jwt.go'),
        (f'{t}/pkg/auth/helpers.go.j2',                              f'{o}/pkg/auth/helpers.go'),
        (f'{t}/internal/repository/auth_repository.go.j2',                  f'{o}/internal/repository/auth_repository.go'),
    ]

    if social.get('google', {}).get('enabled') or social.get('facebook', {}).get('enabled'):
        result.append((
            f'{t}/internal/api/handlers/social_auth.go.j2',
            f'{o}/internal/api/handlers/social_auth.go',
        ))

    if auth.get('app_check_tokens'):
        result.append((
            f'{t}/internal/api/handlers/app_check_token.go.j2',
            f'{o}/internal/api/handlers/app_check_token.go',
        ))

    if auth.get('web_auth', {}).get('enabled'):
        result.append((
            f'{t}/internal/web/auth/web_auth_handler.go.j2',
            f'{o}/internal/web/auth/web_auth_handler.go',
        ))

    # ── HTML Templates & JS ──────────────────────────────────────────────────
    ep = auth.get('email_password', {})
    web_auth = auth.get('web_auth', {})

    if web_auth.get('enabled') or ep.get('enabled'):
        # Auth HTML pages
        result.append((
            f'{t}/public/templates/auth/signin.html.j2',
            f'{o}/html/templates/auth/signin.html',
        ))
        result.append((
            f'{t}/public/templates/auth/auth.js.j2',
            f'{o}/html/static/auth/js/auth.js',
        ))

        signup_ep = web_auth.get('endpoints', {}).get('signup', {})
        signup_enabled = signup_ep.get('enabled', True) if web_auth.get('enabled') else ep.get('enabled', False)
        if signup_enabled:
            result.append((
                f'{t}/public/templates/auth/signup.html.j2',
                f'{o}/html/templates/auth/signup.html',
            ))
            result.append((
                f'{t}/public/templates/auth/signup.js.j2',
                f'{o}/html/static/auth/js/signup.js',
            ))

        if ep.get('forgot_password', {}).get('enabled'):
            result.append((
                f'{t}/public/templates/auth/forgot_password.html.j2',
                f'{o}/html/templates/auth/reset-password.html',
            ))
            result.append((
                f'{t}/public/templates/auth/forgot_password.js.j2',
                f'{o}/html/static/auth/js/forgot_password.js',
            ))
            result.append((
                f'{t}/public/templates/auth/reset_password.html.j2',
                f'{o}/html/templates/auth/reset_password_confirm.html',
            ))
            # reset_password uses the same forgot_password JS for OTP handling
            result.append((
                f'{t}/public/templates/auth/reset_password.js.j2',
                f'{o}/html/static/auth/js/reset_password.js',
            ))

        if auth.get('email_verification', {}).get('enabled'):
            result.append((
                f'{t}/public/templates/auth/verify_email.html.j2',
                f'{o}/html/templates/auth/verify_email.html',
            ))
            result.append((
                f'{t}/public/templates/auth/verify_email.js.j2',
                f'{o}/html/static/auth/js/verify_email.js',
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
    parser = argparse.ArgumentParser(description='Generate Go auth files from YAML config')
    parser.add_argument('--config',    required=True)
    parser.add_argument('--templates', default='./tool/templates')
    parser.add_argument('--output',    default='./generated')
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"❌ Config not found: {args.config}"); sys.exit(1)

    print("=" * 60)
    print("  AUTH GENERATOR")
    print("=" * 60)
    run(args.config, args.templates, args.output)
    print("=" * 60 + "\n  DONE\n" + "=" * 60)
    from generators.format_generated_code import codeFormat
    codeFormat(args.output)

if __name__ == "__main__":
    main()