"""Release packaging and durable offline CI contracts."""
import json
from pathlib import Path
import re
import unittest

KIT = Path(__file__).resolve().parents[2]
REPO = KIT.parents[1]


class ReleaseTests(unittest.TestCase):
    def test_skill_and_plugin_versions_are_coordinated(self):
        version = re.search(r'  version: "([^"]+)"', (KIT / 'SKILL.md').read_text()).group(1)
        self.assertEqual(version, '3.0.0-alpha.2')
        plugin = json.loads((REPO / '.claude-plugin/plugin.json').read_text())
        market = json.loads((REPO / '.claude-plugin/marketplace.json').read_text())
        self.assertEqual(plugin['version'], version)
        self.assertEqual(market['plugins'][0]['version'], version)

    def test_native_workflows_have_durable_push_and_pr_triggers(self):
        for name in ('kit-tests.yml','v3-pilot.yml','v3-jev-sdk.yml','v3-replay-macos.yml'):
            with self.subTest(workflow=name):
                text = (REPO / '.github/workflows' / name).read_text()
                self.assertIn('\n  push:\n', text)
                self.assertIn('\n  pull_request:\n', text)
                self.assertNotIn('pull_request_target:', text)
                self.assertNotIn('branches:', text)
                self.assertIn('contents: read', text)
                self.assertNotIn('secrets.', text)

    def test_replay_dependency_is_in_assets_known_to_original_upgrader(self):
        from run import KIT_FILES, confined_replay
        self.assertIn(('v3', 'assets/v3'), KIT_FILES)
        self.assertEqual(Path(confined_replay.__file__).resolve(), KIT / 'assets/v3/replay.py')
        self.assertFalse((KIT / 'scripts/replay.py').exists())
