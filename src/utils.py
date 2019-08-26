import asyncio
import inspect
import logging
import os.path

__all__ = ["read_file_ignore_errors", "raise_event", "run_event_loop", "Timer"]

log = logging.getLogger("utils")

def basedir():
    return os.path.dirname(__file__) + "/"

def read_file_ignore_errors(path):
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except:
        return None

def raise_event(handler, *args):
    if not handler:
        return

    try:
        res = handler(*args)

        if inspect.isawaitable(res):
            run_background(res)
    except Exception as e:
        log.error("Exception in background task", exc_info=e)

def run_background(coro):
    def done(task):
        if task.cancelled():
            return

        ex = task.exception()
        if ex and type(ex) != asyncio.CancelledError:
            log.error("Exception in background task", exc_info=ex)

    task = asyncio.ensure_future(coro)
    task.add_done_callback(done)
    return task

def run_event_loop(debug=False):
    loop = asyncio.get_event_loop()

    if debug:
        loop.set_debug(True)

        import warnings
        warnings.simplefilter("always", ResourceWarning)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("\nTrying to shut down gracefully... (Ctrl-C to force)")

        for task in asyncio.Task.all_tasks():
            task.cancel()

        async def _stop():
            loop.stop()

        loop.run_until_complete(_stop())
    finally:
        loop.close()

class Timer:
    def __init__(self, func, interval, repeat=False):
        self.cancelled = False

        async def call_func():
            try:
                res = func()

                if inspect.isawaitable(res):
                    await res
            except Exception as e:
                log.error("Exception in timer function", exc_info=e)

        async def repeat_coro():
            while not self.cancelled:
                await call_func()

                await asyncio.sleep(interval)

        async def single_coro():
            await asyncio.sleep(interval)

            if not self.cancelled:
                await call_func()

        asyncio.ensure_future(repeat_coro() if repeat else single_coro())

    def cancel(self):
        self.cancelled = True