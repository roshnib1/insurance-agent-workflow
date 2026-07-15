import asyncio
import unittest

from workflow import adk_runtime


class AdkRuntimeTests(unittest.TestCase):
    def test_run_coroutine_sync_from_running_loop(self) -> None:
        async def sample() -> str:
            await asyncio.sleep(0)
            return "ok"

        async def runner() -> None:
            result = adk_runtime._run_coroutine_sync(sample())
            self.assertEqual(result, "ok")

        asyncio.run(runner())


if __name__ == "__main__":
    unittest.main()
