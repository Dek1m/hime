"""Entry point for hime."""

from hime.config import load_config, setup_logging

config = load_config()
setup_logging(config.log_level)

from hime.cli.commands import app

app()
