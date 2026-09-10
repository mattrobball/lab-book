import json
import os
import subprocess
import sys
import unittest

import run


class WorkerEnvironmentTests(unittest.TestCase):
    def test_secrets_are_withheld_and_env_keys_are_honoured(self):
        source = {
            "PATH": "/usr/bin", "HOME": "/Users/x", "LC_ALL": "C",
            "ANTHROPIC_API_KEY": "sk-1", "OPENAI_API_KEY": "sk-2",
            "CLAUDE_CODE_MESSAGING_TOKEN": "t", "GH_TOKEN": "g",
            "PROVIDER_THING": "wanted",
        }
        env = run.worker_environment({}, source)
        self.assertEqual(set(env), {"PATH", "HOME", "LC_ALL"})
        env = run.worker_environment({"env_keys": ["PROVIDER_THING"]}, source)
        self.assertEqual(set(env), {"PATH", "HOME", "LC_ALL", "PROVIDER_THING"})

    def test_launched_worker_sees_no_secret_names(self):
        source = dict(os.environ)
        source["FAKE_LAB_API_KEY"] = "leak-me"
        env = run.worker_environment({}, source)
        out = subprocess.run(
            [sys.executable, "-c",
             "import os, json; print(json.dumps(sorted(os.environ)))"],
            env=env, capture_output=True, text=True, check=True).stdout
        names = json.loads(out)
        self.assertNotIn("FAKE_LAB_API_KEY", names)
        self.assertNotIn("CLAUDE_CODE_MESSAGING_TOKEN", names)
        self.assertIn("PATH", names)


if __name__ == "__main__":
    unittest.main()
