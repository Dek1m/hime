"""Entry point for hime."""

from argenta_logging import setup_logging
from hime.config import load_config

config = load_config()
setup_logging(level=config.log_level)

from hime.cli.commands import app

app()
