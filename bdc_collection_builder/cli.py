#
# This file is part of Brazil Data Cube Collection Builder.
# Copyright (C) 2019-2020 INPE.
#
# Brazil Data Cube Collection Builder is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
#

"""Define Brazil Data Cube command line utilities.

Creates a python click context and inject it to the global flask commands.
"""

import click
from bdc_catalog.cli import cli
from flask.cli import FlaskGroup, with_appcontext

from . import create_app
from .config import Config


@click.group(cls=FlaskGroup, create_app=create_app)
def cli():
    """Command line for Collection Builder."""


@cli.command(context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True,
))
@with_appcontext
@click.pass_context
def beat(ctx: click.Context):
    """Run cube builder worker and make it available to execute data cube tasks.

    Uses celery default variables
    """
    from celery.bin.celery import main as _main

    from .celery import worker

    # TODO: Retrieve dynamically
    worker_context = '{}:celery'.format(worker.__name__)

    args = ["celery", "beat", "-A", worker_context]
    args.extend(ctx.args)
    if "-S" not in ctx.args:
        args.extend(["-S", "celery_sqlalchemy_scheduler.schedulers:DatabaseScheduler"])

    _main(args)


def main(as_module=False):
    """Load Brazil Data Cube (bdc_collection_builder) as module."""
    import sys
    cli.main(args=sys.argv[1:], prog_name="python -m bdc_collection_builder" if as_module else None)
