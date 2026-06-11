"""
async_bridge.py
Runs a dedicated asyncio event loop in a background thread.
GTK callbacks submit coroutines via run() and receive results
through GLib.idle_add so the main thread is never blocked.
"""
import asyncio
import threading
from gi.repository import GLib


_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None


def _start():
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


def ensure_started():
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_start, daemon=True, name="mps-async")
        _thread.start()


def run(coro, on_done=None, on_error=None):
    """
    Submit a coroutine to the background loop.
    on_done(result) and on_error(exc) are called on the GTK main thread
    via GLib.idle_add.
    """
    ensure_started()

    def _done(future):
        exc = future.exception()
        if exc:
            if on_error:
                GLib.idle_add(on_error, exc)
        else:
            if on_done:
                GLib.idle_add(on_done, future.result())

    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    future.add_done_callback(_done)
    return future


def run_fire(coro):
    """Submit a coroutine without caring about its result."""
    ensure_started()
    asyncio.run_coroutine_threadsafe(coro, _loop)
