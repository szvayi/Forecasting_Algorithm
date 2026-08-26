from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import BinaryIO, Optional


DEFAULT_EXECUTION_LOCK_PATH = "/run/lock/forecast-execution.lock"


class RunLockBusy(RuntimeError):
    """Raised when another execution already holds the requested lock."""


_PROCESS_LOCKS: set[str] = set()
_PROCESS_LOCKS_GUARD = threading.Lock()


class RunLock:
    """A non-blocking, process-scoped file lock with same-process protection."""

    def __init__(self, path: str = DEFAULT_EXECUTION_LOCK_PATH):
        self.path = os.path.abspath(os.fspath(path))
        self._identity = os.path.normcase(self.path)
        self._file: Optional[BinaryIO] = None

    def acquire(self) -> "RunLock":
        if self._file is not None:
            raise RunLockBusy(f"Run lock is already held: {self.path}")

        with _PROCESS_LOCKS_GUARD:
            if self._identity in _PROCESS_LOCKS:
                raise RunLockBusy(f"Run lock is busy: {self.path}")
            _PROCESS_LOCKS.add(self._identity)

        handle: Optional[BinaryIO] = None
        try:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            handle = open(self.path, "a+b")
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            self._lock_file(handle)
            self._file = handle
            return self
        except BaseException:
            if handle is not None:
                try:
                    handle.close()
                except BaseException:
                    pass
            try:
                self._discard_process_reservation()
            except BaseException:
                pass
            raise

    @property
    def is_held(self) -> bool:
        """Return whether this lease still owns the in-process reservation."""
        handle = self._file
        if handle is None or handle.closed:
            return False
        with _PROCESS_LOCKS_GUARD:
            return self._identity in _PROCESS_LOCKS

    def release(self) -> None:
        handle = self._file
        if handle is None:
            return
        self._file = None
        try:
            self._unlock_file(handle)
        finally:
            try:
                handle.close()
            finally:
                self._discard_process_reservation()

    def __enter__(self) -> "RunLock":
        return self.acquire()

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()

    def _discard_process_reservation(self) -> None:
        with _PROCESS_LOCKS_GUARD:
            _PROCESS_LOCKS.discard(self._identity)

    @staticmethod
    def _lock_file(handle: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RunLockBusy("Run lock is busy") from exc
            return

        import errno
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise RunLockBusy("Run lock is busy") from exc
            raise

    @staticmethod
    def _unlock_file(handle: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                # The operating system may already have released the lease
                # during interpreter or process teardown.
                pass
            return

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
