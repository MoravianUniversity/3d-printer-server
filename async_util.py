"""
Asynchronous utilities.

Emulates asyncio.loop.run_in_executor() but supports ProcessPoolExecutor by
using functools.partial() instead of local functions.
"""

from functools import partial
from concurrent.futures import ProcessPoolExecutor
import concurrent.futures
import asyncio

def run_async(func, *args):
    if run_async._executor is None:
        run_async._executor = ProcessPoolExecutor(6)
    return _wrap_future(run_async._executor.submit(func, *args))

run_async._executor = None


def _wrap_future(src):
    future = asyncio.Future()
    future.add_done_callback(partial(_call_check_cancel, src))
    src.add_done_callback(partial(_call_set_state, future))
    return future


def _call_check_cancel(src, future):
    if future.cancelled():
        src.cancel()


def _call_set_state(future, src):
    if future.cancelled() and future.get_loop().is_closed(): return
    future.get_loop().call_soon_threadsafe(_set_state, src, future)


def _set_state(src, dest):
    if dest.cancelled():
        return
    if src.cancelled():
        dest.cancel()
    else:
        exception = src.exception()
        if exception is not None:
            dest.set_exception(_convert_future_exc(exception))
        else:
            dest.set_result(src.result())


def _convert_future_exc(exc):
    exc_class = type(exc)
    if exc_class is concurrent.futures.CancelledError:
        return asyncio.exceptions.CancelledError(*exc.args)
    elif exc_class is concurrent.futures.TimeoutError:
        return asyncio.exceptions.TimeoutError(*exc.args)
    elif exc_class is concurrent.futures.InvalidStateError:
        return asyncio.exceptions.InvalidStateError(*exc.args)
    else:
        return exc
