#!/usr/bin/env python3
"""
Quick validation script for research feed system.
Checks dependencies, file integrity, and basic functionality.
"""

import sys
import os
from pathlib import Path

def check_python_version():
    """Verify Python 3.10+"""
    if sys.version_info < (3, 10):
        print(f"✗ Python 3.10+ required (found {sys.version_info.major}.{sys.version_info.minor})")
        return False
    print(f"✓ Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    return True

def check_packages():
    """Verify required packages."""
    packages = {
        'requests': 'HTTP library',
        'bs4': 'HTML parsing (beautifulsoup4)',
        'feedparser': 'RSS feed parsing'
    }

    missing = []
    for pkg, desc in packages.items():
        try:
            __import__(pkg)
            print(f"✓ {pkg:15} ({desc})")
        except ImportError:
            print(f"✗ {pkg:15} ({desc}) - MISSING")
            missing.append(pkg)

    if missing:
        print("\nInstall missing packages:")
        print(f"  pip install {' '.join(missing)}")
        return False
    return True

def check_files():
    """Verify script files exist."""
    base_dir = Path(__file__).parent
    required_files = {
        'workhorse-research-feed.py': 'Main research feed engine',
        'workhorse-subscribe.py': 'Feed subscription manager',
    }

    missing = []
    for filename, desc in required_files.items():
        path = base_dir / filename
        if path.exists():
            size = path.stat().st_size / 1024
            print(f"✓ {filename:40} ({desc}) - {size:.1f} KB")
        else:
            print(f"✗ {filename:40} ({desc}) - NOT FOUND")
            missing.append(filename)

    return len(missing) == 0

def check_directories():
    """Verify/create required directories."""
    base_dir = Path(__file__).parent
    log_dir = base_dir / "rudy-logs"

    if not log_dir.exists():
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            print(f"✓ Created {log_dir}")
        except Exception as e:
            print(f"✗ Failed to create {log_dir}: {e}")
            return False
    else:
        print(f"✓ Directory exists: {log_dir}")

    return True

def test_imports():
    """Test that scripts can be imported."""
    base_dir = Path(__file__).parent
    sys.path.insert(0, str(base_dir))

    try:
        # Just check they parse
        import ast

        script_path = base_dir / "workhorse-research-feed.py"
        with open(script_path) as f:
            ast.parse(f.read())
        print("✓ workhorse-research-feed.py syntax valid")

        script_path = base_dir / "workhorse-subscribe.py"
        with open(script_path) as f:
            ast.parse(f.read())
        print("✓ workhorse-subscribe.py syntax valid")

        return True
    except SyntaxError as e:
        print(f"✗ Syntax error: {e}")
        return False
    except Exception as e:
        print(f"✗ Parse error: {e}")
        return False

def main():
    """Run all checks."""
    print("\n" + "=" * 80)
    print("Workhorse Research Feed - System Validation")
    print("=" * 80 + "\n")

    checks = [
        ("Python Version", check_python_version),
        ("Python Packages", check_packages),
        ("Script Files", check_files),
        ("Directories", check_directories),
        ("Script Syntax", test_imports),
    ]

    results = []
    for name, check_fn in checks:
        print(f"\n{name}:")
        print("-" * 40)
        try:
            result = check_fn()
            results.append((name, result))
        except Exception as e:
            print(f"✗ Check failed: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "=" * 80)
    print("Summary:")
    print("=" * 80)

    all_pass = True
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:8} {name}")
        if not result:
            all_pass = False

    print("=" * 80)

    if all_pass:
        print("\n✓ All checks passed! System ready.\n")
        print("Next steps:")
        print("  1. python workhorse-research-feed.py --quick")
        print("  2. Review: rudy-logs/research-digest-*.md")
        print("  3. Schedule: .\\RESEARCH-FEED-SETUP.ps1")
        print("")
        return 0
    else:
        print("\n✗ Some checks failed. See above for details.\n")
        return 1

if __name__ == '__main__':
    sys.exit(main())
