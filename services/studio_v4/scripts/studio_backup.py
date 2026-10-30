#!/usr/bin/env python3
"""Offline Studio backup lifecycle; run after stopping Studio API and worker."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.backup import create_backup, restore_backup, verify_backup


def main():
    parser = argparse.ArgumentParser(description="Offline Studio workspace disaster recovery")
    parser.add_argument("action", choices=("backup", "verify", "restore"))
    parser.add_argument("--root", type=Path, help="Studio workspace root for backup")
    parser.add_argument("--backup", type=Path, required=True, help="Backup directory")
    parser.add_argument("--destination", type=Path, help="New, nonexistent restore workspace")
    parser.add_argument("--offline-confirmed", action="store_true",
                        help="Confirm API and worker are stopped before backup or restore")
    args = parser.parse_args()
    if args.action == "verify":
        result = verify_backup(args.backup)
    elif args.action == "backup":
        if args.root is None:
            parser.error("--root is required for backup")
        result = create_backup(args.root, args.backup,
                               offline_confirmed=args.offline_confirmed)
    else:
        if args.destination is None:
            parser.error("--destination is required for restore")
        result = restore_backup(args.backup, args.destination,
                                offline_confirmed=args.offline_confirmed)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
