"""LensAPI must survive being built outside an event loop.

On Python 3.9 an asyncio Lock/Semaphore binds to the loop current at
construction, so `api = LensAPI()` at module level followed by
`asyncio.run(...)` failed - and a second `asyncio.run` with the same object
failed again. These run on every supported version, but 3.9 is where they
would bite.
"""

import asyncio
import os
import pathlib
import subprocess
import sys
import textwrap

from chrome_lens_py.core.aio import LoopLocal


def test_loop_local_is_created_per_loop():
    holder = LoopLocal(asyncio.Lock)

    async def grab():
        return holder.get()

    first = asyncio.run(grab())
    second = asyncio.run(grab())
    assert first is not second  # a fresh primitive for the new loop

    async def same_loop_twice():
        return holder.get() is holder.get()

    assert asyncio.run(same_loop_twice())


def test_api_built_outside_a_loop_works_under_two_asyncio_runs():
    # In a subprocess so no event loop policy state leaks in from pytest.
    script = textwrap.dedent("""
        import asyncio
        from chrome_lens_py import LensAPI

        api = LensAPI(api_key="k")  # no loop exists yet

        async def use():
            async with api._semaphore.get():
                session = api.request_handler.new_session()
                await session.next_ids(is_new_image_payload=True)
                async with session.exclusive():
                    pass
            client = await api.request_handler.get_client()
            assert client is not None
            await api.aclose()

        asyncio.run(use())
        asyncio.run(use())
        print("ok")
        """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "PYTHONPATH": str(pathlib.Path(__file__).resolve().parents[1] / "src"),
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")
