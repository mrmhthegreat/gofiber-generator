#!/usr/bin/env python3
"""
Enhanced GORM Model and Repository Generator with DTOs and Responses

This script reads a YAML configuration file and generates Go models, repositories,
DTOs (Data Transfer Objects), and response structures using Jinja2 templates.

Features:
- Dynamic Create/Update DTOs with field selection
- Smart response generation (List, Detail, Nested)
- Proper nil checks and field mapping
- Custom getter responses
- Flexible field ordering

Usage:
    python repo_generate_enhanced.py --config model_config.yaml --output-dir ./generated
"""

import os
import sys
import argparse
import yaml
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, Template
from typing import Dict, List, Any, Set


class ModelGenerator:
    """Generator for Go models, repositories, DTOs, and responses from YAML configuration"""
    
    def __init__(self, config_path: str, templates_dir: str, output_dir: str):
        """
        Initialize the generator
        
        Args:
            config_path: Path to the YAML configuration file
            templates_dir: Directory containing Jinja2 templates
            output_dir: Directory where generated files will be saved
        """
        self.config_path = config_path
        self.templates_dir = templates_dir
        self.output_dir = output_dir
        self.is_share_generate = False
        
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Setup Jinja2 environment
        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        # Add custom filters
        self.env.filters['tojson'] = lambda x: f'"{x}"'
        self.env.filters['to_go_type'] = self.to_go_type
        self.env.filters['is_pointer'] = lambda t: t.startswith('*')
        self.env.filters['strip_pointer'] = lambda t: t[1:] if t.startswith('*') else t

        # Setup Web Jinja2 environment with custom delimiters
        self.web_env = Environment(
            loader=FileSystemLoader(templates_dir),
            trim_blocks=True,
            lstrip_blocks=True,
            block_start_string='[%',
            block_end_string='%]',
            variable_start_string='[[',
            variable_end_string=']]',
            comment_start_string='[#',
            comment_end_string='#]',
        )
        self.web_env.filters = self.env.filters.copy()
        
    def to_go_type(self, field_type: str) -> str:
        """Convert field type to appropriate Go type"""
        type_map = {
            'uint': 'uint',
            'int': 'int',
            'int64': 'int64',
            'string': 'string',
            'bool': 'bool',
            'time.Time': 'time.Time',
            '*time.Time': '*time.Time',
            'datatypes.JSON': 'datatypes.JSON',
        }
        return type_map.get(field_type, field_type)
    
    def is_soft_delete_enabled(self, model: Dict[str, Any]) -> bool:
        """Safely check if soft_delete is enabled"""
        soft_delete = model.get('soft_delete', False)
        if isinstance(soft_delete, dict):
            return soft_delete.get('enabled', False)
        return bool(soft_delete)
    def process_web_handler(self, model: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process web handler configuration and generate endpoint contexts.
        Similar to process_controller but for web/HTML handlers.
        """
        handler_cfg = model.get('web_handler', {})
        if not handler_cfg.get('enabled', False):
            return None
        
        name = model['name']
        base_path = handler_cfg.get('base_path', f'/dashboard/{name.lower()}')
        middleware = handler_cfg.get('middleware', ['auth'])
        rate_limit = handler_cfg.get('rate_limit', {})
        package_name = handler_cfg.get('package_name', 'handlers')
        auth_redirect = handler_cfg.get('auth_redirect', '/login')
        template_base = handler_cfg.get('template_base', f'views/{name.lower()}')
        
        # RBAC settings
        rbac_cfg = handler_cfg.get('rbac', {})
        rbac_enabled = rbac_cfg.get('enabled', False)
        rbac_service_var = rbac_cfg.get('service_var', 'rbacService')
        
        # Helper: resolve DTO name
        def resolve_dto(dto_name: str, op_type: str) -> str:
            if dto_name:
                return dto_name
            # Try defaults
            if op_type == 'create':
                return model.get('create_dto', {}).get('enabled') and f'Create{name}Request' or ''
            if op_type == 'update':
                return model.get('update_dto', {}).get('enabled') and f'Update{name}Request' or ''
            return ''
    
        # Helper: get file uploads from DTO
        def dto_file_uploads(dto_name: str) -> List[Dict]:
            if not dto_name:
                return []
            
            # Find DTO config
            dto_config = None
            for dto in model.get('dtos', []):
                if dto['name'] == dto_name:
                    dto_config = dto
                    break
            
            if not dto_config or not dto_config.get('file_fields'):
                return []
        
            # Get model-level defaults
            model_defaults = model.get('file_upload_defaults', {})
            
            file_uploads = []
            for field_name, field_type in dto_config['file_fields'].items():
                if field_type != 'file':
                    continue
            
                # Check DTO-level settings
                dto_file_settings = dto_config.get('file_upload_settings', {}).get(field_name, {})
                
                file_cfg = {
                    'field': field_name,
                    'form_field': dto_file_settings.get('form_field', 
                        self.to_snake_case(field_name)),
                    'storage_path': dto_file_settings.get('storage_path',
                        model_defaults.get('storage_path', f'uploads/{name.lower()}')),
                    'max_size_mb': dto_file_settings.get('max_size_mb',
                        model_defaults.get('max_size_mb', 5)),
                    'allowed_types': dto_file_settings.get('allowed_types',
                        model_defaults.get('allowed_types', [])),
                    'required': dto_file_settings.get('required',
                        model_defaults.get('required', False)),
                }
                file_uploads.append(file_cfg)
        
            return file_uploads
    
        # Helper: process file uploads (explicit or auto-detect)
        def process_file_uploads(endpoint_cfg: Dict, dto_name: str) -> List[Dict]:
            # Explicit file_uploads take precedence
            if 'file_uploads' in endpoint_cfg:
                file_uploads = []
                for f in endpoint_cfg['file_uploads']:
                    file_cfg = {
                        'field': f['field'],
                        'form_field': f.get('form_field', self.to_snake_case(f['field'])),
                        'storage_path': f.get('storage_path', f'uploads/{name.lower()}'),
                        'max_size_mb': f.get('max_size_mb', 5),
                        'allowed_types': f.get('allowed_types', []),
                        'required': f.get('required', False),
                    }
                    file_uploads.append(file_cfg)
                return file_uploads
            
            # Auto-detect from DTO
            return dto_file_uploads(dto_name)
    
        # Helper: process context data
        def process_context(ctx_cfg: Dict) -> Dict:
            # Always provide user_config with defaults
            user_cfg_input = ctx_cfg.get('user_config', {}) if ctx_cfg.get('needs_user') else {}
            
            user_config = {
                'use_repo': user_cfg_input.get('use_repo', False),
                'repo_name': user_cfg_input.get('repo_name', 'userRepo'),
                'method': user_cfg_input.get('method', 'GetByID'),
            }
            
            return {
                'needs_user': ctx_cfg.get('needs_user', False),
                'user_config': user_config,  # Always present with safe defaults
                'needs_csrf': ctx_cfg.get('needs_csrf', True),
                'needs_perms': ctx_cfg.get('needs_perms', False),
            'needs_dashbase': ctx_cfg.get('needs_dashbase', False),
            'needs_translations': ctx_cfg.get('needs_translations', False),
            'base_translations': ctx_cfg.get('base_translations', ''),
            'extra_translations': ctx_cfg.get('extra_translations', []),
            'custom_data': ctx_cfg.get('custom_data', []),
         }
    
        # Helper: process path params
        def process_path_params(params_cfg: List[Dict]) -> List[Dict]:
            params = []
            for p in params_cfg:
                params.append({
                    'name': p['name'],
                'type': p.get('type', 'uint'),
                'var_name': p['name'],
            })
            return params
    
        # Helper: process query params
        def process_query_params(params_cfg: List[Dict]) -> List[Dict]:
            params = []
            for p in params_cfg:
                params.append({
                    'name': p['name'],
                    'type': p.get('type', 'string'),
                    'default': p.get('default', ''),
                    'var_name': p['name'] + 'Val',
                })
            return params
    
        # Helper: get update fields from DTO
        def get_update_fields(dto_name: str) -> List[Dict]:
            if not dto_name:
                return []
        
            fields = []
            for dto in model.get('dtos', []):
                if dto['name'] == dto_name:
                    for field_name in dto.get('fields', []):
                        field_cfg = self.get_field_by_name(model, field_name)
                        if field_cfg:
                            ft = field_cfg.get('type', 'string')
                            fields.append({
                                'name': field_name,
                                'type': ft,
                                'is_pointer': ft.startswith('*'),
                                'db_column': field_cfg.get('json', field_name.lower()),
                            })
                
                # Add file fields
                if dto.get('file_fields'):
                    for field_name, field_type in dto['file_fields'].items():
                        if field_type == 'file':
                            field_cfg = self.get_field_by_name(model, field_name)
                            if field_cfg:
                                fields.append({
                                    'name': field_name,
                                    'type': 'file',
                                    'is_pointer': False,
                                    'db_column': field_cfg.get('json', field_name.lower()),
                                    'form_field': self.to_snake_case(field_name),
                                    'storage_path': f'uploads/{name.lower()}',
                                })
                break
        
            return fields
    
        # Process CRUD endpoints
        crud_settings = handler_cfg.get('crud_settings', {})
        endpoints = []
    
        # --- CREATE PAGE ---
        create_page_cfg = crud_settings.get('create_page', {})
        if create_page_cfg.get('enabled', False):
            cp_middleware = create_page_cfg.get('middleware', middleware)
            cp_rate_limit = create_page_cfg.get('rate_limit', rate_limit)
            endpoints.append({
                'type': 'create_page',
                'handler_type': 'page',
                'method': 'GET',
                'rate_limit': cp_rate_limit,
                'middleware':cp_middleware,
                'path': base_path + create_page_cfg.get('path', '/new'),
                'func_name': f'Create{name}Page',
                'model': name,
                'template': f"{template_base}/{create_page_cfg.get('template', 'create.html')}",
                'permissions': create_page_cfg.get('permissions', []),
                'context': process_context(create_page_cfg.get('context', {})),

                'path_params': [],
                'query_params': [],
            })
    
        # --- CREATE ACTION ---
        create_cfg = crud_settings.get('create', {})
        if create_cfg.get('enabled', False):
            dto_name = resolve_dto(create_cfg.get('dto', ''), 'create')
            file_ups = process_file_uploads(create_cfg, dto_name)
            
            ownership = create_cfg.get('ownership', {})
            c_middleware = create_cfg.get('middleware', middleware)
            c_rate_limit = create_cfg.get('rate_limit', rate_limit)
            endpoints.append({
                'type': 'create',
                'handler_type': create_cfg.get('handler_type', 'action'),
                'method': create_cfg.get('method', 'POST'),
                'path': base_path + create_cfg.get('path', ''),
                'func_name': f'Create{name}',
                'model': name,
                'middleware':c_middleware,
                'rate_limit': c_rate_limit,
                'dto_name': dto_name,
                'file_uploads': file_ups,
                'has_file_uploads': bool(file_ups),
                'return_type': create_cfg.get('return_type', 'redirect'),
                'redirect_on_success': create_cfg.get('redirect_on_success', base_path),
                'hx_redirect': create_cfg.get('hx_redirect', ''),
                'template': create_cfg.get('template', ''),
                'permissions': create_cfg.get('permissions', []),
                'ownership': {
                    'enabled': ownership.get('enabled', False),
                    'field': ownership.get('field', 'UserID'),
                    'go_field': ownership.get('field', 'UserID').replace('_', ' ').title().replace(' ', ''),
                    'auto_fill': ownership.get('auto_fill', 'user_id'),
                },
                'auto_fields': create_cfg.get('auto_fields', []),
                'context': process_context(create_cfg.get('context', {})),
            })
    
        # --- EDIT PAGE ---
        edit_page_cfg = crud_settings.get('edit_page', {})
        if edit_page_cfg.get('enabled', False):
            path_params = process_path_params(edit_page_cfg.get('path_params', []))
            own_cfg = edit_page_cfg.get('ownership', {})
            e_middleware = edit_page_cfg.get('middleware', middleware)
            e_rate_limit = edit_page_cfg.get('rate_limit', rate_limit)
            # Build ownership with repo_method support
            ownership = {'enabled': False}
            if own_cfg.get('enabled', False):
                ownership = {
                    'enabled': True,
                    'field': own_cfg.get('field', 'UserID'),
                    'go_field': own_cfg.get('field', 'UserID').replace('_id', 'ID').replace('_', ' ').title().replace(' ', ''),
                    'verify': own_cfg.get('verify', 'field'),
                }
                # If verify=param and repo_method is specified
                if ownership['verify'] == 'param' and own_cfg.get('repo_method'):
                    ownership['repo_method'] = own_cfg.get('repo_method')
                    # Build args from path_params, WITH userID first (like controller does)
                    args = ['userID']  # Always first!
                    for p in path_params:
                        args.append(p['name'])
                    ownership['repo_method_args_str'] = ', '.join(args)
        
            endpoints.append({
            'type': 'edit_page',
            'handler_type': 'page',
            'method': 'GET',
            'rate_limit': e_rate_limit,
            'path': base_path + edit_page_cfg.get('path', '/:id/edit'),
            'func_name': f'Edit{name}Page',
            'model': name,
            'middleware':e_middleware,
            'template': f"{template_base}/{edit_page_cfg.get('template', 'edit.html')}",
            'permissions': edit_page_cfg.get('permissions', []),
            'context': process_context(edit_page_cfg.get('context', {})),
            'path_params': path_params,
            'ownership': ownership,
        })
    
        # --- UPDATE ACTION ---
        update_cfg = crud_settings.get('update', {})
        if update_cfg.get('enabled', False):
            dto_name = resolve_dto(update_cfg.get('dto', ''), 'update')
            file_ups = process_file_uploads(update_cfg, dto_name)
            path_params = process_path_params(update_cfg.get('path_params', []))
            u_middleware = update_cfg.get('middleware', middleware)
            u_rate_limit = update_cfg.get('rate_limit', rate_limit)
            own_cfg = update_cfg.get('ownership', {})
            
            # Build ownership with repo_method support
            ownership = {'enabled': False}
            if own_cfg.get('enabled', False):
                ownership = {
                    'enabled': True,
                    'field': own_cfg.get('field', 'UserID'),
                    'go_field': own_cfg.get('field', 'UserID').replace('_id', 'ID').replace('_', ' ').title().replace(' ', ''),
                    'verify': own_cfg.get('verify', 'field'),
                }
                # If verify=param and repo_method is specified
                if ownership['verify'] == 'param' and own_cfg.get('repo_method'):
                    ownership['repo_method'] = own_cfg.get('repo_method')
                    # Build args from path_params, WITH userID first (like controller does)
                    args = ['userID']  # Always first!
                    for p in path_params:
                        args.append(p['name'])
                    ownership['repo_method_args_str'] = ', '.join(args)
        
            endpoints.append({
            'type': 'update',
            'handler_type': update_cfg.get('handler_type', 'action'),
            'method': update_cfg.get('method', 'POST'),
            'path': base_path + update_cfg.get('path', '/:id'),
            'func_name': f'Update{name}',
            'model': name,
            'rate_limit': u_rate_limit,
            'middleware':u_middleware,
            'dto_name': dto_name,
            'file_uploads': file_ups,
            'has_file_uploads': bool(file_ups),
            'return_type': update_cfg.get('return_type', 'redirect'),
            'redirect_on_success': update_cfg.get('redirect_on_success', base_path),
            'hx_redirect': update_cfg.get('hx_redirect', ''),
            'template': update_cfg.get('template', ''),
            'permissions': update_cfg.get('permissions', []),
            'track_changes': update_cfg.get('track_changes', False),
            'update_fields': get_update_fields(dto_name) if update_cfg.get('track_changes') else [],
            'ownership': ownership,
            'path_params': path_params,
            'context': process_context(update_cfg.get('context', {})),
        })
    
        # --- GET/SHOW ---
        get_cfg = crud_settings.get('get', {})
        if get_cfg.get('enabled', False):
            path_params = process_path_params(get_cfg.get('path_params', []))
            g_middleware = get_cfg.get('middleware', middleware)
            g_rate_limit = get_cfg.get('rate_limit', rate_limit)
            endpoints.append({
                'type': 'get',
                'handler_type': 'page',
                'method': 'GET',
                'rate_limit': g_rate_limit,
                'path': base_path + get_cfg.get('path', '/:id'),
                'func_name': f'Show{name}',
                'model': name,
                'template': f"{template_base}/{get_cfg.get('template', 'show.html')}",
                'permissions': get_cfg.get('permissions', []),
                'context': process_context(get_cfg.get('context', {})),
                'path_params': path_params,
                'ownership': get_cfg.get('ownership', {'enabled': False}),
            })
    
        # --- LIST/INDEX ---
        list_cfg = crud_settings.get('list', {})
        if list_cfg.get('enabled', False):
            query_params = process_query_params(list_cfg.get('query_params', []))
            l_middleware = list_cfg.get('middleware', middleware)
            l_rate_limit = list_cfg.get('rate_limit', rate_limit)
            endpoints.append({
            'type': 'list',
            'handler_type': 'page',
            'method': 'GET',
            'rate_limit': l_rate_limit,
            'path': base_path + list_cfg.get('path', ''),
            'func_name': f'List{name}',
            'model': name,
            'middleware':l_middleware,
            'template': f"{template_base}/{list_cfg.get('template', 'index.html')}",
            'permissions': list_cfg.get('permissions', []),
            'pagination': list_cfg.get('pagination', False),
            'context': process_context(list_cfg.get('context', {})),
            'query_params': query_params,
        })
    
        # --- DELETE ---
        delete_cfg = crud_settings.get('delete', {})
        if delete_cfg.get('enabled', False):
            path_params = process_path_params(delete_cfg.get('path_params', []))
            own_cfg = delete_cfg.get('ownership', {})
            d_middleware = delete_cfg.get('middleware', middleware)
            d_rate_limit = delete_cfg.get('rate_limit', rate_limit)
            # Build ownership with repo_method support
            ownership = {'enabled': False}
            if own_cfg.get('enabled', False):
                ownership = {
                    'enabled': True,
                    'field': own_cfg.get('field', 'UserID'),
                    'go_field': own_cfg.get('field', 'UserID').replace('_id', 'ID').replace('_', ' ').title().replace(' ', ''),
                    'verify': own_cfg.get('verify', 'field'),
                }
                # If verify=param and repo_method is specified
                if ownership['verify'] == 'param' and own_cfg.get('repo_method'):
                    ownership['repo_method'] = own_cfg.get('repo_method')
                    # Build args from path_params, WITH userID first (like controller does)
                    args = ['userID']  # Always first!
                    for p in path_params:
                        args.append(p['name'])
                    ownership['repo_method_args_str'] = ', '.join(args)
        
            endpoints.append({
                'type': 'delete',
                'handler_type': 'action',
                'rate_limit': d_rate_limit,
                'method': delete_cfg.get('method', 'DELETE'),
                'path': base_path + delete_cfg.get('path', '/:id'),
                'func_name': f'Delete{name}',
                'model': name,
                'middleware':d_middleware,
                'return_type': delete_cfg.get('return_type', 'json'),
                'redirect_on_success': delete_cfg.get('redirect_on_success', base_path),
                'permissions': delete_cfg.get('permissions', []),
                'ownership': ownership,
                'path_params': path_params,
            })
    
        # Process custom getter endpoints
        getter_endpoints = []
        for getter in model.get('custom_getters', []):
            getter_handler_cfg = getter.get('web_handler', {})
            if not getter_handler_cfg.get('enabled', False):
                continue
        
            path_params = process_path_params(getter_handler_cfg.get('path_params', []))
            query_params = process_query_params(getter_handler_cfg.get('query_params', []))
            g_middleware = getter_handler_cfg.get('middleware', middleware)
            g_rate_limit = getter_handler_cfg.get('rate_limit', rate_limit)
            getter_endpoints.append({
                'type': 'custom_getter',
                'handler_type': getter_handler_cfg.get('handler_type', 'page'),
                'getter_name': getter['name'],
                'method': 'GET',  # Always GET for custom getters
                'path': getter_handler_cfg.get('path', f"{base_path}/{getter['name'].lower()}"),
                'func_name': getter['name'],
                'rate_limit': g_rate_limit,
                'model': name,
                'middleware':g_middleware,
                'template': getter_handler_cfg.get('template', f"{template_base}/{getter['name'].lower()}.html"),
                'permissions': getter_handler_cfg.get('permissions', []),
                'unique': getter.get('unique', False),
                'pagination': getter.get('pagination', False),
                'context': process_context(getter_handler_cfg.get('context', {})),
                'path_params': path_params,
                'query_params': query_params,
                'ownership': getter_handler_cfg.get('ownership', {'enabled': False}),
            })
    
        # Check what imports are needed
        needs_user_repo = any(
            ep.get('context', {}).get('needs_user', False) 
            for ep in endpoints
        )

        return {
            'model': name,
            'package_name': package_name,
            'base_path': base_path,
            'middleware': middleware,
            'auth_redirect': auth_redirect,
            'rate_limit': rate_limit,
            'template_base': template_base,
            'rbac': {
                'enabled': rbac_enabled,
                'service_var': rbac_service_var,
            },
            'crud_settings': crud_settings,
            'endpoints': endpoints,
            'getter_endpoints': getter_endpoints,
            'needs_user_repo': False,  # Not needed - repos come from contexthelpers
            'repo_types': [],  # Not needed - repos come from contexthelpers
            'repo_var': f'{name[0].lower()}{name[1:]}Repo',
            'repo_type': f'repository.{name}Repository',
        }

    def process_model(self, model: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process and enhance model configuration with computed properties
        
        Args:
            model: Raw model configuration from YAML
            
        Returns:
            Enhanced model configuration
        """
        processed = model.copy()
        
        # --- NEW LOGIC: Standardize ID and Inject Auth Fields ---
        project_cfg = self.config.get('project', {})
        user_model_name = project_cfg.get('user_model_name', 'User')
        
        auth_cfg = self.config.get('authentication', {})
        fcm_cfg = self.config.get('fcm', {})
        
        raw_fields = processed.get('fields', [])
        
        # 1. Always enforce standard ID field
        fixed_id_field = {
            "name": "ID",
            "type": "uint",
            "gorm": "primaryKey;autoIncrement",
            "json": "id"
        }
        
        # Filter out existing ID fields (case insensitive)
        existing_field_names = []
        filtered_fields = []
        for f in raw_fields:
            if f.get('name', '').lower() != 'id':
                filtered_fields.append(f)
                existing_field_names.append(f.get('name', '').lower())
                
        final_fields = [fixed_id_field] + filtered_fields
        
        # 2. Inject Dynamic User Fields based on config
        if processed.get('name') == user_model_name:
            # Helper to add field if not exists
            def add_field_if_missing(f_cfg):
                if f_cfg['name'].lower() not in existing_field_names:
                    final_fields.append(f_cfg)
                    existing_field_names.append(f_cfg['name'].lower())

            # a. Login Identifier Fields (Email / Username)
            ident_cfg = auth_cfg.get('identifier', {})
            login_methods = ident_cfg.get('login_methods', [])
            
            uses_email = False
            uses_username = False
            
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
            
            if uses_email:
                add_field_if_missing({
                    "name": "Email", "type": "string", "gorm": "unique;not null;index", "json": "email", "validate": "required,email"
                })
                
            if uses_username:
                add_field_if_missing({
                    "name": "Username", "type": "string", "gorm": "unique;not null;index", "json": "username", "validate": "required,min=3,max=50,alphanum"
                })
                
            # b. Password Field
            email_pass_cfg = auth_cfg.get('email_password', {})
            if email_pass_cfg.get('enabled', False) or (not auth_cfg.get('social_auth') and auth_cfg.get('enabled', False)):
                add_field_if_missing({
                    "name": "Password", "type": "string", "gorm": "not null", "json": "-"
                })
                
            # c. Email Verification
            email_verif_cfg = auth_cfg.get('email_verification', {})
            if email_verif_cfg.get('enabled', False):
                # ensure email exists if not already added by login_methods
                if not uses_email:
                    add_field_if_missing({
                        "name": "Email", "type": "string", "gorm": "unique;not null;index", "json": "email", "validate": "required,email"
                    })
                add_field_if_missing({
                    "name": "Verified", "type": "bool", "gorm": "default:false", "json": "verified"
                })
                
            # d. Social Auth
            social_cfg = auth_cfg.get('social_auth', {})
            has_social = False
            for provider, p_cfg in social_cfg.items():
                if isinstance(p_cfg, dict) and p_cfg.get('enabled', False):
                    has_social = True
                    # Check for provider specific model fields
                    if provider=="google":
                        add_field_if_missing({
                            "name": "GoogleID", "type": "*string", "gorm": "uniqueIndex", "json": "google_id"
                        })
                    elif provider=="facebook":
                        add_field_if_missing({
                            "name": "FacebookID", "type": "*string", "gorm": "uniqueIndex", "json": "facebook_id"
                        })
                   
            
            if has_social:
                add_field_if_missing({
                    "name": "AuthProvider", "type": "string", "gorm": "default:'local'", "json": "auth_provider"
                })
                
            # e. FCM Token
            if fcm_cfg.get('enabled', False):
                add_field_if_missing({
                    "name": "FCMToken", "type": "*string", "gorm": "index", "json": "fcm_token"
                })
                
        processed['fields'] = final_fields
        # --- END NEW LOGIC ---
        
        # Detect if model has time fields
        processed['has_time_fields'] = any(
            field.get('type') in ['time.Time', '*time.Time'] 
            for field in processed.get('fields', [])
        )
        
        # Detect if model has JSON fields
        processed['has_json_fields'] = any(
            'datatypes.JSON' in field.get('type', '') 
            for field in processed.get('fields', [])
        )
        
        # Set default pagination settings
        if 'pagination' not in processed:
            processed['pagination'] = False
        
        # Set default filters
        if 'filters' not in processed:
            processed['filters'] = []
        
        # Set default sort fields
        if 'sort_by' not in processed:
            processed['sort_by'] = []
        
        # Set default search fields
        if 'search_fields' not in processed:
            processed['search_fields'] = []
        
        # Set default soft_delete configuration
        if 'soft_delete' not in processed:
            processed['soft_delete'] = False
        elif processed['soft_delete'] is True:
            processed['soft_delete'] = {
                'enabled': True,
                'include_hard_delete': False,
                'include_restore': False
            }
        
        # Set default timestamps
        if 'timestamps' not in processed:
            processed['timestamps'] = False
        
        # Process relations
        if 'relations' in processed:
            for relation in processed['relations']:
                # Set default omitempty for relations
                if 'omitempty' not in relation:
                    relation['omitempty'] = True
        
        # Process DTOs
        processed = self.process_dtos(processed)
        
        # Process responses
        processed = self.process_responses(processed)
        
        # Process custom getters
        if 'custom_getters' in processed:
            for getter in processed['custom_getters']:
                # Set default field types if not specified
                if 'field_types' not in getter:
                    getter['field_types'] = ['string'] * len(getter.get('fields', []))
                
                # Set default unique flag
                if 'unique' not in getter:
                    getter['unique'] = False
                
                # Set response type
                if 'response_type' not in getter:
                    if getter['unique']:
                        getter['response_type'] = 'detail'
                    else:
                        getter['response_type'] = 'list'
                
                # Handle select_fields - if specified, create a custom response
                has_select = 'select_fields' in getter and getter['select_fields']
                has_preloads = bool(getter.get('preloads'))
                needs_custom = (has_select or has_preloads) and getter.get('response_type') in ['list', 'detail']

                if needs_custom and 'custom_response' not in getter:
                    response_name = f"{getter['name']}Response"
                    custom_fields = []

                    # --- Main model fields from select_fields (or all model fields if no select) ---
                    source_fields = getter.get('select_fields', [])
                    if source_fields:
                        for field_name in source_fields:
                            field_config = self.get_field_by_name(processed, field_name)
                            if field_config:
                                custom_fields.append({
                                    'name': field_config['name'],
                                    'type': field_config['type'],
                                    'json_name': field_config.get('json', field_name.lower()),
                                    'from_field': field_config['name'],
                                    'omitempty': field_config.get('type', '').startswith('*')
                                })
                            elif field_name.lower() in ['created_at', 'updated_at'] and processed.get('timestamps'):
                                go_name = field_name.replace('_', ' ').title().replace(' ', '')
                                custom_fields.append({
                                    'name': go_name,
                                    'type': 'time.Time',
                                    'json_name': field_name.lower(),
                                    'from_field': go_name,
                                    'omitempty': False
                                })
                    else:
                        # No select_fields: include ALL model fields (minus sensitive)
                        for field in processed.get('fields', []):
                            fn = field['name']
                            jn = field.get('json', fn.lower())
                            if jn == '-' or 'password' in fn.lower():
                                continue
                            custom_fields.append({
                                'name': fn,
                                'type': field.get('type', 'string'),
                                'json_name': jn,
                                'from_field': fn,
                                'omitempty': field.get('type', '').startswith('*')
                            })
                        if processed.get('timestamps'):
                            custom_fields.extend([
                                {'name': 'CreatedAt', 'type': 'time.Time', 'json_name': 'created_at', 'from_field': 'CreatedAt', 'omitempty': False},
                                {'name': 'UpdatedAt', 'type': 'time.Time', 'json_name': 'updated_at', 'from_field': 'UpdatedAt', 'omitempty': False},
                            ])

                    # --- Preload relation fields ---
                    preload_relations = []
                    for preload in getter.get('preloads', []):
                        pname = preload['name']
                        pselect = preload.get('select_fields', [])

                        # Look up the relation definition + related model config
                        prel_def, prelated_model = self.get_relation_info(processed, pname)

                        # Determine if this relation is list (has_many/many_to_many) or single
                        rel_type = 'single'
                        if prel_def and prel_def.get('type') in ['has_many', 'many_to_many']:
                            rel_type = 'list'

                        # Build typed fields for the nested struct
                        if pselect:
                            nested_typed_fields = self.build_typed_fields_from_model(prelated_model, pselect)
                        else:
                            # No select — use all fields of the related model (minus sensitive)
                            if prelated_model:
                                nested_typed_fields = []
                                for f in prelated_model.get('fields', []):
                                    fn = f['name']
                                    jn = f.get('json', fn.lower())
                                    if jn == '-' or 'password' in fn.lower():
                                        continue
                                    ft = f.get('type', 'string')
                                    nested_typed_fields.append({
                                        'go_name': fn, 'type': ft,
                                        'json_name': jn, 'from_field': fn,
                                        'omitempty': ft.startswith('*')
                                    })
                            else:
                                nested_typed_fields = [{'go_name': 'ID', 'type': 'uint',
                                                        'json_name': 'id', 'from_field': 'ID',
                                                        'omitempty': False}]

                        # Build nested response struct name
                        nested_struct = f"{getter['name']}{pname}Item"

                        # Collect nested_relations for this preload
                        nested_responses = []
                        for nested in preload.get('nested_relations', []):
                            nname = nested['name']
                            nselect = nested.get('select_fields', [])

                            # Look up nested relation type from the related model
                            nrel_type = 'list'
                            if prelated_model:
                                for r in prelated_model.get('relations', []):
                                    if r['name'] == nname:
                                        nrel_type = 'list' if r.get('type') in ['has_many', 'many_to_many'] else 'single'
                                        # Get the deeply-nested model for typed fields
                                        nrelated_model = self.get_model_by_name(r['model'])
                                        break
                                else:
                                    nrelated_model = None
                            else:
                                nrelated_model = None

                            if nselect:
                                n_typed_fields = self.build_typed_fields_from_model(nrelated_model, nselect)
                            else:
                                n_typed_fields = [{'go_name': 'ID', 'type': 'uint',
                                                   'json_name': 'id', 'from_field': 'ID',
                                                   'omitempty': False}]

                            nested_responses.append({
                                'name': nname,
                                'struct': f"{getter['name']}{pname}{nname}Item",
                                'rel_type': nrel_type,
                                'select_fields': nselect,
                                'typed_fields': n_typed_fields,
                                'order_by': nested.get('order_by', ''),
                                'limit': nested.get('limit'),
                            })

                        preload_relations.append({
                            'name': pname,
                            'rel_type': rel_type,
                            'struct': nested_struct,
                            'select_fields': pselect,
                            'typed_fields': nested_typed_fields,
                            'nested_responses': nested_responses,
                            'order_by': preload.get('order_by', ''),
                            'limit': preload.get('limit'),
                        })

                    getter['custom_response'] = {
                        'name': response_name,
                        'fields': custom_fields,
                        'preload_relations': preload_relations,
                    }
                    getter['response_type'] = 'custom'
        
        # Process batch operations
        if 'batch_operations' in processed:
            for batch_op in processed['batch_operations']:
                # Set default soft_delete for DeleteMultiple
                if batch_op.get('name') == 'DeleteMultiple' and 'soft_delete' not in batch_op:
                    batch_op['soft_delete'] = self.is_soft_delete_enabled(processed)
        
        # Set default admin queries
        if 'admin_queries' not in processed:
            processed['admin_queries'] = {'enabled': False}
        
        return processed
    
    def process_dtos(self, model: Dict[str, Any]) -> Dict[str, Any]:
        """Process DTO configurations for create and update operations"""
        
        # Support multiple DTOs - convert single to list
        if 'dtos' in model:
            # Already using new format
            if not isinstance(model['dtos'], list):
                model['dtos'] = [model['dtos']]
        else:
            # Convert old format to new list format
            dtos = []
            
            # Process Create DTO
            if 'create_dto' in model:
                create_dto = model['create_dto'] if isinstance(model['create_dto'], dict) else {'enabled': True}
                if create_dto.get('enabled', True):
                    if 'fields' not in create_dto:
                        # Auto-generate from required fields
                        create_fields = []
                        for field in model.get('fields', []):
                            field_name = field['name']
                            if field_name in ['ID', 'CreatedAt', 'UpdatedAt', 'DeletedAt']:
                                continue
                            if field.get('type', '').startswith('*') and 'default' in field.get('gorm', ''):
                                continue
                            create_fields.append(field_name)
                        create_dto['fields'] = create_fields
                    
                    create_dto['name'] = create_dto.get('name', f'Create{model["name"]}Request')
                    create_dto['type'] = 'create'
                    if 'custom_fields' not in create_dto:
                        create_dto['custom_fields'] = []
                    if 'file_fields' not in create_dto:
                        create_dto['file_fields'] = {}
                    dtos.append(create_dto)
            
            # Process Update DTO
            if 'update_dto' in model:
                update_dto = model['update_dto'] if isinstance(model['update_dto'], dict) else {'enabled': True}
                if update_dto.get('enabled', True):
                    if 'fields' not in update_dto:
                        # Auto-generate from all editable fields
                        update_fields = []
                        for field in model.get('fields', []):
                            field_name = field['name']
                            if field_name in ['ID', 'CreatedAt', 'UpdatedAt', 'DeletedAt']:
                                continue
                            update_fields.append(field_name)
                        update_dto['fields'] = update_fields
                    
                    update_dto['name'] = update_dto.get('name', f'Update{model["name"]}Request')
                    update_dto['type'] = 'update'
                    if 'partial' not in update_dto:
                        update_dto['partial'] = True
                    if 'custom_fields' not in update_dto:
                        update_dto['custom_fields'] = []
                    if 'file_fields' not in update_dto:
                        update_dto['file_fields'] = {}
                    dtos.append(update_dto)
            
            model['dtos'] = dtos
        
        # Process each DTO
        for dto in model.get('dtos', []):
            # Set defaults
            if 'enabled' not in dto:
                dto['enabled'] = True
            if 'custom_fields' not in dto:
                dto['custom_fields'] = []
            if 'file_fields' not in dto:
                dto['file_fields'] = {}
            if 'type' not in dto:
                dto['type'] = 'create'
            if 'partial' not in dto and dto['type'] == 'update':
                dto['partial'] = True
            
            # Auto-detect file fields if not specified
            for field_name in dto.get('fields', []):
                if field_name not in dto['file_fields']:
                    field = self.get_field_by_name(model, field_name)
                    if field:
                        json_name = field.get('json', field_name.lower())
                        # Auto-detect media fields
                        if any(keyword in json_name for keyword in ['image', 'photo', 'avatar', 'file', 'document', 'video', 'audio', 'media']):
                            # Default to string (URL), user can override to 'file'
                            dto['file_fields'][field_name] = 'string'
        
        # Detect if any DTO needs multipart import
        model['has_file_uploads'] = any(
            'file' in dto.get('file_fields', {}).values()
            for dto in model.get('dtos', [])
        )
        
        return model
    
    def _auto_fields_from_model(self, model: Dict[str, Any], include_all: bool = False) -> List[Dict[str, Any]]:
        """Build response field list from model fields (skipping sensitive), with timestamps"""
        fields = []
        for field in model.get('fields', []):
            field_name = field['name']
            field_type = field.get('type', 'string')
            json_name = field.get('json', field_name.lower())
            if json_name == '-' or 'password' in field_name.lower():
                continue
            fields.append({
                'name': field_name,
                'type': field_type,
                'json_name': json_name,
                'from_field': field_name,
                'omitempty': field_type.startswith('*'),
            })
        if model.get('timestamps'):
            fields.extend([
                {'name': 'CreatedAt', 'type': 'time.Time', 'json_name': 'created_at', 'from_field': 'CreatedAt', 'omitempty': False},
                {'name': 'UpdatedAt', 'type': 'time.Time', 'json_name': 'updated_at', 'from_field': 'UpdatedAt', 'omitempty': False},
            ])
        if include_all and self.is_soft_delete_enabled(model):
            fields.append({
                'name': 'DeletedAt',
                'type': '*time.Time',
                'json_name': 'deleted_at',
                'from_field': 'DeletedAt',
                'omitempty': True,
            })
        return fields

    def _enrich_include_relations(self, model: Dict[str, Any], include_relations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enrich each include_relations entry with rel_type (list/single) from model relations"""
        for rel in include_relations:
            if 'rel_type' not in rel:
                rel_type = 'single'
                for r in model.get('relations', []):
                    if r['name'] == rel['name']:
                        rel_type = 'list' if r.get('type') in ['has_many', 'many_to_many'] else 'single'
                        break
                rel['rel_type'] = rel_type
        return include_relations

    def process_responses(self, model: Dict[str, Any]) -> Dict[str, Any]:
        """Process response configurations"""
        
        # Process List Response
        existing_list = model.get('list_response', {})
        list_enabled = existing_list.get('enabled', True) if isinstance(existing_list, dict) else bool(existing_list)
        if list_enabled:
            if 'fields' not in existing_list or not existing_list.get('fields'):
                existing_list['fields'] = self._auto_fields_from_model(model, include_all=False)
            if 'include_relations' not in existing_list:
                existing_list['include_relations'] = []
            existing_list['include_relations'] = self._enrich_include_relations(
                model, existing_list['include_relations']
            )
            existing_list['enabled'] = True
            model['list_response'] = existing_list
        
        # Process Detail Response
        existing_detail = model.get('detail_response', {})
        detail_enabled = existing_detail.get('enabled', True) if isinstance(existing_detail, dict) else bool(existing_detail)
        if detail_enabled:
            if 'fields' not in existing_detail or not existing_detail.get('fields'):
                existing_detail['fields'] = self._auto_fields_from_model(model, include_all=True)
            if 'include_relations' not in existing_detail:
                existing_detail['include_relations'] = []
            existing_detail['include_relations'] = self._enrich_include_relations(
                model, existing_detail['include_relations']
            )
            existing_detail['enabled'] = True
            model['detail_response'] = existing_detail
            
        return model
    
    def get_field_by_name(self, model: Dict[str, Any], field_name: str) -> Dict[str, Any]:
        """Get field configuration by name"""
        for field in model.get('fields', []):
            if field['name'] == field_name:
                return field
        return None
    def to_snake_case(self, text: str) -> str:
        """Convert CamelCase to snake_case"""
        import re
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', text)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    def get_model_by_name(self, model_name: str) -> Dict[str, Any]:
        """Find a raw model config from the global config by model name"""
        for m in self.config.get('models', []):
            if m['name'] == model_name:
                return m
        return None

    def get_relation_info(self, model: Dict[str, Any], relation_name: str) -> Dict[str, Any]:
        """Return the relation dict and the related model's raw config for a given relation name"""
        for rel in model.get('relations', []):
            if rel['name'] == relation_name:
                related_model = self.get_model_by_name(rel['model'])
                return rel, related_model
        return None, None

    def build_typed_fields_from_model(self, related_model: Dict[str, Any],
                                      select_fields: List[str]) -> List[Dict[str, Any]]:
        """
        Build a list of typed field dicts for a nested struct.
        For each name in select_fields, look up the actual Go type in related_model.
        Falls back to 'string' if the field or model cannot be found.
        Handles snake_case sql names → PascalCase Go names.
        """
        if related_model is None:
            return [{'go_name': f.replace('_', ' ').title().replace(' ', ''),
                     'type': 'string',
                     'json_name': f.lower(),
                     'from_field': f.replace('_', ' ').title().replace(' ', ''),
                     'omitempty': False}
                    for f in select_fields]

        result = []
        for sf in select_fields:
            # sql name → Go PascalCase name
            go_name = sf.replace('_', ' ').title().replace(' ', '')
            json_name = sf.lower()

            # Special timestamp fields
            if sf.lower() in ['created_at', 'updated_at', 'deleted_at', 'published_at']:
                go_type = '*time.Time' if sf.lower() in ['deleted_at', 'published_at'] else 'time.Time'
                result.append({'go_name': go_name, 'type': go_type, 'json_name': json_name,
                                'from_field': go_name, 'omitempty': go_type.startswith('*')})
                continue

            # Look up in related model fields
            field_cfg = self.get_field_by_name(related_model, go_name)
            if field_cfg:
                ft = field_cfg.get('type', 'string')
                result.append({'go_name': go_name, 'type': ft, 'json_name': json_name,
                                'from_field': go_name, 'omitempty': ft.startswith('*')})
            else:
                # 'id' → 'ID' special case
                if sf.lower() == 'id':
                    result.append({'go_name': 'ID', 'type': 'uint', 'json_name': 'id',
                                   'from_field': 'ID', 'omitempty': False})
                else:
                    result.append({'go_name': go_name, 'type': 'string', 'json_name': json_name,
                                   'from_field': go_name, 'omitempty': False})
        return result
    
    def generate_model(self, model: Dict[str, Any]) -> str:
        """
        Generate Go model code from configuration
        
        Args:
            model: Processed model configuration
            
        Returns:
            Generated Go code as string
        """
        user_model_name = self.config.get('project', {}).get('user_model_name', 'User')
        if model.get('name') == user_model_name:
            template = self.env.get_template('internal/domain/user_model.go.j2')
        else:
            template = self.env.get_template('internal/domain/model.go.j2')
        return template.render(model=model)
    
    def generate_dto(self, model: Dict[str, Any]) -> str:
        """
        Generate Go DTO code from configuration
        
        Args:
            model: Processed model configuration
            
        Returns:
            Generated Go code as string
        """
        template = self.env.get_template('pkg/dto/dto.go.j2')
        return template.render(model=model)
    
    def _swagger_type(self, go_type: str) -> str:
        """Map Go type to swagger type string"""
        mapping = {
            'string': 'string', 'bool': 'boolean',
            'int': 'integer', 'int64': 'integer', 'uint': 'integer',
            'float64': 'number', 'float32': 'number',
            'time.Time': 'string', '*time.Time': 'string',
            '*string': 'string', '*bool': 'boolean',
            '*int': 'integer', '*uint': 'integer',
        }
        return mapping.get(go_type, 'string')

    def _swagger_format(self, go_type: str) -> str:
        mapping = {
            'int64': 'int64', 'uint': 'int64', 'int': 'int32',
            'float64': 'double', 'float32': 'float',
            'time.Time': 'date-time', '*time.Time': 'date-time',
        }
        return mapping.get(go_type, '')

    def process_controller(self, model: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a controller_context dict from model config.
        Called AFTER process_model so DTOs and responses are already resolved.
        """
        ctrl_cfg = model.get('controller', {})
        if not ctrl_cfg or not ctrl_cfg.get('enabled', True):
            return None

        name = model['name']
        base_path = ctrl_cfg.get('base_path', f'/api/{name.lower()}s')
        middleware = ctrl_cfg.get('middleware', [])
        tag = ctrl_cfg.get('tag', name)
        module_path = model.get('_module_path', 'github.com/yourorg/yourproject')
        rate_limit = ctrl_cfg.get('rate_limit', {})
        # ---- helper: resolve DTO name ----
        def resolve_dto(dto_hint: str, op_type: str) -> str:
            """Find DTO struct name from hint or auto-detect"""
            if dto_hint:
                # check if it's a full name already or just a type hint (create/update)
                for dto in model.get('dtos', []):
                    if dto['name'] == dto_hint or dto.get('type') == dto_hint:
                        return dto['name']
                return dto_hint  # user gave exact name
            # auto-detect by type
            for dto in model.get('dtos', []):
                if dto.get('type') == op_type:
                    return dto['name']
            return f'{op_type.capitalize()}{name}Request'

        # ---- helper: detect file uploads from DTO ----
        # Helper: get file uploads from DTO
        def dto_file_uploads(dto_name: str) -> List[Dict]:
            if not dto_name:
                return []
            
            # Find DTO config
            dto_config = None
            for dto in model.get('dtos', []):
                if dto['name'] == dto_name:
                    dto_config = dto
                    break
            
            if not dto_config or not dto_config.get('file_fields'):
                return []
        
            # Get model-level defaults
            model_defaults = model.get('file_upload_defaults', {})
            
            file_uploads = []
            for field_name, field_type in dto_config['file_fields'].items():
                if field_type != 'file':
                    continue
            
                # Check DTO-level settings
                dto_file_settings = dto_config.get('file_upload_settings', {}).get(field_name, {})
                
                file_cfg = {
                    'field': field_name,
                    'form_field': dto_file_settings.get('form_field', 
                        self.to_snake_case(field_name)),
                    'storage_path': dto_file_settings.get('storage_path',
                        model_defaults.get('storage_path', f'uploads/{name.lower()}')),
                    'max_size_mb': dto_file_settings.get('max_size_mb',
                        model_defaults.get('max_size_mb', 5)),
                    'allowed_types': dto_file_settings.get('allowed_types',
                        model_defaults.get('allowed_types', [])),
                    'required': dto_file_settings.get('required',
                        model_defaults.get('required', False)),
                }
                file_uploads.append(file_cfg)
        
            return file_uploads
    
        def process_file_uploads(endpoint_cfg: Dict, dto_name: str) -> List[Dict]:
            # Explicit file_uploads take precedence
            if 'file_uploads' in endpoint_cfg:
                file_uploads = []
                for f in endpoint_cfg['file_uploads']:
                    file_cfg = {
                        'field': f['field'],
                        'form_field': f.get('form_field', self.to_snake_case(f['field'])),
                        'storage_path': f.get('storage_path', f'uploads/{name.lower()}'),
                        'max_size_mb': f.get('max_size_mb', 5),
                        'allowed_types': f.get('allowed_types', []),
                        'required': f.get('required', False),
                    }
                    file_uploads.append(file_cfg)
                return file_uploads
            
            # Auto-detect from DTO
            return dto_file_uploads(dto_name)
        # ---- helper: resolve response struct name ----
        def resolve_response(resp_hint: str, default_type: str) -> Dict:
            """Returns {'struct': 'XDetailResponse', 'pkg': 'response', 'is_list': False}"""
            if resp_hint == 'list' or default_type == 'list':
                return {'struct': f'{name}ListResponse', 'pkg': 'response', 'is_list': True,
                        'item_struct': f'{name}ListItem', 'converter': f'To{name}ListItems'}
            if resp_hint == 'detail' or default_type == 'detail':
                return {'struct': f'{name}DetailResponse', 'pkg': 'response', 'is_list': False,
                        'converter': f'To{name}DetailResponse'}
            if resp_hint == 'success' or resp_hint is None:
                return {'struct': 'SuccessResponse', 'pkg': 'response', 'is_list': False,
                        'converter': None}
            # custom: could be a custom getter response name
            return {'struct': resp_hint, 'pkg': 'response', 'is_list': False,
                    'converter': f'To{resp_hint}'}

        # ---- helper: build query params for swagger from getter config ----
        def build_query_params(source: Dict, explicit_params: List[Dict]) -> List[Dict]:
            """
            Merge explicit query_params with auto-derived ones from getter filters/sort_by.
            Explicit params take precedence. Only include params that map to real getter options.
            """
            # Build set of valid filter/sort names from the getter
            valid_filters = set(source.get('filters', []))
            valid_sorts = set(source.get('sort_by', []))

            # Start with explicit params
            result = []
            explicit_names = set()
            for p in explicit_params:
                result.append(self._normalize_query_param(p))
                explicit_names.add(p['name'])

            # Auto-add filters not already explicit
            for f in source.get('filters', []):
                if f in explicit_names:
                    continue
                if f == 'search':
                    result.append({'name': 'search', 'type': 'string', 'swagger_type': 'string',
                                   'go_parse': 'string', 'default': '', 'enum_values': []})
                elif f.endswith('_id'):
                    result.append({'name': f, 'type': 'uint', 'swagger_type': 'integer',
                                   'go_parse': 'int', 'default': 0, 'enum_values': []})
                elif f in ('status', 'role'):
                    result.append({'name': f, 'type': 'string', 'swagger_type': 'string',
                                   'go_parse': 'string', 'default': '', 'enum_values': []})
                else:
                    result.append({'name': f, 'type': 'string', 'swagger_type': 'string',
                                   'go_parse': 'string', 'default': '', 'enum_values': []})

            # Auto-add sort params if getter has sort_by
            if valid_sorts and 'sort_by' not in explicit_names:
                default_sort = source.get('default_sort_field', 'created_at')
                result.append({'name': 'sort_by', 'type': 'enum', 'swagger_type': 'string',
                               'go_parse': 'string', 'default': default_sort,
                               'enum_values': sorted(valid_sorts)})
            if valid_sorts and 'sort_order' not in explicit_names:
                result.append({'name': 'sort_order', 'type': 'enum', 'swagger_type': 'string',
                               'go_parse': 'string', 'default': source.get('default_sort_order', 'desc'),
                               'enum_values': ['asc', 'desc']})

            return result

        # ================================================================
        # Shared helpers for params + ownership + response
        # ================================================================

        def normalize_param(p: Dict) -> Dict:
            """
            Normalize a param definition into a full dict with:
              name, type, go_type, source (path|claim|query|body),
              var_name, cast_expr, swagger_type, required
            source=claim  → read from c.Locals("user_id").(uint)
            source=path   → c.Params / c.ParamsInt
            source=query  → c.Query / c.QueryInt
            """
            pname   = p['name']
            ptype   = p.get('type', 'string')
            source  = p.get('source', 'path')
            var     = p.get('var_name', pname)   # Go variable name

            go_type = {
                'uint': 'uint', 'int': 'int', 'int64': 'int64',
                'string': 'string', 'bool': 'bool',
            }.get(ptype, 'string')

            swagger_type = {
                'uint': 'integer', 'int': 'integer', 'int64': 'integer',
                'string': 'string', 'bool': 'boolean',
            }.get(ptype, 'string')

            # How to pass this param to the repo call
            if go_type in ('uint', 'int', 'int64'):
                call_expr = f'uint({var})' if go_type != 'uint' else var
            else:
                call_expr = var

            return {
                'name':         pname,
                'type':         ptype,
                'go_type':      go_type,
                'source':       source,       # path | claim | query
                'var_name':     var,
                'call_expr':    call_expr,    # expression used in the repo call
                'swagger_type': swagger_type,
                'required':     p.get('required', True),
            }

        def default_params_for_op(op_cfg: Dict, op_type: str) -> List[Dict]:
            """
            Build the default params list when user hasn't specified params.
            create  → no params (no path segment)
            get/update/delete → [{ name:id, type:uint, source:path }]
            """
            raw = op_cfg.get('params')
            if raw is not None:
                return [normalize_param(p) for p in raw]
            if op_type == 'create':
                return []
            # default: single :id path param
            return [normalize_param({'name': 'id', 'type': 'uint', 'source': 'path'})]

        def build_path_from_params(params: List[Dict]) -> str:
            """
            Build the route path segment from path params.
            e.g. params [{name:user_id,source:claim},{name:id,source:path}]
            → only path params appear in URL: /:id
            Uses base_path as prefix.
            """
            path_segs = [f':{p["name"]}' for p in params if p['source'] == 'path']
            suffix = '/' + '/'.join(path_segs) if path_segs else ''
            return f'{base_path}{suffix}'

        def resolve_response_full(resp_cfg) -> Dict:
            """
            resp_cfg can be:
              'detail'                         → auto name
              'list'                           → auto name
              'success'                        → SuccessResponse
              {'struct': 'X', 'converter': 'ToX'}   → explicit
            """
            if resp_cfg is None or resp_cfg == 'success':
                return {'struct': 'SuccessResponse', 'converter': None}
            if isinstance(resp_cfg, dict):
                struct    = resp_cfg.get('struct', f'{name}DetailResponse')
                converter = resp_cfg.get('converter', f'To{struct}')
                return {'struct': struct, 'converter': converter}
            # string shorthand
            if resp_cfg == 'list':
                return {'struct': f'{name}ListResponse',
                        'converter': f'To{name}ListItems'}
            if resp_cfg == 'detail':
                return {'struct': f'{name}DetailResponse',
                        'converter': f'To{name}DetailResponse'}
            # user gave a raw struct name
            return {'struct': resp_cfg, 'converter': f'To{resp_cfg}'}

        def resolve_ownership(own_cfg: Dict, params: List[Dict]) -> Dict:
            """
            own_cfg:
              enabled: true
              verify: param        # repo method already received the owner param → just check err
                   OR
              verify: field        # fetch first, compare field after
              field: author_id     # field to compare (only for verify:field)
              repo_method: GetByUserAndID  # (optional) repo method to use for verify:param
            Returns enriched dict the template can use directly.
            """
            if not own_cfg or not own_cfg.get('enabled', False):
                return {'enabled': False}

            verify = own_cfg.get('verify', 'field')
            field  = own_cfg.get('field', 'UserID')
            go_field = field.replace('_id', 'ID').replace('_', ' ').title().replace(' ', '')
            repo_method_name = own_cfg.get('repo_method', '')

            # find which param carries the owner id (source=claim usually)
            owner_param = next(
                (p for p in params if p['source'] == 'claim'), None
            )

            result = {
                'enabled':     True,
                'verify':      verify,      # 'param' | 'field'
                'field':       field,
                'go_field':    go_field,
                'owner_param': owner_param, # the param dict for the claim/JWT param
            }

            # If verify=param and repo_method is specified, build the method call args
            if verify == 'param' and repo_method_name:
                result['repo_method'] = repo_method_name
                # Build args: collect values from params
                args = []
                for p in params:
                    args.append(p['var_name'])
                result['repo_method_args_str'] = ', '.join(args)

            return result

        def resolve_repo_method(op_cfg: Dict, op_type: str, params: List[Dict]) -> Dict:
            """
            Resolve which repository method to call and build its call args.
            op_cfg may have:
              repo_method: GetPostByUserAndID
              fetch_method: GetPostByUserAndID   (alias, used for get/update/delete pre-fetch)
            """
            # explicit
            explicit = op_cfg.get('repo_method') or op_cfg.get('fetch_method')
            if explicit:
                method = explicit
            else:
                defaults = {
                    'create': 'Create',
                    'get':    'GetByID',
                    'update': 'Update',
                    'delete': 'Delete',
                }
                method = defaults.get(op_type, 'GetByID')

            # build arg list: claim params first, then path params
            args = [p['call_expr'] for p in params]

            return {'method': method, 'args': args, 'args_str': ', '.join(args)}

        # ================================================================
        # CRUD endpoints
        # ================================================================
        crud_settings = ctrl_cfg.get('crud_settings', {})
        endpoints = []

        # --- CREATE ---
        create_cfg = crud_settings.get('create', {})
        if create_cfg.get('enabled', False):
            dto_name  = resolve_dto(create_cfg.get('dto', ''), 'create')
            # file_ups  = dto_file_uploads(dto_name)
            file_ups = process_file_uploads(create_cfg, dto_name)

            params    = default_params_for_op(create_cfg, 'create')
            resp      = resolve_response_full(create_cfg.get('response', 'detail'))
            ownership = resolve_ownership(create_cfg.get('ownership', {}), params)
            auto_fields = create_cfg.get('auto_fields', [])
            c_rate_limit = create_cfg.get('rate_limit', rate_limit)
            # needs_claim: ownership OR any auto_field with source=context
            needs_claim = ownership['enabled'] or any(
                af.get('source') == 'context' for af in auto_fields
            )
            endpoints.append({
                'type':           'create',
                'method':         create_cfg.get('method', 'POST').upper(),
                'path':           base_path,
                'func_name':      f'Create{name}',
                'model':          name,
                'tag':            tag,
                'middleware':     create_cfg.get('middleware', middleware),
                'dto_name':       dto_name,
                'rate_limit':     c_rate_limit,
                'file_uploads':   file_ups,
                'has_file_uploads': bool(file_ups),
                'response':       resp,
                'params':         params,
                'ownership':      ownership,
                'auto_fields':    auto_fields,
                'needs_claim':    needs_claim,
                'validation':     create_cfg.get('validation', {'use_validator': True}),
            })

        # --- GET ---
        get_cfg = crud_settings.get('get', {})
        if get_cfg.get('enabled', False):
            params      = default_params_for_op(get_cfg, 'get')
            path        = build_path_from_params(params)
            resp        = resolve_response_full(get_cfg.get('response', 'detail'))
            ownership   = resolve_ownership(get_cfg.get('ownership', {}), params)
            repo_method = resolve_repo_method(get_cfg, 'get', params)
            needs_claim = ownership['enabled'] or any(p['source'] == 'claim' for p in params)
            g_rate_limit = get_cfg.get('rate_limit', rate_limit)
            endpoints.append({
                'type':         'get',
                'method':       'GET',
                'path':         path,
                'rate_limit':     g_rate_limit,
                'func_name':    f'Get{name}ByID',
                'model':        name,
                'tag':          tag,
                'middleware':   get_cfg.get('middleware', middleware),
                'response':     resp,
                'params':       params,
                'ownership':    ownership,
                'repo_method':  repo_method,
                'needs_claim':  needs_claim,
            })

        # --- UPDATE ---
        update_cfg = crud_settings.get('update', {})
        if update_cfg.get('enabled', False):
            dto_name    = resolve_dto(update_cfg.get('dto', ''), 'update')
            # file_ups    = dto_file_uploads(dto_name)
            file_ups = process_file_uploads(update_cfg, dto_name)
            
            params      = default_params_for_op(update_cfg, 'update')
            path        = build_path_from_params(params)
            resp        = resolve_response_full(update_cfg.get('response', 'detail'))
            ownership   = resolve_ownership(update_cfg.get('ownership', {}), params)
            repo_method = resolve_repo_method(update_cfg, 'get', params)  # fetch method
            u_rate_limit = update_cfg.get('rate_limit', rate_limit)
            needs_claim = ownership['enabled'] or any(p['source'] == 'claim' for p in params)
            endpoints.append({
                'type':           'update',
                'method':         update_cfg.get('method', 'PATCH').upper(),
                'path':           path,
                'func_name':      f'Update{name}',
                'model':          name,
                'tag':            tag,
                'rate_limit':     u_rate_limit,
                'middleware':     update_cfg.get('middleware', middleware),
                'dto_name':       dto_name,
                'file_uploads':   file_ups,
                'has_file_uploads': bool(file_ups),
                'response':       resp,
                'params':         params,
                'ownership':      ownership,
                'repo_method':    repo_method,
                'needs_claim':    needs_claim,
                'validation':     update_cfg.get('validation', {'use_validator': True}),
            })

        # --- DELETE ---
        delete_cfg = crud_settings.get('delete', {})
        if delete_cfg.get('enabled', False):
            params      = default_params_for_op(delete_cfg, 'delete')
            path        = build_path_from_params(params)
            ownership   = resolve_ownership(delete_cfg.get('ownership', {}), params)
            repo_method = resolve_repo_method(delete_cfg, 'get', params)  # fetch for ownership
            needs_claim = ownership['enabled'] or any(p['source'] == 'claim' for p in params)
            d_rate_limit = delete_cfg.get('rate_limit', rate_limit)
            endpoints.append({
                'type':        'delete',
                'method':      'DELETE',
                'path':        path,
                'func_name':   f'Delete{name}',
                'rate_limit':     d_rate_limit,
                'model':       name,
                'tag':         tag,
                'middleware':  delete_cfg.get('middleware', middleware),
                'params':      params,
                'ownership':   ownership,
                'repo_method': repo_method,
                'needs_claim': needs_claim,
                'hard_delete': delete_cfg.get('hard_delete', False),
            })

        # --- BATCH DELETE ---
        batch_del_cfg = crud_settings.get('batch_delete', {})
        if batch_del_cfg.get('enabled', False):
            own_enabled = batch_del_cfg.get('ownership_check', False)
            b_rate_limit = batch_del_cfg.get('rate_limit', rate_limit)
            endpoints.append({
                'type':      'batch_delete',
                'method':    'DELETE',
                'path':      f'{base_path}/batch',
                'func_name': f'BatchDelete{name}',
                'model':     name,
                'rate_limit':     b_rate_limit,
                'tag':       tag,
                'middleware': batch_del_cfg.get('middleware', middleware),
                'ownership': {'enabled': own_enabled,
                              'field':   batch_del_cfg.get('ownership_field', 'user_id'),
                              'go_field': batch_del_cfg.get('ownership_field', 'user_id')
                                          .replace('_', ' ').title().replace(' ', ''),
                              'verify':  'field'},
                'needs_claim': own_enabled,
                'hard_delete': batch_del_cfg.get('hard_delete', False),
            })

        # ================================================================
        # Custom getter endpoints
        # ================================================================
        getter_endpoints = []
        for getter in model.get('custom_getters', []):
            g_ctrl = getter.get('controller', {})
            if not g_ctrl.get('enabled', False):
                continue

            g_name = getter['name']
            g_path = g_ctrl.get('path', f'{base_path}/{g_name.lower()}')
            g_method = g_ctrl.get('method', 'GET').upper()
            g_middleware = g_ctrl.get('middleware', middleware)
            g_ownership = g_ctrl.get('ownership', {'enabled': False})
            g_explicit_params = g_ctrl.get('query_params', [])

            # Build query params — only from what this getter actually supports
            g_query_params = build_query_params(getter, g_explicit_params)
            # Add pagination if getter has it
            has_pagination = bool(getter.get('pagination'))
            g_rate_limit = g_ctrl.get('rate_limit', rate_limit)

            # Resolve response
            g_resp_hint = g_ctrl.get('response', getter.get('response_type', 'list'))
            if getter.get('custom_response'):
                cr = getter['custom_response']
                cr_name = cr['name']
                if getter.get('unique'):
                    g_resp = {'struct': cr_name, 'pkg': 'response', 'is_list': False,
                              'converter': f'To{cr_name}'}
                else:
                    g_resp = {'struct': f'[]response.{cr_name}', 'pkg': 'response', 'is_list': True,
                              'item_struct': cr_name, 'converter': f'To{cr_name}List',
                              'list_response_struct': None}
            elif g_resp_hint in ('list', 'detail'):
                g_resp = resolve_response(g_resp_hint, g_resp_hint)
            else:
                g_resp = resolve_response(None, 'list')

            # Path params from getter.fields
            path_params = [
                {'name': f.lower(), 'type': getter['field_types'][i] if i < len(getter.get('field_types', [])) else 'string'}
                for i, f in enumerate(getter.get('fields', []))
            ]

            # func name
            func_name = g_ctrl.get('func_name', g_name)

            getter_endpoints.append({
                'type': 'custom_getter',
                'method': g_method,
                'path': g_path,
                'func_name': func_name,
                'rate_limit':     g_rate_limit,
                'getter_name': g_name,
                'model': name,
                'tag': g_ctrl.get('tag', tag),
                'middleware': g_middleware,
                'query_params': g_query_params,
                'path_params': path_params,
                'has_pagination': has_pagination,
                'response': g_resp,
                'ownership': g_ownership,
                'unique': getter.get('unique', False),
                'description': g_ctrl.get('description', ''),
                'options_type': f'{g_name}Options' if (getter.get('filters') or getter.get('sort_by') or has_pagination) else None,
            })

        # ================================================================
        # Detect which imports are needed
        # ================================================================
        needs_time = any(
            any(p.get('type') == 'date' for p in ep.get('query_params', []))
            for ep in getter_endpoints
        )
        needs_uuid = any(
            any(af.get('generator') == 'uuid' for af in ep.get('auto_fields', []))
            for ep in endpoints
        )
        needs_strings = any(ep.get('has_file_uploads') for ep in endpoints)
        needs_strconv = any(ep['type'] == 'batch_delete' for ep in endpoints)
        needs_validator = any(ep.get('validation', {}).get('use_validator') for ep in endpoints)

        return {
            'model': name,
            'base_path': base_path,
            'tag': tag,
            'middleware': middleware,
            'module_path': module_path,
            'endpoints': endpoints,
            'getter_endpoints': getter_endpoints,
            'needs_time': needs_time,
            'rate_limit': rate_limit,
            'needs_uuid': needs_uuid,
            'needs_strings': needs_strings,
            'needs_strconv': needs_strconv,
            'needs_validator': needs_validator,
            'repo_var': f'{name[0].lower()}{name[1:]}Repo',
            'repo_type': f'repository.{name}Repository',
            'repo_constructor': f'repository.New{name}Repository',
        }

    def _fields_for_update(self, model: Dict, dto_name: str) -> List[Dict]:
        """Get typed field list for update diff logic from the DTO definition"""
        fields = []
        for dto in model.get('dtos', []):
            if dto['name'] == dto_name:
                for field_name in dto.get('fields', []):
                    field_cfg = self.get_field_by_name(model, field_name)
                    if field_cfg:
                        ft = field_cfg.get('type', 'string')
                        fields.append({
                            'name': field_name,
                            'type': ft,
                            'is_pointer': ft.startswith('*'),
                            'db_column': field_cfg.get('json', field_name.lower()),
                        })
        return fields

    def _normalize_query_param(self, p: Dict) -> Dict:
        """Normalize a query_param dict with swagger_type and go_parse fields"""
        t = p.get('type', 'string')
        swagger_type = {'int': 'integer', 'uint': 'integer', 'bool': 'boolean',
                        'enum': 'string', 'date': 'string', 'float': 'number'}.get(t, 'string')
        go_parse = {'int': 'int', 'uint': 'int', 'bool': 'bool',
                    'date': 'date', 'enum': 'string', 'float': 'float'}.get(t, 'string')
        return {
            'name': p['name'],
            'type': t,
            'swagger_type': swagger_type,
            'go_parse': go_parse,
            'default': p.get('default', ''),
            'enum_values': p.get('values', []),
            'format': p.get('format', ''),
            'required': p.get('required', False),
        }

    def generate_controller(self, ctrl_ctx: Dict[str, Any]) -> str:
        template = self.env.get_template('internal/api/handlers/handler.go.j2')
        return template.render(ctrl=ctrl_ctx, config=self.config)

    def generate_response(self, model: Dict[str, Any]) -> str:
        template = self.env.get_template('pkg/response/response.go.j2')
        return template.render(model=model, config=self.config, module_path=self.config.get('project', {}).get('module', ''))
    
    def generate_repository(self, model: Dict[str, Any], module_path: str) -> str:
        template = self.env.get_template('internal/repository/repository.go.j2')
        return template.render(model=model, module_path=module_path, config=self.config)
    def generate_web_handler(self, handler_ctx: Dict[str, Any]) -> str:
        """Generate web handler code from context"""
        template = self.env.get_template('internal/web/dashboard/web_handler.go.j2')
        return template.render(handler=handler_ctx, module_path=handler_ctx['module_path'], config=self.config)

    def generate_web_templates(self, model: Dict[str, Any], handler_ctx: Dict[str, Any]):
        """Generate HTML and JS templates for the web handler"""
        model_name_lower = model['name'].lower()
        output_path = Path(self.output_dir)
        
        # Determine DTO fields for the form
        # We try to find a 'create' or 'update' DTO
        dto_name = ""
        for ep in handler_ctx['endpoints']:
            if ep['type'] in ['create', 'update'] and ep.get('dto_name'):
                dto_name = ep['dto_name']
                break
        
        # If no DTO found, use all fields (fallback)
        dto_fields = []
        if dto_name:
            # We need to find the DTO in the model's dtos list
            for dto in model.get('dtos', []):
                if dto['name'] == dto_name:
                    for f_name in dto.get('fields', []):
                        f_cfg = self.get_field_by_name(model, f_name)
                        if f_cfg:
                            dto_fields.append(f_cfg)
                    # Add file fields if any
                    for f_name, f_type in dto.get('file_fields', {}).items():
                        if f_type == 'file':
                            f_cfg = self.get_field_by_name(model, f_name)
                            if f_cfg:
                                f_copy = f_cfg.copy()
                                f_copy['type'] = 'file'
                                dto_fields.append(f_copy)
                    break
        
        # Fallback if no DTO fields found
        if not dto_fields:
            dto_fields = [f for f in model.get('fields', []) if f['name'] not in ['ID', 'CreatedAt', 'UpdatedAt', 'DeletedAt']]

        # Context for rendering templates
        render_ctx = {
            'model': model,
            'handler': handler_ctx,
            'dto_fields': dto_fields,
            'config': self.config
        }
        shared_dir = output_path / 'html' / 'templates' / 'shared'
        shared_dir.mkdir(parents=True, exist_ok=True)
        if not self.is_share_generate:
            if handler_ctx['crud_settings'].get('list', {}).get('enabled', False):
                table_loading_html = self.web_env.get_template('public/templates/crud/partials/table-loading.html.j2').render(**render_ctx)
                table_loading_path = shared_dir / 'table-loading.html'
                with open(table_loading_path, 'w') as f:
                    f.write(table_loading_html)

            preloader_html = self.web_env.get_template('public/templates/shared/preloader.html.j2').render(**render_ctx)
            preloader_path = shared_dir / 'preloader.html'
            with open(preloader_path, 'w') as f:
                f.write(preloader_html)

            overlay_html = self.web_env.get_template('public/templates/shared/overlay.html.j2').render(**render_ctx)
            overlay_path = shared_dir / 'overlay.html'
            with open(overlay_path, 'w') as f:
                f.write(overlay_html)

            
            # header_html = self.web_env.get_template('public/templates/shared/header.html.j2').render(**render_ctx)
            # header_path = shared_dir / 'header.html'
            # with open(header_path, 'w') as f:
            #     f.write(header_html)

            # sidebar_html = self.web_env.get_template('public/templates/shared/sidebar.html.j2').render(**render_ctx)
            # sidebar_path = shared_dir / 'sidebar.html'
            # with open(sidebar_path, 'w') as f:
            #     f.write(sidebar_html)

            self.is_share_generate=True

       
        # 2. Form Page (Create/Edit)
        # We render it twice: once for create, once for edit (sharing the same j2)
        if handler_ctx['crud_settings'].get('create_page', {}).get('enabled', False):
            print("Rendering form edit=False"); create_html = self.web_env.get_template('public/templates/crud/form.html.j2').render(edit=False, **render_ctx)
            create_path = output_path / 'html' / 'templates' / handler_ctx['template_base'] / 'create.html'
            create_path.parent.mkdir(parents=True, exist_ok=True)
            with open(create_path, 'w') as f:
                f.write(create_html)
        if handler_ctx['crud_settings'].get('edit_page', {}).get('enabled', False):
            print("Rendering form edit=True"); edit_html = self.web_env.get_template('public/templates/crud/form.html.j2').render(edit=True, **render_ctx)
            edit_path = output_path / 'html' / 'templates' / handler_ctx['template_base'] / 'edit.html'
            edit_path.parent.mkdir(parents=True, exist_ok=True)
            with open(edit_path, 'w') as f:
                f.write(edit_html)
            
        # 3. Show Page

        
        # 4a. Additional Partials (filter, table-view, models)
        partials_dir = output_path / 'html' / 'templates' / handler_ctx['template_base'] / 'partials' 
        partials_dir.mkdir(parents=True, exist_ok=True)
        if handler_ctx['crud_settings'].get('get', {}).get('enabled', False):
            try:
                show_html = self.web_env.get_template('public/templates/crud/show.html.j2').render(**render_ctx)
                show_path = partials_dir / 'show.html'
                with open(show_path, 'w') as f:
                    f.write(show_html)
            except Exception as e:
                print(f"Warning: Could not render show template for {model['name']}: {e}")
            try:
                loading_html = self.web_env.get_template('public/templates/crud/partials/details-loading.html.j2').render(**render_ctx)
                with open(partials_dir / f'{model_name_lower}-details-loading.html', 'w') as f:
                    f.write(loading_html)
            except Exception as e:
                print(f"Warning: Could not render details-loading template for {model['name']}: {e}")
         
        # 4. Table Rows Partial
        if handler_ctx['crud_settings'].get('list', {}).get('enabled', False):
             # 1. List Page
            print("Rendering list"); 
            list_html = self.web_env.get_template('public/templates/crud/list.html.j2').render(**render_ctx)
            list_path = output_path / 'html' / 'templates' / handler_ctx['template_base'] / 'index.html'
            list_path.parent.mkdir(parents=True, exist_ok=True)
            with open(list_path, 'w') as f:
                f.write(list_html)
            
            try:
                rows_html = self.web_env.get_template('public/templates/crud/partials/table_rows.html.j2').render(**render_ctx)
                rows_path = partials_dir / f'{model_name_lower}_table_rows.html'
                with open(rows_path, 'w') as f:
                    f.write(rows_html)
            except Exception as e:
                print(f"Warning: Could not render filter template for {model['name']}: {e}")

            try:
                filter_html = self.web_env.get_template('public/templates/crud/partials/filter.html.j2').render(**render_ctx)
                with open(partials_dir / f'{model_name_lower}-filter.html', 'w') as f:
                    f.write(filter_html)
            except Exception as e:
                print(f"Warning: Could not render filter template for {model['name']}: {e}")

            try:
                table_view = self.web_env.get_template('public/templates/crud/partials/table-view.html.j2').render(**render_ctx)
                with open(partials_dir / f'{model_name_lower}-table-view.html', 'w') as f:
                    f.write(table_view)
            except Exception as e:
                print(f"Warning: Could not render table-view template for {model['name']}: {e}")

            try:
                models_html = self.web_env.get_template('public/templates/crud/partials/models.html.j2').render(**render_ctx)
                with open(partials_dir / f'{model_name_lower}_models.html', 'w') as f:
                    f.write(models_html)
            except Exception as e:
                print(f"Warning: Could not render models template for {model['name']}: {e}")

        # 4b. Shared loading template
       
           
        # 5. CRUD JS
        crud_js = self.web_env.get_template('public/templates/crud/crud.js.j2').render(**render_ctx)
        js_path = output_path / 'html' / 'static' / model_name_lower / 'js' / f"{model_name_lower}.js"
        js_path.parent.mkdir(parents=True, exist_ok=True)
        with open(js_path, 'w') as f:
            f.write(crud_js)
            
        print(f"    ✓ HTML/JS templates generated for {model['name']}")


    def create_directories(self):
        """Create output directories if they don't exist"""
        output_path = Path(self.output_dir)
        models_dir = output_path / 'internal'/'domain'
        dto_dir = output_path /'pkg' / 'dto'
        response_dir = output_path /'pkg'/ 'response'
        repository_dir = output_path / 'internal'/ 'repository'
        controller_dir = output_path /'internal'/ 'api'/ 'handlers'
        handler_dir = output_path / 'internal' / 'web' / 'dashboard'
        
        # HTML and Static directories
        template_dir = output_path / 'html' / 'templates'
        static_dir = output_path / 'html' / 'static'
        
        dirs = [
            models_dir, dto_dir, response_dir, repository_dir, 
            controller_dir, handler_dir, template_dir, static_dir
        ]
        
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
            
        return models_dir, dto_dir, response_dir, repository_dir, controller_dir, handler_dir

    def generate_all(self, module_path: str = "your-module/path", **kwargs):
        """Generate all models, DTOs, responses, repositories, and controllers"""
        models_dir, dto_dir, response_dir, repository_dir, controller_dir, handler_dir = self.create_directories()
        
        # Extract toggles (default to True for backward compatibility if not passed, 
        # but generator.py passes them explicitly)
        do_models = kwargs.get('generate_models', True)
        do_dtos = kwargs.get('generate_dtos', True)
        do_responses = kwargs.get('generate_responses', True)
        do_repos = kwargs.get('generate_repositories', True)
        do_controllers = kwargs.get('generate_controllers', True)
        do_handlers = kwargs.get('generate_handlers', True)

        if 'models' not in self.config:
            print("Error: No models found in configuration")
            return
        
        print(f"Generating {len(self.config['models'])} models...")
        for raw_model in self.config['models']:
            model = self.process_model(raw_model)
            model['_module_path'] = module_path
            model_name = model['name']
            
            if do_models:
                model_code = self.generate_model(model)
                with open(models_dir / f"{model_name.lower()}.go", 'w') as f:
                    f.write(model_code)
                print(f"    ✓ Model generated")
            
            if do_dtos and model.get('dtos') and len(model.get('dtos', [])) > 0:
                dto_code = self.generate_dto(model)
                with open(dto_dir / f"{model_name.lower()}_dto.go", 'w') as f:
                    f.write(dto_code)
                print(f"    ✓ DTO generated")
            
            if do_responses:
                has_custom_getter_response = any(
                    g.get('response_type') == 'custom' and g.get('custom_response')
                    for g in model.get('custom_getters', [])
                )
                if model.get('list_response', {}).get('enabled') or \
                   model.get('detail_response', {}).get('enabled') or \
                   has_custom_getter_response:
                    response_code = self.generate_response(model)
                    with open(response_dir / f"{model_name.lower()}_response.go", 'w') as f:
                        f.write(response_code)
                    print(f"    ✓ Response generated")
            
            if do_repos:
                repo_code = self.generate_repository(model, module_path)
                with open(repository_dir / f"{model_name.lower()}_repository.go", 'w') as f:
                    f.write(repo_code)
                print(f"    ✓ Repository generated")
            
            # Generate controller if configured
            if do_controllers:
                ctrl_ctx = self.process_controller(model)
                if ctrl_ctx:
                    ctrl_ctx['module_path'] = module_path
                    ctrl_code = self.generate_controller(ctrl_ctx)
                    with open(controller_dir / f"{model_name.lower()}_handler.go", 'w') as f:
                        f.write(ctrl_code)
                    print(f"    ✓ Controller generated")

            if do_handlers:
                handler_ctx = self.process_web_handler(model)
                if handler_ctx:
                    handler_ctx['module_path'] = module_path
                    handler_code = self.generate_web_handler(handler_ctx)
                    with open(handler_dir / f"{model_name.lower()}_handler.go", 'w') as f:
                        f.write(handler_code)
                    print(f"    ✓ Web Handler generated")
                    
                    # Generate HTML templates
                    self.generate_web_templates(model, handler_ctx)
        
        print(f"\n✅ Generation complete! Files saved to: {self.output_dir}")

  
def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Generate Go from YAML configuration'
    )
    parser.add_argument(
        '--config',
        type=str,
        required=True,
        help='Path to the YAML configuration file'
    )
    parser.add_argument(
        '--templates',
        type=str,
        default='./tool/templates/',
        help='Directory containing Jinja2 templates (default: ./templates)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='./generated/',
        help='Output directory for generated files (default: ./generated)'
    )
    parser.add_argument(
        '--module',
        type=str,
        default='github.com/yourorg/',
        help='Go module path (e.g., github.com/user/project)'
    )
    
    args = parser.parse_args()
    
    # Validate config file exists
    if not os.path.exists(args.config):
        print(f"Error: Configuration file not found: {args.config}")
        sys.exit(1)
    
    # Validate templates directory exists
    if not os.path.exists(args.templates):
        print(f"Error: Templates directory not found: {args.templates}")
        sys.exit(1)
    
    # Create generator and run
    generator = ModelGenerator(
        config_path=args.config,
        templates_dir=args.templates,
        output_dir=args.output
    )
    
   

    generator.generate_all(module_path=args.module)


if __name__ == '__main__':
    main()