import os

from celery.signals import worker_process_init, worker_process_shutdown, worker_shutdown

from app.core.config import Settings
from app.db.session import create_database_engine

_engine = None
_pid = None


def get_engine():
    global _engine, _pid
    if _pid != os.getpid():
        if _engine is not None:
            _engine.dispose(close=False)
        _engine, _pid = None, os.getpid()
    if _engine is None:
        _engine = create_database_engine(Settings())
    return _engine


@worker_process_init.connect
def after_fork(**kwargs):
    global _engine, _pid
    if _engine is not None:
        _engine.dispose(close=False)
    _engine, _pid = None, os.getpid()


@worker_process_shutdown.connect
@worker_shutdown.connect
def shutdown(**kwargs):
    global _engine, _pid
    if _engine is not None:
        _engine.dispose()
    _engine, _pid = None, None
