"""Helper functions"""

import asyncio
import typing
from collections.abc import Callable

if typing.TYPE_CHECKING:
    import concurrent.futures


async def async_future_helper(
    func: Callable[..., "concurrent.futures.Future"], *args: typing.Any
):
    """Run future returning function in thread, then await the resulting future

    The reason for existence of this function is that some AWS SDK functions
    that return ``concurrent.futures.Future`` instances actually do blocking IO
    before constructing the future (for example do blocking request, and only
    wrap the response into ``Future``).  If run inside event loop, these block,
    even if the signature suggests otherwise.  Hence it's good idea to wrap any
    ``Future`` returning AWS SDK function into this.
    """
    future = await asyncio.to_thread(func, *args)
    return await asyncio.wrap_future(future)
