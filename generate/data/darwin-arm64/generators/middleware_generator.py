"""
Enhanced Middleware Generator
Generates Go middleware code from YAML configuration
"""
import argparse
import yaml
import sys
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, TemplateError
from typing import Dict, Any


class MiddlewareGenerator:
    """
    Generates Go middleware code from YAML configuration using Jinja2 templates
    """

    def __init__(
        self,
        config_path: str,
        template_dir: str = "./templates",
        output_dir: str = "./generated",
    ):
        """
        Initialize the middleware generator

        Args:
            config_path: Path to the YAML configuration file
            template_dir: Directory containing Jinja2 templates
            output_dir: Directory where generated files will be saved
        """
        self.config_path = config_path
        self.template_dir = template_dir
        self.output_dir = output_dir
        self.env = Environment(
            loader=FileSystemLoader(self.template_dir),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def load_config(self) -> Dict[str, Any]:
        """
        Load and parse YAML configuration file

        Returns:
            Parsed configuration dictionary
        """
        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f)
            print(f"✅ Loaded configuration from {self.config_path}")
            return config
        except FileNotFoundError:
            print(f"❌ Configuration file not found: {self.config_path}")
            sys.exit(1)
        except yaml.YAMLError as e:
            print(f"❌ Error parsing YAML: {e}")
            sys.exit(1)

    def transform_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform and validate configuration with sensible defaults

        Args:
            config: Raw configuration dictionary

        Returns:
            Transformed configuration with defaults applied
        """
        # Ensure project section exists
        config.setdefault("project", {})
        config["project"].setdefault("module", "myapp")

        # Ensure session section exists
        config.setdefault("session", {"enabled": False})

        # Ensure features section exists
        config.setdefault("features", {})

        # Ensure middleware section exists
        middleware = config.setdefault("middleware", {})

        # Set defaults for global middleware
        middleware.setdefault("csrf", {"enabled": False})
        middleware.setdefault("compression", {"enabled": False})
        middleware.setdefault("logging", {"enabled": False})
        middleware.setdefault("cors", {"enabled": False})
        middleware.setdefault("rate_limit", {"enabled": False})

        # Set defaults for feature flags
        middleware.setdefault("rbac", {"enabled": False})
        middleware.setdefault("dashboard", {"enabled": False})
        middleware.setdefault("web_auth", {"enabled": False, "fully_verified_enabled": False})

        # Set defaults for context locals
        middleware.setdefault(
            "locals",
            {
                "user_id": "user_id",
                "email": "email",
                "session": "session",
                "verified": "verified",
                "app_id": "app_id",
                "is_admin": "is_admin",
                "role": "role",
            },
        )

        # Ensure definitions and custom lists exist
        middleware.setdefault("definitions", [])
        middleware.setdefault("custom", [])

        # Validate middleware definitions
        self._validate_definitions(middleware.get("definitions", []))

        # Ensure authentication section exists
        config.setdefault("authentication", {"jwt": {"claims": []}})

        return config

    def _validate_definitions(self, definitions: list) -> None:
        """
        Validate middleware definitions for common errors

        Args:
            definitions: List of middleware definitions
        """
        valid_types = [
            "api_key",
            "jwt",
            "session_auth",
            "combined",
            "rate_limit",
            "role_check",
            "ownership_check",
            "header_check",
        ]

        for idx, mw_def in enumerate(definitions):
            # Check for required fields
            if "name" not in mw_def:
                print(f"⚠️  Warning: Middleware definition #{idx + 1} missing 'name' field")
                continue

            if "type" not in mw_def:
                print(f"⚠️  Warning: Middleware '{mw_def['name']}' missing 'type' field")
                continue

            # Validate type
            if mw_def["type"] not in valid_types:
                print(
                    f"⚠️  Warning: Middleware '{mw_def['name']}' has invalid type '{mw_def['type']}'"
                )
                print(f"    Valid types: {', '.join(valid_types)}")

            # Type-specific validations
            if mw_def["type"] == "jwt":
                if "secret_key" not in mw_def:
                    print(f"⚠️  Warning: JWT middleware '{mw_def['name']}' missing 'secret_key' field")

            elif mw_def["type"] == "api_key":
                if "header" not in mw_def:
                    print(
                        f"⚠️  Warning: API key middleware '{mw_def['name']}' missing 'header' field"
                    )
                if "secret_key" not in mw_def:
                    print(
                        f"⚠️  Warning: API key middleware '{mw_def['name']}' missing 'secret_key' field"
                    )

            elif mw_def["type"] == "rate_limit":
                if "max_requests" not in mw_def:
                    print(
                        f"⚠️  Warning: Rate limit middleware '{mw_def['name']}' missing 'max_requests' field"
                    )
                if "window" not in mw_def:
                    print(
                        f"⚠️  Warning: Rate limit middleware '{mw_def['name']}' missing 'window' field"
                    )

            elif mw_def["type"] == "combined":
                if "components" not in mw_def or not mw_def["components"]:
                    print(
                        f"⚠️  Warning: Combined middleware '{mw_def['name']}' missing 'components' list"
                    )

            elif mw_def["type"] == "role_check":
                if "check_is_admin" not in mw_def and "required_role" not in mw_def:
                    print(
                        f"⚠️  Warning: Role check middleware '{mw_def['name']}' needs either 'check_is_admin' or 'required_role'"
                    )

    def generate(self) -> None:
        """
        Generate Go middleware code from configuration
        """
        # Load and transform configuration
        config = self.load_config()
        config = self.transform_config(config)

        # Get template
        try:
            template = self.env.get_template("middleware.go.j2")
        except TemplateError as e:
            print(f"❌ Template error: {e}")
            sys.exit(1)

        # Render template
        try:
            output = template.render(config=config)
        except TemplateError as e:
            print(f"❌ Error rendering template: {e}")
            sys.exit(1)

        # Create output directory
        output_path = Path(self.output_dir) / "internal"/ "api" / "middleware"
        output_path.mkdir(parents=True, exist_ok=True)

        # Write output file
        output_file = output_path / "middleware.go"
        try:
            with open(output_file, "w") as f:
                f.write(output)
            print(f"✅ Generated {output_file}")
            print(f"📊 Generated {len(config['middleware'].get('definitions', []))} middleware definitions")
        except IOError as e:
            print(f"❌ Error writing output file: {e}")
            sys.exit(1)

    def generate_docs(self) -> None:
        """
        Generate markdown documentation for the middleware
        """
        config = self.load_config()
        config = self.transform_config(config)

        doc_lines = ["# Middleware Documentation", "", "## Available Middleware", ""]

        definitions = config.get("middleware", {}).get("definitions", [])

        for mw_def in definitions:
            name = mw_def.get("name", "Unknown")
            mw_type = mw_def.get("type", "unknown")
            desc = mw_def.get("description", "No description provided")

            doc_lines.append(f"### {name.capitalize()}Middleware")
            doc_lines.append(f"**Type**: `{mw_type}`  ")
            doc_lines.append(f"**Description**: {desc}  ")
            doc_lines.append("")

            # Add usage example
            doc_lines.append("**Usage**:")
            doc_lines.append("```go")
            doc_lines.append(f"router.Use(middleware.{name.capitalize()}Middleware())")
            doc_lines.append("```")
            doc_lines.append("")

        # Write documentation
        doc_path = Path(self.output_dir) / "MIDDLEWARE.md"
        try:
            with open(doc_path, "w") as f:
                f.write("\n".join(doc_lines))
            print(f"✅ Generated documentation: {doc_path}")
        except IOError as e:
            print(f"❌ Error writing documentation: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Module-level entry points (consistent with other generators)
# ─────────────────────────────────────────────────────────────────────────────

def run(config_path: str, templates_dir: str, output_dir: str) -> None:
    """
    Run the middleware generator. Called by master orchestrator.

    Args:
        config_path:   Path to YAML config
        templates_dir: Templates root directory (the middleware template must be at
                       <templates_dir>/internal/api/middleware/middleware.go.j2)
        output_dir:    Output root directory
    """
    template_dir = os.path.join(templates_dir, 'internal', 'api', 'middleware')
    generator = MiddlewareGenerator(config_path, template_dir, output_dir)
    generator.generate()


def main():
    """
    CLI entry point for the middleware generator.
    """
    parser = argparse.ArgumentParser(description='Generate Go middleware from YAML config')
    parser.add_argument('--config',    required=True,
                        help='Path to YAML config file')
    parser.add_argument('--templates', default='./tool/templates',
                        help='Templates root directory (default: ./tool/templates)')
    parser.add_argument('--output',   default='./generated',
                        help='Output directory (default: ./generated)')
    parser.add_argument('--docs',     action='store_true',
                        help='Also generate MIDDLEWARE.md documentation')
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f'❌ Config not found: {args.config}')
        sys.exit(1)

    print('=' * 60)
    print('  MIDDLEWARE GENERATOR')
    print('=' * 60)

    template_dir = os.path.join(args.templates, 'internal', 'api', 'middleware')
    generator = MiddlewareGenerator(args.config, template_dir, args.output)
    generator.generate()

    if args.docs:
        generator.generate_docs()

    print('')
    print('🎉 Generation complete!')


if __name__ == '__main__':
    main()