#!/usr/bin/env python3
"""
Simple, reliable Go code formatter.
Properly handles indentation by tracking scope depth.
"""

import re
import sys
from pathlib import Path


def format_go_file(filepath):
    """Format a single Go file."""
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_size = len(content)
    original_lines = len(content.split('\n'))
    
    # Split into lines
    lines = content.split('\n')
    formatted_lines = []
    indent_level = 0
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Handle empty lines
        if not stripped:
            formatted_lines.append('')
            continue
        
        # Check if line starts with closing brace BEFORE indenting
        starts_with_close = stripped.startswith('}')
        if starts_with_close:
            indent_level = max(0, indent_level - 1)
        
        # Add proper indentation
        formatted_line = '\t' * indent_level + stripped
        formatted_lines.append(formatted_line)
        
        # Now check if we need to increase indent for next line
        # Count braces
        temp = stripped
        
        # Remove closing braces we already handled
        if starts_with_close:
            temp = temp.lstrip('}')
        
        # Count remaining braces
        open_braces = temp.count('{')
        close_braces = temp.count('}')
        
        # Update indent level for next iteration
        indent_level += open_braces - close_braces
        indent_level = max(0, indent_level)
    
    # Remove consecutive blank lines (keep max 1)
    cleaned = []
    prev_blank = False
    for line in formatted_lines:
        if line.strip():
            cleaned.append(line)
            prev_blank = False
        else:
            if not prev_blank:
                cleaned.append('')
            prev_blank = True
    
    # Remove trailing blank lines at start
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    
    # Remove trailing blank lines at end
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    
    # Fix spacing in code
    cleaned = fix_spacing(cleaned)
    
    # Join and ensure single newline at end
    result = '\n'.join(cleaned)
    if result and not result.endswith('\n'):
        result += '\n'
    
    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(result)
    
    final_size = len(result)
    final_lines = len(result.split('\n')) - 1  # Don't count final newline
    
    return {
        'file': filepath,
        'original_lines': original_lines,
        'final_lines': final_lines,
        'original_size': original_size,
        'final_size': final_size,
        'lines_saved': original_lines - final_lines,
        'bytes_saved': original_size - final_size,
        'percent': round(((original_size - final_size) / original_size * 100), 1) if original_size > 0 else 0
    }


def fix_spacing(lines):
    """Fix spacing in Go code."""
    result = []
    
    for line in lines:
        if not line.strip():
            result.append(line)
            continue
        
        # Get indentation
        indent = 0
        for ch in line:
            if ch == '\t':
                indent += 1
            else:
                break
        
        code = line[indent:]
        
        # Skip comments
        if code.startswith('//'):
            result.append(line)
            continue
        
        # Separate code from inline comment
        if '//' in code:
            code_part = code[:code.index('//')]
            comment_part = code[code.index('//'):]
        else:
            code_part = code
            comment_part = ''
        
        # Fix < = to <=
        code_part = code_part.replace('< =', '<=')
        code_part = code_part.replace('> =', '>=')
        
        # Fix operator spacing
        # := spacing
        code_part = re.sub(r'(\S):=(\S)', r'\1 := \2', code_part)
        
        # == spacing
        code_part = re.sub(r'(\S)==(\S)', r'\1 == \2', code_part)
        
        # != spacing
        code_part = re.sub(r'(\S)!=(\S)', r'\1 != \2', code_part)
        
        # <= and >= spacing
        code_part = re.sub(r'(\S)<=(\S)', r'\1 <= \2', code_part)
        code_part = re.sub(r'(\S)>=(\S)', r'\1 >= \2', code_part)
        
        # < and > spacing
        code_part = re.sub(r'(\S)<(\S)', r'\1 < \2', code_part)
        code_part = re.sub(r'(\S)>(\S)', r'\1 > \2', code_part)
        
        # = spacing (assignment, but not ==, :=, <=, >=)
        code_part = re.sub(r'([^:!=<>])\s*=\s*([^=<>])', r'\1 = \2', code_part)
        
        # Comma spacing
        code_part = re.sub(r',([^\s])', r', \1', code_part)
        
        # if, for, switch spacing
        code_part = re.sub(r'\bif\s*\(', 'if (', code_part)
        code_part = re.sub(r'\bfor\s*\(', 'for (', code_part)
        code_part = re.sub(r'\bswitch\s*\(', 'switch (', code_part)
        code_part = re.sub(r'\belse\s*{', 'else {', code_part)
        
        # Clean up multiple spaces
        code_part = re.sub(r'  +', ' ', code_part)
        
        # Combine
        final_code = code_part + comment_part
        result.append('\t' * indent + final_code)
    
    return result

def codeFormat(directory: str):
    directory = Path(directory)
    
    if not directory.exists():
        print(f"❌ Directory not found: {directory}")
        sys.exit(1)
    
    go_files = sorted(directory.glob('**/*.go'))
    
    if not go_files:
        print(f"❌ No .go files found in {directory}")
        sys.exit(1)
    
    print(f"\n🔧 Formatting {len(go_files)} Go files...\n")
    results = []
    total_original_size = 0
    total_final_size = 0
    total_original_lines = 0
    total_final_lines = 0
    
    for go_file in go_files:
        result = format_go_file(str(go_file))
        results.append(result)
        
        total_original_size += result['original_size']
        total_final_size += result['final_size']
        total_original_lines += result['original_lines']
        total_final_lines += result['final_lines']
        
        print(f"✅ {go_file.name}")
        print(f"   Lines: {result['original_lines']} → {result['final_lines']} (-{result['lines_saved']})")
        print(f"   Size: {result['original_size']} → {result['final_size']} bytes (-{result['bytes_saved']} bytes, -{result['percent']}%)")
        print()
    
    print("=" * 70)
    print("📊 FORMATTING SUMMARY")
    print("=" * 70)
    print(f"✅ Files formatted: {len(results)}")
    print(f"📏 Lines: {total_original_lines} → {total_final_lines} (-{total_original_lines - total_final_lines})")
    print(f"📦 Size: {total_original_size} → {total_final_size} bytes (-{total_original_size - total_final_size} bytes)")
    if total_original_size > 0:
        percent = round(((total_original_size - total_final_size) / total_original_size * 100), 1)
        print(f"📉 Total reduction: -{percent}%")
    print("=" * 70)
    print("\n✅ All files formatted!\n")

def main():
    """Main function."""
    if len(sys.argv) < 2:
        print("Usage: python3 format_go_final.py <directory>")
        print("\nExample:")
        print("  python3 format_go_final.py ./generated")
        sys.exit(1)
    
    codeFormat(sys.argv[1])

if __name__ == '__main__':
    main()



