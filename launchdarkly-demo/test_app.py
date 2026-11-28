"""Unit tests for the isolated LaunchDarkly demo (no network required)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

DEMO_DIR = Path(__file__).resolve().parent
APP_PATH = DEMO_DIR / "app.py"


def _load_app():
    spec = importlib.util.spec_from_file_location("launchdarkly_demo_app", APP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


app = _load_app()


class FakeClient:
    def __init__(self, *, initialized: bool, value: bool = False, raise_on_variation: bool = False):
        self._initialized = initialized
        self._value = value
        self._raise = raise_on_variation
        self.flush = MagicMock()

    def is_initialized(self) -> bool:
        return self._initialized

    def variation(self, key: str, context: object, default: bool) -> bool:
        if self._raise:
            raise RuntimeError("variation failed")
        assert key == app.FLAG_KEY
        return self._value


class EvaluateBannerTests(unittest.TestCase):
    def test_missing_key_uses_off_fallback_and_nonzero_exit(self) -> None:
        result = app.evaluate_banner(sdk_key="", client=None)
        self.assertFalse(result.enabled)
        self.assertEqual(result.source, "missing_key")
        self.assertEqual(result.exit_code, 1)
        self.assertIn(app.BANNER_OFF, result.lines)
        self.assertTrue(any("LAUNCHDARKLY_SDK_KEY is not set" in line for line in result.lines))

    def test_init_failed_safe_off_fallback(self) -> None:
        client = FakeClient(initialized=False)
        result = app.evaluate_banner(sdk_key="sdk-test", client=client)
        self.assertFalse(result.enabled)
        self.assertEqual(result.source, "init_failed")
        self.assertEqual(result.exit_code, 0)
        self.assertIn(app.BANNER_OFF, result.lines)
        self.assertTrue(any("failed to initialize" in line for line in result.lines))

    def test_none_client_treated_as_init_failed(self) -> None:
        result = app.evaluate_banner(sdk_key="sdk-test", client=None)
        self.assertEqual(result.source, "init_failed")
        self.assertFalse(result.enabled)

    def test_flag_on(self) -> None:
        client = FakeClient(initialized=True, value=True)
        result = app.evaluate_banner(sdk_key="sdk-test", client=client, context=SimpleNamespace())
        self.assertTrue(result.enabled)
        self.assertEqual(result.source, "flag")
        self.assertEqual(result.exit_code, 0)
        self.assertIn(app.BANNER_ON, result.lines)

    def test_flag_off(self) -> None:
        client = FakeClient(initialized=True, value=False)
        result = app.evaluate_banner(sdk_key="sdk-test", client=client, context=SimpleNamespace())
        self.assertFalse(result.enabled)
        self.assertEqual(result.source, "flag")
        self.assertIn(app.BANNER_OFF, result.lines)
        self.assertIn(app.FLAG_URL, result.lines)

    def test_variation_exception_safe_fallback(self) -> None:
        client = FakeClient(initialized=True, raise_on_variation=True)
        result = app.evaluate_banner(sdk_key="sdk-test", client=client, context=SimpleNamespace())
        self.assertFalse(result.enabled)
        self.assertEqual(result.source, "fallback")
        self.assertEqual(result.exit_code, 0)
        self.assertIn(app.BANNER_OFF, result.lines)

    def test_default_variation_argument_is_false(self) -> None:
        client = FakeClient(initialized=True, value=False)
        # FakeClient.variation asserts default path via evaluate_banner call.
        result = app.evaluate_banner(sdk_key="sdk-test", client=client, context=object())
        self.assertEqual(result.source, "flag")


class RenderAndEnvTests(unittest.TestCase):
    def test_load_sdk_key_strips_whitespace(self) -> None:
        self.assertEqual(app.load_sdk_key_from_env({"LAUNCHDARKLY_SDK_KEY": "  abc  "}), "abc")
        self.assertEqual(app.load_sdk_key_from_env({}), "")

    def test_render_banner_shapes(self) -> None:
        on_lines = app.render_banner(True)
        off_lines = app.render_banner(False)
        self.assertEqual(on_lines[0], app.BANNER_ON)
        self.assertEqual(off_lines[0], app.BANNER_OFF)


if __name__ == "__main__":
    unittest.main()
