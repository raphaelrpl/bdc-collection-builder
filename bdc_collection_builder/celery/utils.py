#
# This file is part of Brazil Data Cube Collection Builder.
# Copyright (C) 2019-2020 INPE.
#
# Brazil Data Cube Collection Builder is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
#

"""Defines the utility functions to use among celery tasks."""

from celery import current_app
from celery.backends.database import SessionManager


def list_running_tasks():
    """List all running tasks in celery cluster."""
    inspector = current_app.control.inspect()

    return inspector.active()


def list_pending_tasks():
    """List all pending tasks in celery cluster."""
    inspector = current_app.control.inspect()

    return inspector.reserved()


def load_celery_models():
    """Prepare and load celery models in database backend."""
    session = SessionManager()
    engine = session.get_engine(current_app.backend.url)
    session.prepare_models(engine)


# def list_enqueued_values():
#     app = Celery('myapp', broker=RABBIT_MQ_URL)
#
#     with app.pool.acquire(block=True) as conn:
#         data = []
#         count = []
#
#         def _receive_data(body, *args, **kwargs):
#             if body and len(body) == 3:
#                 internal, _, _ = body
#                 if isinstance(internal, list):
#                     activity = internal[0]  # , internal[1:])
#                     if isinstance(activity, str):
#                         return
#                     #                    print(len(count))
#                     count.append(1)
#                     if activity.get('sceneid'):
#                         key = activity['sceneid']
#                     else:
#                         version = 'v{0:03d}'.format(activity['args']['version'])
#                         key = f"{activity['collection_id']}_{version}_{activity['tile_id']}_{activity['period']}"
#
#                     data.append(key)
#
#         q = Queue(queue, channel=conn.default_channel)
#         consumer = Consumer(conn.default_channel, q)
#         _, total, _ = q.queue_declare()
#         print(total)
#         iterations = math.ceil(total / 200) - 3
#         consumer.register_callback(_receive_data)
#         for i in range(iterations):
#             with consumer:
#                 try:
#                     conn.drain_events(timeout=1)
#                 except:
#                     print(f'Timeout, collected only {len(data)} messages')
#                     break
#     #                conn.drain_events(timeout=10)
#     click.secho(f'Total of messages in queue "{queue}": {len(data)}', bold=True, fg='green')
#     data = sorted(set(data))
#     click.secho(f'Saving unique items {len(data)}')
#
#     parent = os.path.dirname(output_file)
#     if parent:
#         os.makedirs(parent, exist_ok=True)
#
#     with open(output_file, 'w') as f:
#         f.write(json.dumps(list(data), indent=4))
