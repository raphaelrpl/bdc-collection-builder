from celery_sqlalchemy_scheduler.schedulers import DatabaseScheduler, ModelEntry


class ModelSynchronizer(ModelEntry):
    def __init__(self, model, Session, app=None, **kw):
        super(ModelSynchronizer, self).__init__(model, Session, app=app, **kw)
        self.kwargs.update(periodic_task_id=model.id)


class Synchronizer(DatabaseScheduler):
    Entry = ModelSynchronizer
