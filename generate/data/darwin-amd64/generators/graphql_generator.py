#!/usr/bin/env python3
"""
GraphQL Generator — Schema, resolvers, and subscription handlers.
Reads from: config.graphql
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
    
    gql = config.setdefault('graphql', {})
    gql.setdefault('enabled', False)
    gql.setdefault('path', '/graphql')
    gql.setdefault('playground', False)
    gql.setdefault('introspection', False)
    gql.setdefault('complexity_limit', 1000)
    gql.setdefault('models', {'include': [], 'exclude_fields': []})
    gql.setdefault('queries', [])
    gql.setdefault('mutations', [])
    gql.setdefault('subscriptions', {'enabled': False})
    
    # Build model mapping for GraphQL
    models = config.get('models', [])
    gql_models = []
    
    for model in models:
        if model['name'] not in gql['models'].get('include', []):
            continue
            
        gql_fields = []
        for field in model.get('fields', []):
            if field.get('json') == '-' or field['name'] in gql['models'].get('exclude_fields', []):
                continue
                
            # Map Go types to GraphQL types
            go_type = field.get('type', 'string')
            gql_type = _go_to_graphql_type(go_type)
            
            gql_fields.append({
                'name': field['name'],
                'graphql_name': _to_camel_case(field['name']),
                'type': gql_type,
                'go_type': go_type,
                'is_list': field.get('type', '').startswith('[]'),
                'is_required': not field.get('type', '').startswith('*') and 'omitempty' not in field.get('json', '')
            })
        
        # Add relations as fields
        for relation in model.get('relations', []):
            gql_fields.append({
                'name': relation['name'],
                'graphql_name': _to_camel_case(relation['name']),
                'type': relation['model'],
                'is_list': relation.get('type') in ['has_many', 'many_to_many'],
                'is_relation': True
            })
        
        gql_models.append({
            'name': model['name'],
            'fields': gql_fields,
            'has_timestamps': model.get('timestamps', False),
            'has_soft_delete': isinstance(model.get('soft_delete'), dict) and model['soft_delete'].get('enabled')
        })
    
    config['_gql_models'] = gql_models
    
    # Validation
    if gql.get('subscriptions', {}).get('enabled') and not config.get('websocket', {}).get('enabled'):
        print("❌ ERROR: GraphQL subscriptions enabled but WebSocket is disabled")
        sys.exit(1)
        
    return config


def _go_to_graphql_type(go_type: str) -> str:
    """Map Go types to GraphQL scalar types"""
    mapping = {
        'string': 'String',
        '*string': 'String',
        'int': 'Int',
        'int64': 'Int',
        'uint': 'Int',
        'uint64': 'Int',
        '*int': 'Int',
        'bool': 'Boolean',
        '*bool': 'Boolean',
        'float64': 'Float',
        'time.Time': 'Timestamp',
        '*time.Time': 'Timestamp',
    }
    # Handle slices
    if go_type.startswith('[]'):
        inner = go_type[2:]  # Remove []
        return f"[{_go_to_graphql_type(inner)}]"
    return mapping.get(go_type, 'String')


def _to_camel_case(snake_str: str) -> str:
    components = snake_str.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])


def get_templates(config: dict, t: str, o: str) -> list:
    if not config['graphql'].get('enabled'):
        return []
        
    result = [
        # Schema Definition Language
        (f'{t}/graphql/schema.graphql.j2', f'{o}/graphql/schema.graphql'),
        
        # Go generated code (for gqlgen)
        (f'{t}/graphql/resolver.go.j2', f'{o}/internal/graphql/resolver.go'),
        (f'{t}/graphql/generated.go.j2', f'{o}/internal/graphql/generated.go'),
        
        # Server setup
        (f'{t}/graphql/server.go.j2', f'{o}/internal/graphql/server.go'),
        
        # Complexity config
        (f'{t}/graphql/complexity.go.j2', f'{o}/internal/graphql/complexity.go'),
    ]
    
    # Subscriptions handler if enabled
    if config['graphql'].get('subscriptions', {}).get('enabled'):
        result.append((
            f'{t}/graphql/subscriptions.go.j2',
            f'{o}/internal/graphql/subscriptions.go'
        ))
    
    # Model-specific resolvers
    for model in config['_gql_models']:
        result.append((
            f'{t}/graphql/model_resolver.go.j2',
            f'{o}/internal/graphql/{model["name"].lower()}_resolver.go'
        ))
    
    return result


def run(config_path: str, templates_dir: str, output_dir: str):
    config = build_context(config_path)
    templates = get_templates(config, templates_dir, output_dir)
    render_all(config, templates)
    
    # Post-generation: Create gqlgen config if needed
    if config['graphql'].get('enabled'):
        _write_gqlgen_config(config, output_dir)


def _write_gqlgen_config(config: dict, output_dir: str):
    """Write gqlgen.yml for post-generation tooling"""
    gql_config = {
        'schema': ['graphql/schema.graphql'],
        'exec': {
            'filename': 'internal/graphql/generated.go',
            'package': 'graphql'
        },
        'model': {
            'filename': 'internal/graphql/models.go',
            'package': 'graphql'
        },
        'resolver': {
            'layout': 'follow-schema',
            'dir': 'internal/graphql',
            'package': 'graphql'
        },
        'models': {
            'ID': {'model': 'github.com/99designs/gqlgen/graphql.ID'},
            'Timestamp': {'model': 'github.com/99designs/gqlgen/graphql.Time'}
        }
    }
    
    import yaml
    gql_path = Path(output_dir) / 'gqlgen.yml'
    with open(gql_path, 'w') as f:
        yaml.dump(gql_config, f, default_flow_style=False)
    
    print(f"  ✓ Created gqlgen.yml (run 'go run github.com/99designs/gqlgen generate' after)")


def main():
    parser = argparse.ArgumentParser(description='Generate GraphQL files')
    parser.add_argument('--config', required=True)
    parser.add_argument('--templates', default='./tool/templates')
    parser.add_argument('--output', default='./generated')
    args = parser.parse_args()
    
    if not os.path.exists(args.config):
        print(f"❌ Config not found: {args.config}"); sys.exit(1)
    
    print("=" * 60)
    print("  GRAPHQL GENERATOR")
    print("=" * 60)
    run(args.config, args.templates, args.output)
    print("=" * 60 + "\n  DONE\n" + "=" * 60)


if __name__ == "__main__":
    main()