import threading

# In-memory only, keyed by job id - a running scrape checks these flags
# between businesses to pause/stop cleanly. Deliberately not persisted:
# there's nothing to resume mid-flight after a process restart, and any
# job still "running" at startup is already marked errored by db.py.
_lock = threading.Lock()
_controls: dict[str, "JobControl"] = {}


class JobControl:
    def __init__(self):
        self.cancel = threading.Event()
        self.paused = threading.Event()


def register(job_id: str) -> JobControl:
    control = JobControl()
    with _lock:
        _controls[job_id] = control
    return control


def unregister(job_id: str) -> None:
    with _lock:
        _controls.pop(job_id, None)


def get(job_id: str) -> JobControl | None:
    with _lock:
        return _controls.get(job_id)


def request_cancel(job_id: str) -> bool:
    control = get(job_id)
    if control is None:
        return False
    control.cancel.set()
    control.paused.clear()  # unblock a paused loop so it notices the cancel
    return True


def request_pause(job_id: str) -> bool:
    control = get(job_id)
    if control is None:
        return False
    control.paused.set()
    return True


def request_resume(job_id: str) -> bool:
    control = get(job_id)
    if control is None:
        return False
    control.paused.clear()
    return True
