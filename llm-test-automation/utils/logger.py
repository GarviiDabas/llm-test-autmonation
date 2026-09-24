"""
utils/logger.py

Centralized logging module for the automation framework.
Provides a configured logger with console and rotating file handlers.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
AUTOMATION_LOG_FILE = LOG_DIR / "automation.log"


def get_logger(name: str = "automation", log_file: Path = AUTOMATION_LOG_FILE, level: str = None) -> logging.Logger:
    """
    Returns a configured logger instance with both Console and File handlers.
    
    :param name: Name of the logger instance (usually __name__ or module name)
    :param log_file: Path to log file
    :param level: Optional override log level (DEBUG, INFO, WARNING, ERROR)
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    env_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level_str = level.upper() if level else env_level
    log_level = getattr(logging, log_level_str, logging.INFO)
    logger.setLevel(log_level)

    formatter = logging.Formatter(fmt=DEFAULT_LOG_FORMAT, datefmt=DEFAULT_DATE_FORMAT)

    # 1. Console Handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 2. Rotating File Handler (max 5MB, keep 3 backups)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


    logger.propagate = False

    return logger


# Default logger instance
logger = get_logger("automation")
