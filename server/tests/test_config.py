import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


class LoadEnvFileTests(unittest.TestCase):
    def write_env(self, content):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / ".env"
        path.write_text(content, encoding="utf-8")
        return path

    def test_loads_values_and_ignores_comments_and_blank_lines(self):
        path = self.write_env("# comment\n\nFIRST=one\nSECOND = two \nno_equals_sign\n")
        with mock.patch.dict(os.environ, {}, clear=True):
            config.load_env_file(path)
            self.assertEqual(os.environ["FIRST"], "one")
            self.assertEqual(os.environ["SECOND"], "two")
            self.assertNotIn("no_equals_sign", os.environ)

    def test_strips_quotes(self):
        path = self.write_env("QUOTED=\"abc\"\nSINGLE='def'\n")
        with mock.patch.dict(os.environ, {}, clear=True):
            config.load_env_file(path)
            self.assertEqual(os.environ["QUOTED"], "abc")
            self.assertEqual(os.environ["SINGLE"], "def")

    def test_keeps_values_containing_equals_signs(self):
        path = self.write_env("KEY=abc==\n")
        with mock.patch.dict(os.environ, {}, clear=True):
            config.load_env_file(path)
            self.assertEqual(os.environ["KEY"], "abc==")

    def test_does_not_override_existing_environment(self):
        path = self.write_env("KEY=from-file\n")
        with mock.patch.dict(os.environ, {"KEY": "from-env"}, clear=True):
            config.load_env_file(path)
            self.assertEqual(os.environ["KEY"], "from-env")

    def test_missing_file_is_fine(self):
        config.load_env_file(Path("does-not-exist.env"))


class GetTests(unittest.TestCase):
    def test_empty_value_counts_as_missing(self):
        with mock.patch.dict(os.environ, {"KEY": ""}, clear=True):
            self.assertIsNone(config.get("KEY"))

    def test_returns_value(self):
        with mock.patch.dict(os.environ, {"KEY": "value"}, clear=True):
            self.assertEqual(config.get("KEY"), "value")


if __name__ == "__main__":
    unittest.main()
