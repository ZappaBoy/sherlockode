import asyncio
from collections.abc import Awaitable, Callable, Iterable


async def bounded_gather[T, R](items: Iterable[T], action: Callable[[T], Awaitable[R]], limit: int = 8) -> list[R]:
    semaphore = asyncio.Semaphore(limit)

    async def run(item: T) -> R:
        async with semaphore:
            return await action(item)

    return list(await asyncio.gather(*(run(item) for item in items)))
