#!/usr/bin/env python3
"""
App Generator — Top-level application scaffolding.
Generates everything that needs the full config picture and belongs to no
single feature domain:

    config/         config.go, database.go, redis.go, env config.yaml
    internal/       contexthelpers, routes
    cmd/server/     main.go
    infra/          Dockerfile, docker-compose.yml, Makefile, README.md,
                    .gitignore, .dockerignore
    web/templates/  copy of HTML templates (if template_engine enabled)

Reads from: the whole config (project, server, database, redis, swagger,
            session, i18n, static_files, template_engine, features, …)

Usage (standalone):
    python app_generate.py --config master_config.yaml --templates ./tool/templates --output ./generated

Usage (imported):
    from generators.app_generate import run
    run(config_path, templates_dir, output_dir)
"""

import os
import sys
import shutil
import argparse
import yaml
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from generators.help_utils import render_all


# ─────────────────────────────────────────────────────────────────────────────
# Context builder — normalise every top-level key templates may touch
# ─────────────────────────────────────────────────────────────────────────────

def build_context(config_path: str) -> dict:
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # project
    proj = config.setdefault('project', {})
    proj.setdefault('module',      'github.com/user/project')
    proj.setdefault('cmd_name',    config.get('project', {}).get('structure', {}).get('cmd_name', 'server'))

    # server
    srv = config.setdefault('server', {})
    srv.setdefault('port',                 '3000')
    srv.setdefault('default_port',         '3000')
    srv.setdefault('body_limit',           '10 * 1024 * 1024')
    srv.setdefault('body_limit_description', '10MB')
    srv.setdefault('read_timeout',         '10 * time.Second')
    srv.setdefault('write_timeout',        '10 * time.Second')
    srv.setdefault('pass_locals_to_views', False)

    # database
    db = config.setdefault('database', {})
    db.setdefault('driver',           'postgres')
    db.setdefault('url_env',          'DATABASE_URL')
    db.setdefault('host_env',         'DATABASE_HOST')
    db.setdefault('port_env',         'DATABASE_PORT')
    db.setdefault('name_env',         'DATABASE_NAME')
    db.setdefault('user_env',         'DATABASE_USER')
    db.setdefault('password_env',     'DATABASE_PASSWORD')
    db.setdefault('ssl_mode_env',     'DATABASE_SSL_MODE')
    db.setdefault('max_open_conns',   25)
    db.setdefault('max_idle_conns',   5)
    db.setdefault('conn_max_lifetime','5 * time.Minute')
    db.setdefault('auto_migrate',     True)
    db.setdefault('run_migrations',   False)

    # redis
    redis = config.setdefault('redis', {})
    redis.setdefault('enabled',          False)
    redis.setdefault('host_env',         'REDIS_ADDR')
    redis.setdefault('password_env',     'REDIS_PASSWORD')
    redis.setdefault('db_env',           'REDIS_DB')
    redis.setdefault('min_idle_conns',   5)
    redis.setdefault('max_retries',      3)
    redis.setdefault('retry_delay',      '2 * time.Second')
    redis.setdefault('pool_size',        20)
    redis.setdefault('session_addr_env', 'REDIS_ADDR')

    # session
    sess = config.setdefault('session', {})
    sess.setdefault('enabled',           False)
    sess.setdefault('secret_key_env',    'SESSION_SECRET')
    sess.setdefault('cookies_secret_env','COOKIES_SECRET')
    sess.setdefault('cookie_http_only',  True)
    sess.setdefault('cookie_secure',     False)
    sess.setdefault('expiration',        '24 * time.Hour')
    sess.setdefault('store_context_key', 'session')

    # swagger
    sw = config.setdefault('swagger', {})
    sw.setdefault('enabled',     False)
    sw.setdefault('title',       'My API')
    sw.setdefault('description', 'Go Fiber API')
    sw.setdefault('version',     '1.0.0')
    sw.setdefault('host',        'localhost:3000')
    sw.setdefault('base_path',   '/api')
    sw.setdefault('schemes',     ['http', 'https'])

    # i18n
    i18n = config.setdefault('i18n', {})
    i18n.setdefault('enabled',          False)
    i18n.setdefault('root_path',        './locales')
    i18n.setdefault('translations_dir', './translations')
    i18n.setdefault('languages',        ['en'])



    hlp = config.setdefault('helpers', {})
    hlp.setdefault('math_helpers',          True)
    hlp.setdefault('string_helpers',        True)
    hlp.setdefault('random_helpers', True)
    hlp.setdefault('time_helpers',       True)
    hlp.setdefault('validation_helpers',       True)

    # static files
    sf = config.setdefault('static_files', {})
    sf.setdefault('enabled',   False)
    sf.setdefault('route',     '/static')
    sf.setdefault('directory', './static')

    # template engine
    te = config.setdefault('template_engine', {})
    te.setdefault('enabled',      False)
    te.setdefault('template_dir', './templates')
    te.setdefault('extension',    '.html')
    te.setdefault('reload',       True)
    te.setdefault('time_format',  '02 Jan 15:04')

    # features
    feat = config.setdefault('features', {})
    feat.setdefault('cron_jobs',        False)

    # other top-level features — defaults so templates don't crash
    config.setdefault('email',         {}).setdefault('enabled', False)
    config.setdefault('imap',          {}).setdefault('enabled', False)
    config.setdefault('fcm',           {}).setdefault('enabled', False)
    config.setdefault('storage',       {}).setdefault('enabled', False)
    config.setdefault('notifications', {}).setdefault('enabled', False)
    config.setdefault('chat',          {}).setdefault('enabled', False)
    config.setdefault('websocket',     {}).setdefault('enabled', False)
    config.setdefault('rbac',          {}).setdefault('enabled', False)

    # authentication — minimal defaults so routes/main templates don't crash
    auth = config.setdefault('authentication', {})
    auth.setdefault('jwt',         {'enabled': False})
    auth.setdefault('social_auth', {'google': {'enabled': False}, 'facebook': {'enabled': False}})
    auth.setdefault('web_auth',    {'enabled': False})

    return config


