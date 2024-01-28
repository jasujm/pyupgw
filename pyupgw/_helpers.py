"""Helper functions"""

import asyncio
from collections.abc import Callable


async def async_future_helper(
    func: Callable,
    *args,
    getter=lambda x: x,
):
    """Run future returning function in thread, then await the resulting future

    The reason for existence of this function is that some AWS SDK functions
    that return ``concurrent.futures.Future`` instances actually do blocking IO
    before constructing the future (for example do blocking request, and only
    wrap the response into ``Future``).  If run inside event loop, these block,
    even if the signature suggests otherwise.  Hence it's good idea to wrap any
    ``Future`` returning AWS SDK function into this.
    """
    future = getter(await asyncio.to_thread(func, *args))
    return await asyncio.wrap_future(future)
