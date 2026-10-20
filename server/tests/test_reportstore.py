import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import reportstore


class FileReportStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = reportstore.FileReportStore(Path(self.temp.name) / "nested" / "results")

    def test_saves_and_reads_back_creating_the_folder(self):
        path = self.store.save("eval-1.md", "# Report\nשלום")
        self.assertTrue(Path(path).is_file())
        self.assertEqual(self.store.read("eval-1.md"), "# Report\nשלום")

    def test_a_missing_report_reads_as_none(self):
        self.assertIsNone(self.store.read("nope.md"))
        self.assertEqual(self.store.names(), [])

    def test_saving_again_replaces_the_report(self):
        self.store.save("a.md", "one")
        self.store.save("a.md", "two")
        self.assertEqual(self.store.read("a.md"), "two")

    def test_names_are_listed_newest_first(self):
        for index, name in enumerate(("old.md", "mid.md", "new.md")):
            path = self.store.save(name, name)
            os.utime(path, (1_000_000 + index, 1_000_000 + index))
        self.assertEqual(self.store.names(), ["new.md", "mid.md", "old.md"])

    def test_names_that_could_leave_the_folder_are_refused(self):
        for bad in ("../x.md", "a/b.md", "a\\b.md", "..", ".hidden", "", "x" * 81, "with space.md", "/etc/passwd"):
            with self.assertRaises(ValueError, msg=bad):
                self.store.save(bad, "x")
            with self.assertRaises(ValueError, msg=bad):
                self.store.read(bad)

    def test_the_directory_can_come_from_the_environment(self):
        with mock.patch.dict(os.environ, {"EVAL_RESULTS_DIR": self.temp.name}):
            self.assertEqual(reportstore.FileReportStore().directory, Path(self.temp.name))

    def test_the_default_directory_is_next_to_the_evals(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("EVAL_RESULTS_DIR", None)
            self.assertEqual(reportstore.default_directory(), reportstore.DEFAULT_DIRECTORY)
        self.assertEqual(reportstore.DEFAULT_DIRECTORY.parts[-3:], ("server", "evals", "results"))

    def test_files_with_other_names_are_not_listed(self):
        self.store.save("good.md", "x")
        (self.store.directory / ".gitkeep").write_text("", encoding="utf-8")
        self.assertEqual(self.store.names(), ["good.md"])


if __name__ == "__main__":
    unittest.main()
