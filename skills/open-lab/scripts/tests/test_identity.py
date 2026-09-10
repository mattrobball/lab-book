"""Who the record says you are comes from the lab's own settings first, git
only as a fallback, so a lab can be joined without touching git config."""
import os
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import claims


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "--local", "user.name", ""],
                       cwd=self.root, check=True)
        self.env = patch.dict(os.environ, {"LAB_INVESTIGATOR": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def local(self, **cfg):
        (self.root / "lab.local.json").write_text(json.dumps(cfg))

    def test_nothing_set_refuses_and_names_the_local_file(self):
        with self.assertRaises(SystemExit):
            with patch("sys.stdin.isatty", return_value=False):
                claims.own_tag(self.root)
        self.assertIn("lab.local.json", claims.LAST_REFUSAL["message"])

    def test_investigator_name_in_local_settings_makes_the_tag(self):
        self.local(investigator={"name": "Mary R. Brown"})
        self.assertEqual(claims.own_tag(self.root), claims.slug("Mary R. Brown"))

    def test_explicit_tag_wins_over_the_name(self):
        self.local(investigator={"name": "Mary R. Brown", "tag": "MRB"})
        self.assertEqual(claims.own_tag(self.root), "mrb")

    def test_environment_variable_is_the_second_source(self):
        with patch.dict(os.environ, {"LAB_INVESTIGATOR": "Env Person"}):
            self.assertEqual(claims.git_user(self.root), "Env Person")

    def test_asked_once_at_a_terminal_and_kept(self):
        with patch("sys.stdin.isatty", return_value=True), \
                patch("builtins.input", return_value="Asked Person"):
            self.assertEqual(claims.git_user(self.root), "Asked Person")
        kept = json.loads((self.root / "lab.local.json").read_text())
        self.assertEqual(kept["investigator"]["name"], "Asked Person")
        with patch("builtins.input", side_effect=AssertionError("asked twice")):
            self.assertEqual(claims.git_user(self.root), "Asked Person")


if __name__ == "__main__":
    unittest.main()
