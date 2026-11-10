"""The public presentation cannot run paid work or start ingestion on boot."""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from finn import analysis, llm, runtime
from finn.app import lifespan


class PublicRuntimeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {"FINN_DATA_DIR": folder.name, "FINN_PUBLIC_DEMO": "1", "FINN_INTERACTIVE_DEMO": "0",
                                     "FINN_ENABLE_LLM": "1", "FINN_AUTO_REFRESH": "1",
                                     "GEMINI_API_KEY": "fixture-never-real"})
        env.start()
        self.addCleanup(env.stop)

    def test_public_demo_overrides_enabled_ai_and_existing_keys(self):
        self.assertTrue(runtime.capabilities()["read_only"])
        with patch("finn.llm.post_json") as post:
            self.assertFalse(llm.enabled())
            self.assertFalse(llm.public_config()["enabled"])
            with self.assertRaisesRegex(llm.ProviderError, "disabled"):
                llm.generate("gemini", llm.GEMINI_MODEL, "unused", {}, {})
            with self.assertRaisesRegex(llm.ProviderError, "disabled"):
                analysis.begin("INFY", "guidance")
            post.assert_not_called()

    def test_public_startup_does_not_start_a_refresher_even_if_auto_refresh_is_enabled(self):
        async def boot():
            async with lifespan(None):
                pass
        with patch("finn.app.live.Refresher") as refresher:
            asyncio.run(boot())
            refresher.assert_not_called()

    def test_local_startup_retains_refresh_lifecycle(self):
        async def boot():
            async with lifespan(None):
                pass
        with patch.dict(os.environ, {"FINN_PUBLIC_DEMO": "0"}), patch("finn.app.live.Refresher") as factory:
            asyncio.run(boot())
            factory.return_value.start.assert_called_once()
            factory.return_value.stop.assert_called_once()
