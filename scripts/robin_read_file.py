"""Robin skill: Read file contents to stdout (UTF-8 safe).

Workaround for DC read_file metadata-only bug (LG-S34-003).
Alfred delegates file reads to Robin via this script.

Usage:
    python scripts/robin_read_file.py <filepath> [--lines N] [--tail N]
"""
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Read file contents")
    parser.add_argument("filepath", help="Path to file")
    parser.add_argument("--lines", type=int, default=0, help="First N lines (0=all)")
    parser.add_argument("--tail", type=int, default=0, help="Last N lines")
    args = parser.parse_args()

    try:
        with open(args.filepath, "r", encoding="utf-8", errors="replace") as f:
            if args.tail > 0:
                all_lines = f.readlines()
                lines = all_lines[-args.tail:]
            elif args.lines > 0:
                lines = [f.readline() for _ in range(args.lines)]
            else:
                lines = f.readlines()
        sys.stdout.buffer.write("".join(lines).encode("utf-8"))
    except FileNotFoundError:
        print(f"ERROR: File not found: {args.filepath}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