# ─────────────────────────────────────────────────────────────────────────────
# Template decision table
# ─────────────────────────────────────────────────────────────────────────────

def get_templates(config: dict, t: str, o: str) -> list[tuple[str, str]]:
    result = [
        # config package
        (f'{t}/config/config.go.j2',          f'{o}/config/config.go'),
        (f'{t}/config/database.go.j2',         f'{o}/config/database.go'),
        (f'{t}/config/env.config.yaml.j2',     f'{o}/config/config.yaml'),
        (f'{t}/config/permissions.yaml.j2',     f'{o}/config/permissions.yaml'),

        # context helpers + routes + main
        (f'{t}/internal/routes/routes.go.j2',  f'{o}/internal/routes/routes.go'),
        (f'{t}/cmd/server/main.go.j2',         f'{o}/cmd/server/main.go'),

        # infra
        (f'{t}/infra/Dockerfile.j2',                 f'{o}/infra/Dockerfile'),
        (f'{t}/infra/docker-compose.yml.j2',         f'{o}/infra/docker-compose.yml'),
        (f'{t}/infra/Makefile.j2',                   f'{o}/infra/Makefile'),
        (f'{t}/infra/README.md.j2',                  f'{o}/infra/README.md'),
        (f'{t}/infra/gitignore.j2',                  f'{o}/.gitignore'),
        (f'{t}/infra/dockerignore.j2',               f'{o}/infra/.dockerignore'),
        (f'{t}/pkg/response/basic_response.j2', f'{o}/pkg/response/basic_response.go'),
        (f'{t}/pkg/utils/utils.go.j2',                            f'{o}/pkg/utils/utils.go'),
        (f'{t}/pkg/errors/handler.go.j2', f'{o}/pkg/errors/handler.go'),
        (f'{t}/pkg/utils/context_helpers.go.j2',f'{o}/pkg/utils/context_helpers.go'),
     
    ]

    # redis config — only if redis is enabled
    if config['redis'].get('enabled'):
        result.append((f'{t}/config/redis.go.j2', f'{o}/config/redis.go'))

    # swagger
    if config['swagger'].get('enabled'):
        result.append((f'{t}/docs/docs.go.j2', f'{o}/docs/docs.go'))
    if config['i18n'].get('enabled'):
        result.append((f'{t}/pkg/i18n/i18n.go.j2', f'{o}/pkg/i18n/i18n.go'))

    return result




# ─────────────────────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────────────────────

def run(config_path: str, templates_dir: str, output_dir: str):
    config    = build_context(config_path)
    templates = get_templates(config, templates_dir, output_dir)
    render_all(config, templates)


def main():
    parser = argparse.ArgumentParser(description='Generate Go app scaffold from YAML config')
    parser.add_argument('--config',    required=True)
    parser.add_argument('--templates', default='./tool/templates')
    parser.add_argument('--output',    default='./generated')
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"❌ Config not found: {args.config}"); sys.exit(1)

    print("=" * 60)
    print("  APP GENERATOR  (config / main / routes / infra)")
    print("=" * 60)
    run(args.config, args.templates, args.output)
    print("=" * 60 + "\n  DONE\n" + "=" * 60)


if __name__ == "__main__":
    main()