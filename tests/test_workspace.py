from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sherlockode.models import WorkspaceConfig
from sherlockode.workspace import WorkspaceManager


class WorkspaceTests(unittest.TestCase):
    def test_workspace_directories_are_created(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "workspace"
            manager = WorkspaceManager(WorkspaceConfig(root=root))
            layout = manager.ensure_directories()

            self.assertTrue(layout.repositories.exists())
            self.assertTrue(layout.investigations.exists())
            self.assertTrue(layout.reports.exists())
            self.assertTrue(layout.analysis.exists())
            self.assertTrue(layout.generated.exists())
            self.assertTrue(layout.cache.exists())


if __name__ == "__main__":
    unittest.main()
