import logging
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

from src.config import Config


def setup_logging() -> None:
    """
    Configure application-wide logging with file and console handlers.
    
    Creates rotating log files in logs/ directory and outputs to console.
    Log level determined by Config.LOG_LEVEL.
    """
    log_level = getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)
    
    Config.LOGS_DIR.mkdir(exist_ok=True)
    
    log_format = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(log_format)
    
    log_file = Config.LOGS_DIR / f"riki_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(log_level)
    file_handler.setFormatter(log_format)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('discord.http').setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for the given module name.
    
    Args:
        name: Module name (typically __name__)
    
    Returns:
        Configured logger instance
    
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Service initialized")
    """
    return logging.getLogger(name)


setup_logging()