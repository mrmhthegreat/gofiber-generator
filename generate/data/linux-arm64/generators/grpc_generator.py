#!/usr/bin/env python3
"""
gRPC Generator — Proto files, service implementations, and gateway.
Reads from: config.grpc
"""

import os
import sys
import argparse
import yaml
from pathlib import Path
from generators.help_utils import render_all


def build_context(config_path: str) -> dict:
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    config.setdefault('project', {}).setdefault('module', 'github.com/user/project')
    
    grpc = config.setdefault('grpc', {})
    grpc.setdefault('enabled', False)
    grpc.setdefault('port', 50051)
    grpc.setdefault('package', 'api')
    grpc.setdefault('go_package', f'{config["project"]["module"]}/internal/proto')
    grpc.setdefault('tls', {'enabled': False})
    grpc.setdefault('gateway', {'enabled': False, 'port': 8081})
    grpc.setdefault('services', [])
    
    # Build service definitions from models
    models = {m['name']: m for m in config.get('models', [])}
    services = []
    
    for svc_def in grpc.get('services', []):
        svc_name = svc_def['name']
        model_names = svc_def.get('models', [])
        
        methods = []
        for model_name in model_names:
            if model_name not in models:
                continue
                
            model = models[model_name]
            exclude = svc_def.get('exclude_operations', [])
            
            # Standard CRUD methods
            if 'Create' not in exclude:
                methods.append(_build_method(model, 'Create', 'Create', is_create=True))
            if 'Get' not in exclude:
                methods.append(_build_method(model, 'Get', 'GetByID', is_get=True))
            if 'Update' not in exclude:
                methods.append(_build_method(model, 'Update', 'Update', is_update=True))
            if 'Delete' not in exclude:
                methods.append(_build_method(model, 'Delete', 'Delete', is_delete=True))
            if 'List' not in exclude:
                methods.append(_build_method(model, 'List', 'List', is_list=True))
        
        # Custom methods
        for custom in svc_def.get('custom_methods', []):
            methods.append({
                'name': custom['name'],
                'input': custom['input'],
                'output': custom['output'],
                'http_method': custom.get('http_mapping', {}).get('method', 'POST'),
                'http_path': custom.get('http_mapping', {}).get('path', f'/{svc_name}/{custom["name"]}')
            })
        
        services.append({
            'name': svc_name,
            'methods': methods,
            'models': model_names
        })
    
    config['_grpc_services'] = services
    return config


def _build_method(model: dict, op: str, repo_method: str, is_create=False, is_get=False, is_update=False, is_delete=False, is_list=False):
    """Build gRPC method definition from model"""
    name = model['name']
    
    method = {
        'name': f'{op}{name}',
        'input': f'{op}{name}Request',
        'output': f'{name}' if not is_list else f'List{name}Response',
        'repo_method': repo_method,
        'http_method': 'POST',
        'http_path': f'/api/v1/{name.lower()}s',
        'is_list': is_list
    }
    
    if is_get or is_update or is_delete:
        method['http_method'] = 'GET' if is_get else ('PUT' if is_update else 'DELETE')
        method['http_path'] = f'/api/v1/{name.lower()}s/{{id}}'
        method['input'] = f'{name}ByIDRequest'
    
    return method


def get_templates(config: dict, t: str, o: str) -> list:
    if not config['grpc'].get('enabled'):
        return []
        
    result = [
        # Proto files
        (f'{t}/grpc/api.proto.j2', f'{o}/proto/api.proto'),
        
        # Server implementation
        (f'{t}/grpc/server.go.j2', f'{o}/internal/grpc/server.go'),
        
        # Interceptors (auth, logging, recovery)
        (f'{t}/grpc/interceptors.go.j2', f'{o}/internal/grpc/interceptors.go'),
        
        # Service implementations
        (f'{t}/grpc/service_impl.go.j2', f'{o}/internal/grpc/service_impl.go'),
    ]
    
    # Gateway if enabled
    if config['grpc'].get('gateway', {}).get('enabled'):
        result.append((
            f'{t}/grpc/gateway.go.j2',
            f'{o}/internal/grpc/gateway.go'
        ))
    
    return result


def run(config_path: str, templates_dir: str, output_dir: str):
    config = build_context(config_path)
    templates = get_templates(config, templates_dir, output_dir)
    render_all(config, templates)
    
    # Write buf.gen.yaml for proto generation
    _write_buf_config(config, output_dir)


def _write_buf_config(config: dict, output_dir: str):
    """Write buf.gen.yaml for protoc/buf code generation"""
    buf_config = """version: v1
managed:
  enabled: true
plugins:
  - plugin: go
    out: .
    opt: paths=source_relative
  - plugin: go-grpc
    out: .
    opt: paths=source_relative,require_unimplemented_servers=false
"""
    
    if config['grpc'].get('gateway', {}).get('enabled'):
        buf_config += """  - plugin: grpc-gateway
    out: .
    opt: paths=source_relative
  - plugin: openapiv2
    out: ./docs
"""
    
    buf_path = Path(output_dir) / 'buf.gen.yaml'
    with open(buf_path, 'w') as f:
        f.write(buf_config)
    
    print("  ✓ Created buf.gen.yaml")
    print("  ℹ️  Run 'buf generate' or protoc to generate Go from proto files")


def main():
    parser = argparse.ArgumentParser(description='Generate gRPC files')
    parser.add_argument('--config', required=True)
    parser.add_argument('--templates', default='./tool/templates')
    parser.add_argument('--output', default='./generated')
    args = parser.parse_args()
    
    if not os.path.exists(args.config):
        print(f"❌ Config not found: {args.config}"); sys.exit(1)
    
    print("=" * 60)
    print("  GRPC GENERATOR")
    print("=" * 60)
    run(args.config, args.args.templates, args.output)
    print("=" * 60 + "\n  DONE\n" + "=" * 60)


if __name__ == "__main__":
    main()