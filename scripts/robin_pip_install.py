"""Robin skill: Install pip packages safely.

Alfred delegates package installation to Robin. Logs results.

Usage:
    python scripts/robin_pip_install.py <package> [package2 ...]
    python scripts/robin_pip_install.py --requirements <file>
"""
import argparse
import subprocess
import sys
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description="Install pip packages")
    parser.add_argument("packages", nargs="*", help="Package names")
    parser.add_argument("--requirements", "-r", help="Requirements file")
    args = parser.parse_args()

    if not args.packages and not args.requirements:
        parser.error("Provide package names or --requirements file")

    cmd = [sys.executable, "-m", "pip", "install"]
    if args.requirements:
        cmd.extend(["-r", args.requirements])
    else:
        cmd.extend(args.packages)

    print(f"[{datetime.now().isoformat()}] Installing: {' '.join(cmd[4:])}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
