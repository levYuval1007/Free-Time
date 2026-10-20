"""Tags every log line with the id of the planning job that produced it, so one plan can be followed through the
logs of the agent, the tools and the routing and places calls."""

import contextvars
import logging

current_job = contextvars.ContextVar("current_job", default="-")
_installed = False


def install():
    """Give every log record a `job` field. Safe to call more than once."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        record.job = current_job.get()
        return record

    logging.setLogRecordFactory(factory)
    _installed = True


install()
