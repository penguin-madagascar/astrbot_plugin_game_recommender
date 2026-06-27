from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ChangelogTest(unittest.TestCase):
    def test_changelog_tracks_unreleased_and_current_version(self) -> None:
        changelog = ROOT / "CHANGELOG.md"

        self.assertTrue(changelog.exists())
        text = changelog.read_text(encoding="utf-8")
        self.assertIn("## Unreleased", text)
        self.assertIn("## 0.3.1", text)
        self.assertIn("参考游戏归一", text)


if __name__ == "__main__":
    unittest.main()
