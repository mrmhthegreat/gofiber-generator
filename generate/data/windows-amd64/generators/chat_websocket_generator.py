#!/usr/bin/env python3
"""
Chat / WebSocket Generator — Chat models, repositories, controllers, web handlers,
and the WebSocket hub + event handlers.

Reads from:
    config.chat       — Chat models, modes, controller, web_handler
    config.websocket  — WebSocket hub, events, authentication, rooms

Usage (standalone):
    python chat_websocket_genrator.py --config config.yaml --templates ./tool/templates --output ./generated

Usage (imported):
    from generators.chat_websocket_genrator import run
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

    chat = config.setdefault('chat', {})
    chat.setdefault('enabled',      False)
    chat.setdefault('repository',   {})
    chat.setdefault('models',       {})
    chat.setdefault('websocket',    {'enabled': False})
    chat.setdefault('web_handler',  {'enabled': False})
    chat.setdefault('controller',   {'enabled': False})

    websocket = config.setdefault('websocket', {})
    websocket.setdefault('enabled',        False)
    websocket.setdefault('authentication', {})
    websocket.setdefault('connection',     '')
    websocket.setdefault('presence',       {})
    websocket.setdefault('hub',            {})
    websocket.setdefault('events',         [])
    websocket.setdefault('rooms',          {'enabled': False})

    _validate_config(config)

    return config


def _validate_config(config: Dict[str, Any]) -> None:
    """
    Validate configuration for common issues and dependencies.
    Prints warnings/errors; calls sys.exit(1) on critical errors.
    """
    websocket = config['websocket']
    chat      = config['chat']
    websocket_enabled = websocket.get('enabled', False)
    handler_type      = websocket.get('handler_type', 'unified')
    has_errors = False

    if chat.get('websocket', {}).get('enabled', False) and not websocket_enabled:
        print('❌ ERROR: chat.websocket.enabled is true but websocket.enabled is false')
        print('   Fix: Set websocket.enabled to true or disable chat.websocket')
        has_errors = True

    if websocket.get('presence', {}).get('enabled', False) and not websocket_enabled:
        print('⚠️  WARNING: websocket.presence.enabled is true but websocket.enabled is false')
        print('   Presence tracking will not work')

    if chat.get('enabled', False) and not config.get('chat', {}).get('models'):
        print('⚠️  WARNING: chat.enabled is true but no models are defined')

    if handler_type == 'dedicated' and websocket_enabled:
        dedicated = websocket.get('dedicated', {})
        if not dedicated:
            print("⚠️  WARNING: handler_type is 'dedicated' but websocket.dedicated paths are not configured")
            print('   Default paths will be used (/ws/chat, /ws/support, /ws/user, /ws/events)')
        else:
            paths = []
            for handler in ['chat', 'support', 'user', 'events']:
                cfg = dedicated.get(handler, {})
                if cfg.get('enabled', True):
                    path = cfg.get('path', f'/ws/{handler}')
                    if path in paths:
                        print(f"❌ ERROR: Duplicate WebSocket path '{path}' in dedicated.{handler}")
                        has_errors = True
                    paths.append(path)

        if not chat.get('modes', {}).get('support', False):
            if dedicated.get('support', {}).get('enabled', True):
                print("⚠️  WARNING: dedicated.support is enabled but chat.modes.support is false")
                print('   SupportHub will not be generated')

    for event in websocket.get('events', []):
        if event.get('enabled', True):
            if event.get('handler_type') == 'custom' and not event.get('custom_handler'):
                print(f"⚠️  WARNING: Event '{event.get('name')}' has handler_type 'custom' but no custom_handler defined")

            rate_limit = event.get('rate_limit', {})
            if rate_limit.get('enabled', False) and not rate_limit.get('max_per_minute'):
                print(f"⚠️  WARNING: Event '{event.get('name')}' has rate_limit enabled but max_per_minute not set")

    if has_errors:
        print('\n❌ Chat/WebSocket generator: fix errors above before generating')
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Template decision table
# ─────────────────────────────────────────────────────────────────────────────

def get_templates(config: dict, t: str, o: str) -> list:
    websocket    = config['websocket']
    chat         = config['chat']
    result       = []
    handler_type = websocket.get('handler_type', 'unified')

    if chat.get('enabled'):
        result.append((f'{t}/internal/domain/chat.go.j2',          f'{o}/internal/domain/chat.go'))
        result.append((f'{t}/internal/repository/chat.go.j2',       f'{o}/internal/repository/chat.go'))
        result.append((f'{t}/pkg/response/chat_response.go.j2',     f'{o}/pkg/response/chat_response.go'))
        result.append((f'{t}/pkg/dto/chat_dto.go.j2',               f'{o}/pkg/dto/chat_dto.go'))

        if chat.get('controller', {}).get('enabled'):
            result.append((f'{t}/internal/api/handlers/chat.go.j2', f'{o}/internal/api/handlers/chat.go'))

        if chat.get('web_handler', {}).get('enabled'):
            result.append((
                f'{t}/internal/web/dashboard/web_chat_handler.go.j2',
                f'{o}/internal/web/dashboard/web_chat_handler.go',
            ))
    else:
        print('  ℹ️  Chat disabled — skipping')

    if not websocket.get('enabled'):
        print('  ℹ️  WebSocket disabled — skipping')
        return result

    result.append((f'{t}/internal/websocket/base.go.j2', f'{o}/internal/websocket/base.go'))

    if handler_type == 'unified':
        result.append((f'{t}/internal/websocket/hub.go.j2',      f'{o}/internal/websocket/hub.go'))
        result.append((f'{t}/internal/websocket/handlers.go.j2', f'{o}/internal/websocket/handlers.go'))
        return result

    # dedicated handler_type
    if chat.get('enabled') and websocket.get('enabled'):
        result.append((f'{t}/internal/websocket/chat/hub.go.j2',      f'{o}/internal/websocket/chat/hub.go'))
        result.append((f'{t}/internal/websocket/chat/handlers.go.j2', f'{o}/internal/websocket/chat/handlers.go'))

    if chat.get('modes', {}).get('support', False) and websocket.get('enabled'):
        result.append((f'{t}/internal/websocket/support/hub.go.j2',      f'{o}/internal/websocket/support/hub.go'))
        result.append((f'{t}/internal/websocket/support/handlers.go.j2', f'{o}/internal/websocket/support/handlers.go'))

    if len(websocket.get('events', [])) > 0:
        result.append((f'{t}/internal/websocket/events/hub.go.j2',      f'{o}/internal/websocket/events/hub.go'))
        result.append((f'{t}/internal/websocket/events/handlers.go.j2', f'{o}/internal/websocket/events/handlers.go'))

    result.append((f'{t}/internal/websocket/user/handlers.go.j2', f'{o}/internal/websocket/user/handlers.go'))

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────────────────────

def run(config_path: str, templates_dir: str, output_dir: str):
    config    = build_context(config_path)
    templates = get_templates(config, templates_dir, output_dir)
    render_all(config, templates)


def main():
    parser = argparse.ArgumentParser(description='Generate Go Chat/WebSocket files from YAML config')
    parser.add_argument('--config',    required=True,             help='Path to YAML config file')
    parser.add_argument('--templates', default='./tool/templates', help='Templates directory')
    parser.add_argument('--output',    default='./generated',      help='Output directory')
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f'❌ Config not found: {args.config}')
        sys.exit(1)

    print('=' * 60)
    print('  CHAT / WEBSOCKET GENERATOR')
    print('=' * 60)
    run(args.config, args.templates, args.output)
    print('=' * 60 + '\n  DONE\n' + '=' * 60)

    from generators.format_generated_code import codeFormat
    codeFormat(args.output)


if __name__ == '__main__':
    main()
