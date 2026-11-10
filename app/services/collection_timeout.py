from copy import deepcopy
from importlib import import_module
from multiprocessing import get_context
from queue import Empty
from time import monotonic


COLLECTION_TIMEOUT_SECONDS = 120


def _collect(module_name, function_name, state, messages):
    def emit(record):
        messages.put(("record", deepcopy(record)))

    try:
        collector = getattr(import_module(module_name), function_name)
        collector(state, emit)
    except Exception as error:
        messages.put(("error", error))
    else:
        messages.put(("done", None))


def collect_with_timeout(module_name, function_name, state, timeout_s=COLLECTION_TIMEOUT_SECONDS):
    context = get_context("spawn")
    messages = context.Queue()
    worker = context.Process(target=_collect, args=(module_name, function_name, state, messages), daemon=True)
    records = {}
    deadline = monotonic() + timeout_s
    worker.start()
    try:
        while (remaining := deadline - monotonic()) > 0:
            try:
                kind, value = messages.get(timeout=remaining)
            except Empty:
                break
            if kind == "done":
                break
            if kind == "error":
                raise value
            records[value["url"]] = value
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join()
        messages.close()
        worker.close()
    return {"raw_sources": list(records.values())}
