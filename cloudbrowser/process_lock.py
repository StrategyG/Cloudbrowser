from __future__ import annotations

import os
from pathlib import Path


class ProcessLock:
    def __init__(self, path: Path):
        self.path, self.file = path, None

    def acquire(self) -> None:
        self.file = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                self.file.write(b"0")
                self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            raise ValueError("Another Cloudbrowser server already owns this data directory. Use a single worker.") from None

    def release(self) -> None:
        if self.file:
            self.file.close()
            self.file = None
