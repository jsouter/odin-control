"""Odin Server Utility Functions

This module implements utility methods for Odin Server.
"""
import sys
from tornado import version_info
from tornado.escape import json_decode
from tornado.ioloop import IOLoop
from odin.async_util import get_async_event_loop, wrap_async

def decode_request_body(request):
    """Extract the body from a request.

    This might be decoded from json if specified by the request header.
    Otherwise, it will return the body as-is
    """

    try:
        body_type = request.headers["Content-Type"]
        if body_type == "application/json":
            body = json_decode(request.body)
        else:
            body = request.body
    except (TypeError):
        body = request.body
    return body


def wrap_result(result, is_async=True):
    """
    Conditionally wrap a result in an aysncio Future if being used in async code on python 3.

    This is to allow common functions for e.g. request validation, to be used in both
    async and sync code across python variants.

    :param is_async: optional flag for if desired outcome is a result wrapped in a future

    :return: either the result or a Future wrapping the result
    """
    if is_async:
        return wrap_async(result)
    else:
        return result


def run_in_executor(executor, func, *args):
    """
    Run a function asynchronously in an executor.

    This method extends the behaviour of Tornado IOLoop equivalent to allow nested task execution
    without having to modify the underlying asyncio loop creation policy on python 3. If the
    current execution context does not have a valid IO loop, a new one will be created and used.
    The method returns a tornado Future instance, allowing it to be awaited in an async method where
    applicable.

    :param executor: a concurrent.futures.Executor instance to run the task in
    :param func: the function to execute
    :param arg: list of arguments to pass to the function

    :return: a Future wrapping the task
    """
    # Try to get the current asyncio event loop, otherwise create a new one
    get_async_event_loop()

    # Run the function in the specified executor, handling tornado version 4 where there was no
    # run_in_executor implementation
    if version_info[0] <= 4:
        future = executor.submit(func, *args)
    else:
        future = IOLoop.current().run_in_executor(executor, func, *args)

    return future
