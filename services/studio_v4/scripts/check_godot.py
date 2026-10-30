"""Reject Godot script errors even when editor import exits with code zero."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    template = Path(__file__).resolve().parents[1] / 'godot_project'
    with tempfile.TemporaryDirectory(prefix='studio-godot-parse-') as temporary:
        project = Path(temporary) / 'project'
        shutil.copytree(template, project)
        result = subprocess.run(
            [os.getenv('GODOT_BIN', 'godot'), '--headless', '--editor', '--path', str(project), '--import', '--quit'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180,
        )
        output = result.stdout or ''
        print(output)
        if result.returncode or any(marker in output for marker in ('SCRIPT ERROR:', 'ERROR:', 'Parse Error:')):
            raise SystemExit('Godot import or script validation failed.')
        print('Godot import and GDScript validation: PASS')


if __name__ == '__main__':
    main()
