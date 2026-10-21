"""Runtime concerns for the desktop app: version, logging and single-instance.

Kept separate from data_manager so the persistence layer stays importable
(and testable) without touching the filesystem beyond its own database.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

APP_NAME = "BarStock Management"
APP_VERSION = "2.1.0"

_LOCK_HANDLE = None


def get_app_support_dir() -> str:
    path = os.path.expanduser("~/Library/Application Support/BarStockManagement")
    os.makedirs(path, exist_ok=True)
    return path


def get_log_path() -> str:
    return os.path.join(get_app_support_dir(), "logs", "barstock.log")


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure a rotating log file (and stderr if one is attached).

    Logging used to be limited to print() and modal dialogs, so a crash or a
    failed save left no record to investigate. The log lives beside the
    database and rotates at 2 MB, keeping five files.
    """
    logger = logging.getLogger()
    if getattr(logger, "_barstock_configured", False):
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )

    log_dir = os.path.join(get_app_support_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    file_handler = RotatingFileHandler(
        get_log_path(), maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if sys.stderr is not None:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    logger._barstock_configured = True
    logger.info("%s %s starting (pid %s)", APP_NAME, APP_VERSION, os.getpid())
    return logger


def acquire_single_instance_lock():
    """Take an exclusive lock so two copies cannot write the same database.

    Returns the open file handle (keep it alive for the process lifetime), or
    None when another instance already holds the lock. The OS releases the
    lock automatically if the process dies, so a stale lock file is harmless.
    """
    global _LOCK_HANDLE
    if _LOCK_HANDLE is not None:
        return _LOCK_HANDLE

    try:
        import fcntl
    except ImportError:  # pragma: no cover - non-POSIX platform
        # No advisory locking available; let the app run rather than block it.
        return True

    lock_path = os.path.join(get_app_support_dir(), "barstock.lock")
    handle = open(lock_path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None

    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _LOCK_HANDLE = handle
    return handle


def install_exception_hooks(root=None) -> None:
    """Send unhandled exceptions (including Tk callbacks) to the log."""
    logger = logging.getLogger("barstock.crash")

    def excepthook(exc_type, exc, tb):
        logger.error("Unhandled exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = excepthook

    if root is not None:
        def report_callback_exception(exc_type, exc, tb):
            logger.error("Unhandled Tk callback exception",
                         exc_info=(exc_type, exc, tb))
            try:
                from tkinter import messagebox
                messagebox.showerror(
                    "Unexpected Error",
                    f"{exc_type.__name__}: {exc}\n\nDetails were written to:\n{get_log_path()}",
                )
            except Exception:
                pass

        root.report_callback_exception = report_callback_exception
