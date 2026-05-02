#!/usr/bin/env python3
"""
Notifications / FCM Generator — Push notification domain, repository,
controllers, and FCM push sender.

Reads from:
    config.notifications  — Notification model, repository, controller, triggers, WebSocket
    config.fcm            — Firebase Cloud Messaging sender, controller, web_handler

Usage (standalone):
    python notification_genrator.py --config config.yaml --templates ./tool/templates --output ./generated

Usage (imported):
    from generators.notification_genrator import run
    run(config_path, templates_dir, output_dir)
"""

import os
import sys
import argparse
import yaml
from typing import Dict, Any
from generators.help_utils import render_all


# ─────────────────────────────────────────────────────────────────────────────
# Context builder
# ─────────────────────────────────────────────────────────────────────────────

def build_context(config_path: str) -> dict:
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    config.setdefault('project', {}).setdefault('module', 'github.com/user/project')
    config.setdefault('websocket', {'enabled': True})
    config.setdefault('rbac', {'enabled': False})
    notifications = config.setdefault('notifications', {})
    notifications.setdefault('enabled',    False)
    notifications.setdefault('controller', {'enabled': False})
    notifications.setdefault('push',       {'enabled': False})
    notifications.setdefault('triggers',   [])
    notifications.setdefault('model',      {}).setdefault('fields', [])
    notifications.setdefault('repository', {})
    notifications.setdefault('websocket',  {'enabled': False})

    fcm = config.setdefault('fcm', {})
    fcm.setdefault('enabled',               False)
    fcm.setdefault('credentials_path_env',  'FCM_CREDENTIALS_PATH')
    fcm.setdefault('project_id_env',        'FCM_PROJECT_ID')
    fcm.setdefault('admin_topic_env',       'admin_default_topic')
    fcm.setdefault('controller',            {'enabled': False})
    fcm.setdefault('web_handler',           {'enabled': False})

    _validate_config(config)

    return config


def _validate_config(config: Dict[str, Any]) -> None:
    """
    Validate configuration for common issues and dependencies.
    Prints warnings/errors; calls sys.exit(1) on critical errors.
    """
    notifications     = config['notifications']
    websocket_enabled = config.get('websocket', {}).get('enabled', False)
    fcm_enabled       = config.get('fcm', {}).get('enabled', False)
    has_errors        = False

    if notifications.get('websocket', {}).get('enabled', False) and not websocket_enabled:
        print('❌ ERROR: notifications.websocket.enabled is true but websocket.enabled is false')
        print('   Fix: Set websocket.enabled to true or disable notifications.websocket')
        has_errors = True

    if notifications.get('push', {}).get('enabled', False) and not fcm_enabled:
        print('❌ ERROR: notifications.push.enabled is true but fcm.enabled is false')
        print('   Fix: Set fcm.enabled to true or disable notifications.push')
        has_errors = True

    chat_enabled = config.get('chat', {}).get('enabled', False)
    for trigger in notifications.get('triggers', []):
        if trigger.get('event') in ('message_sent', 'message_received') and not chat_enabled:
            print(f"⚠️  WARNING: Notification trigger '{trigger.get('event')}' references chat but chat.enabled is false")
            break

    if has_errors:
        print('\n❌ Notification generator: fix errors above before generating')
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Template decision table
# ─────────────────────────────────────────────────────────────────────────────

def get_templates(config: dict, t: str, o: str) -> list:
    notifications = config['notifications']
    fcm           = config['fcm']
    result        = []

    if fcm.get('enabled'):
        result.append((f'{t}/pkg/fcm/sender.go.j2', f'{o}/pkg/fcm/sender.go'))

        if fcm['controller'].get('enabled', False) or fcm['web_handler'].get('enabled', False):
            result.append((f'{t}/internal/api/handlers/fcm.go.j2', f'{o}/internal/api/handlers/fcm.go'))
            result.append((f'{t}/pkg/dto/fcm_dto.go.j2',           f'{o}/pkg/dto/fcm_dto.go'))

    if not notifications.get('enabled'):
        print('  ℹ️  Notifications disabled — skipping')
        return result

    result.append((f'{t}/internal/domain/notification.go.j2',     f'{o}/internal/domain/notification.go'))
    result.append((f'{t}/internal/repository/notification.go.j2', f'{o}/internal/repository/notification.go'))

    if notifications.get('controller', {}).get('enabled'):
        result.append((f'{t}/internal/api/handlers/notification.go.j2',     f'{o}/internal/api/handlers/notification.go'))
        result.append((f'{t}/pkg/response/notification_response.go.j2',     f'{o}/pkg/response/notification_response.go'))
        result.append((f'{t}/pkg/dto/notification_dto.go.j2',               f'{o}/pkg/dto/notification_dto.go'))
        result.append((f'{t}/pkg/notification/notifier.go.j2',              f'{o}/pkg/notification/notifier.go'))

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────────────────────

def run(config_path: str, templates_dir: str, output_dir: str):
    config    = build_context(config_path)
    templates = get_templates(config, templates_dir, output_dir)
    render_all(config, templates)


def main():
    parser = argparse.ArgumentParser(description='Generate Go Notifications/FCM files from YAML config')
    parser.add_argument('--config',    required=True,              help='Path to YAML config file')
    parser.add_argument('--templates', default='./tool/templates',  help='Templates directory')
    parser.add_argument('--output',    default='./generated',       help='Output directory')
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f'❌ Config not found: {args.config}')
        sys.exit(1)

    print('=' * 60)
    print('  NOTIFICATIONS / FCM GENERATOR')
    print('=' * 60)
    run(args.config, args.templates, args.output)
    print('=' * 60 + '\n  DONE\n' + '=' * 60)
    from generators.format_generated_code import codeFormat
    codeFormat(args.output)

if __name__ == '__main__':
    main()
