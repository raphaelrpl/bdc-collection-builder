#
# This file is part of Brazil Data Cube Collection Builder.
# Copyright (C) 2019-2020 INPE.
#
# Brazil Data Cube Collection Builder is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
#

"""Models for Collection Builder."""

import json
from copy import deepcopy
from datetime import datetime
from typing import List, Union

from bdc_catalog.models import Collection
from bdc_catalog.models.base_sql import BaseModel, db
from celery import states
from celery.backends.database import Task
from celery_sqlalchemy_scheduler.models import PeriodicTask, CrontabSchedule
from sqlalchemy import (ARRAY, JSON, Column, DateTime, ForeignKey, Integer,
                        PrimaryKeyConstraint, String, UniqueConstraint,
                        func)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from .utils import get_or_create_model
from ..config import Config

db.metadata.schema = Config.ACTIVITIES_SCHEMA


class RadcorActivity(BaseModel):
    """Define a collection activity.

    An activity consists in task to execute.
    """

    __tablename__ = 'activities'

    id = Column(Integer, primary_key=True)
    collection_id = Column(ForeignKey(Collection.id), nullable=False)
    activity_type = Column('activity_type', String(64), nullable=False)
    args = Column('args', JSON)
    tags = Column('tags', ARRAY(String))
    scene_type = Column('scene_type', String)
    sceneid = Column('sceneid', String(255), nullable=False)
    # sensing_date = Column(TIMESTAMP(timezone=True), nullable=False)

    # Relations
    collection = relationship('Collection')
    history = relationship('RadcorActivityHistory', back_populates='activity', order_by='desc(RadcorActivityHistory.start)')

    children = relationship('ActivitySRC', primaryjoin='RadcorActivity.id == ActivitySRC.activity_src_id')
    parents = relationship('ActivitySRC', primaryjoin='RadcorActivity.id == ActivitySRC.activity_id')

    __table_args__ = (
        UniqueConstraint(collection_id, activity_type, sceneid),
        dict(schema=Config.ACTIVITIES_SCHEMA),
    )

    @classmethod
    def get_scenes(cls, scenes: List[str]) -> List['RadcorActivity']:
        return cls.query().filter(RadcorActivity.sceneid.in_(scenes)).all()

    def failed_tasks(self) -> List['RadcorActivityHistory']:
        return db.session.query(RadcorActivityHistory).filter(RadcorActivityHistory.is_failed).all()


class ActivitySRC(BaseModel):
    """Model for collection provenance/lineage."""

    __tablename__ = 'activity_src'

    activity_id = db.Column(
        db.Integer(),
        db.ForeignKey(RadcorActivity.id, onupdate='CASCADE', ondelete='CASCADE'),
        nullable=False)

    activity_src_id = db.Column(
        db.Integer(),
        db.ForeignKey(RadcorActivity.id, onupdate='CASCADE', ondelete='CASCADE'),
        nullable=False)

    activity = relationship(RadcorActivity, primaryjoin='ActivitySRC.activity_id == RadcorActivity.id')
    parent = relationship(RadcorActivity, primaryjoin='ActivitySRC.activity_src_id == RadcorActivity.id')

    __table_args__ = (
        PrimaryKeyConstraint(activity_id, activity_src_id),
        dict(schema=Config.ACTIVITIES_SCHEMA),
    )


class RadcorActivityHistory(BaseModel):
    """Define Activity History execution.

    This model is attached with celery execution.
    An activity may have multiple executions 1..N.
    """

    __tablename__ = 'activity_history'
    __table_args__ = dict(schema=Config.ACTIVITIES_SCHEMA)

    activity_id = Column(
        ForeignKey('{}.activities.id'.format(Config.ACTIVITIES_SCHEMA, onupdate='CASCADE', ondelete='CASCADE')),
        primary_key=True, nullable=False
    )
    task_id = Column(ForeignKey(Task.id, onupdate='CASCADE', ondelete='CASCADE'), primary_key=True, nullable=False)

    start = Column('start', DateTime)
    env = Column('env', JSON)

    # Relations
    activity = relationship('RadcorActivity', back_populates="history")
    task = relationship(Task, uselist=False)

    @classmethod
    def get_by_task_id(cls, task_id: str):
        """Retrieve a task execution from celery task id."""
        return cls.query().filter(cls.task.has(task_id=task_id)).one()

    @hybrid_property
    def status(self) -> str:
        return self.task.status

    @hybrid_property
    def is_running(self) -> bool:
        return self.status == states.STARTED  # and in celery worker

    @hybrid_property
    def is_pending(self) -> bool:
        return self.status == states.PENDING

    @hybrid_property
    def is_failed(self) -> bool:
        return self.status == states.FAILURE



class DataSynchronizer(BaseModel):
    """Represent the model for data synchronization as task-like."""

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(ForeignKey(Collection.id, onupdate='CASCADE', ondelete='CASCADE'),
                           primary_key=True, nullable=False)
    schedule_id = Column(ForeignKey(PeriodicTask.id, onupdate='CASCADE', ondelete='CASCADE'),
                         primary_key=True, nullable=False)
    start_from = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, server_default=func.now(),
                        nullable=False)

    collection = relationship(Collection, lazy='select')
    scheduler = relationship(PeriodicTask)

    def __init__(self, collection: Union[int, Collection] = None, name: str = None, start_from=None, **task_kwargs):
        instance = None
        if name is not None:
            instance = self._get_scheduler(name, **task_kwargs)

        super(DataSynchronizer, self).__init__(collection=collection, scheduler=instance, start_from=start_from)

    def _get_scheduler(self, name: str, crontab=None, **kwargs):
        copy_kwargs = deepcopy(kwargs)
        if crontab is not None:
            copy_kwargs['crontab'] = CrontabSchedule(**crontab)

        args = copy_kwargs.get('args', [])
        kargs = copy_kwargs.get('kwargs', {})
        copy_kwargs['kwargs'] = json.dumps(kargs)
        copy_kwargs['args'] = json.dumps(args)

        instance, created = get_or_create_model(PeriodicTask, defaults=copy_kwargs, engine=db, name=name)
        return instance

    @hybrid_property
    def name(self) -> str:
        return self.scheduler.name

    @classmethod
    def list_synchronizers(cls, enabled: bool = True, expired: bool = False) -> List['DataSynchronizer']:
        where = [cls.scheduler.has(PeriodicTask.enabled.is_(enabled))]
        if expired:
            where.append(cls.scheduler.has(PeriodicTask.expires <= datetime.now()))
        return cls.filter(*where)

    @classmethod
    def get_from_periodic_task(cls, entry_id: int = None, entry_name: str = None) -> 'DataSynchronizer':
        if entry_id is None and entry_name is None:
            raise RuntimeError('Periodic Task Id or Name is required.')
        where = []
        if entry_id:
            where.append(PeriodicTask.id == entry_id)
        if entry_name:
            where.append(PeriodicTask.name == entry_name)
        return cls.query().filter(*where).first_or_404(f'Synchronizer {entry_id}, {entry_name} not found')

    def is_running(self) -> bool:
        # Search in celery
        return False


# class DataSynchronizerLog(BaseModel):
#     id = Column(Integer, primary_key=True)
#     synchronizer_id = Column(ForeignKey(DataSynchronizer.id, onupdate='CASCADE', ondelete='CASCADE'),
#                              primary_key=True, nullable=False)
#     total_dispatched = Column(Integer, nullable=True)
#
#     synchronizer = relationship(Collection, lazy='select')
