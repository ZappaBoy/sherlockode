from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sherlockode.config import AppConfig


class ConfigLoadTests(unittest.TestCase):
    def test_environment_overrides_toml_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "repo-agent.toml"
            config_path.write_text(
                """
[workspace]
root = "workspace-from-toml"

[sandbox]
enabled = false

[groups]
python = ["service-a", "service-b"]
""".strip(),
                encoding="utf-8",
            )

            env = {
                "REPO_AGENT_WORKSPACE": "workspace-from-env",
                "REPO_AGENT_SANDBOX_ENABLED": "true",
                "REPO_AGENT_LOG_LEVEL": "DEBUG",
            }
            config = AppConfig.load(config_path, env)

            self.assertEqual(Path("workspace-from-env"), config.workspace.root)
            self.assertTrue(config.sandbox.enabled)
            self.assertEqual("DEBUG", config.log_level)
            self.assertEqual(["service-a", "service-b"], config.groups["python"].repositories)


if __name__ == "__main__":
    unittest.main()
