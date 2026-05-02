
import os
import sys
import argparse
import yaml
import re
from jinja2 import Environment, FileSystemLoader


def _make_env(template_dir: str, is_web: bool = False) -> Environment:
    kwargs = {}
    if is_web:
        kwargs = {
            'block_start_string': '[%',
            'block_end_string': '%]',
            'variable_start_string': '[[',
            'variable_end_string': ']]',
            'comment_start_string': '[#',
            'comment_end_string': '#]',
        }
    env = Environment(loader=FileSystemLoader(template_dir), keep_trailing_newline=True, **kwargs)
    env.filters['snake_case'] = lambda s: s.lower().replace(' ', '_')
    env.filters['camel_case'] = lambda s: ''.join(w.capitalize() for w in s.split('_'))
    env.filters['title']      = lambda s: s.title()
    env.filters['lower']      = lambda s: s.lower()
    env.filters['regex_replace'] = lambda s, pattern, repl: re.sub(pattern, repl, s)
    return env


def render_all(context: dict, templates: list[tuple[str, str]]):
    """Render (template_path, output_path) pairs with the shared context."""
    ctx = {'config': context, **context}
    _env_cache: dict[str, Environment] = {}

    for t_path, o_path in templates:
        if not os.path.exists(t_path):
            print(f"  ⚠️  Template not found (skipping): {t_path}")
            continue
        tmpl_dir  = os.path.dirname(t_path)
        tmpl_name = os.path.basename(t_path)
        is_web = t_path.endswith('.html.j2') or t_path.endswith('.js.j2')
        env_key = f"{tmpl_dir}_{is_web}"
        
        if env_key not in _env_cache:
            _env_cache[env_key] = _make_env(tmpl_dir, is_web)
        try:
            rendered = _env_cache[env_key].get_template(tmpl_name).render(**ctx)
            os.makedirs(os.path.dirname(o_path), exist_ok=True)
            with open(o_path, 'w') as f:
                f.write(rendered)
            print(f"  ✅ {o_path}")
        except Exception as e:
            print(f"  ❌ Error rendering {t_path}: {e}")
            import traceback; traceback.print_exc()
