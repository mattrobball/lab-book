#!/usr/bin/env python3
"""Upgrade using the ACTUAL alpha.1 command from the pinned Git source object.

No downloads, credentials, paid calls, or production lab. Run in a full kit clone
with the native replay backend installed. The fixture deliberately uses old
KIT_FILES before invoking the old upgrade command, so omitted modules are caught.
"""
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1]
REPO = KIT.parents[1]
SOURCE = "0a0ac1b3404f731edce6c25ec6280eb36e9c9482"
sys.path[:0] = [str(KIT / 'scripts'), str(KIT / 'scripts/tests')]
from test_run import LabCase, git


class UpgradeContract(LabCase):
    def test_actual_first_pass_upgrade_installs_all_repairs_and_replays_canary(self):
        raw = subprocess.check_output(['git', 'archive', SOURCE, 'skills/open-lab'], cwd=REPO)
        with tempfile.TemporaryDirectory(prefix='alpha1-kit-') as directory:
            with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
                archive.extractall(directory, filter='data')
            old = Path(directory) / 'skills/open-lab'
            # The old code, not today's KIT_FILES, supplies the installation list.
            code = "import json,sys;sys.path.insert(0,sys.argv[1]);import run;print(json.dumps(run.KIT_FILES))"
            pairs = json.loads(subprocess.check_output([sys.executable, '-c', code, str(old / 'scripts')], text=True))
            for target, source in pairs:
                src, dst = old / source, self.root / target
                if src.is_dir(): shutil.copytree(src, dst)
                else: shutil.copy2(src, dst)
            self.shared(kit_version='3.0.0-alpha.1')
            git(self.root, 'add', '--', *[name for name, _ in pairs], 'lab.json')
            git(self.root, 'commit', '-qm', 'Install exact alpha.1 kit')
            upgraded = self.script(self.root / 'run.py', 'upgrade', '--from', str(KIT), '--agree')
            self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)
            self.assertNotIn('Same version; nothing', upgraded.stdout)
            for name in ('ci.py','jev.py','identity.py','replay.py','migrate-alpha1-alpha2.sql'):
                self.assertEqual((self.root / 'v3' / name).read_bytes(), (KIT / 'assets/v3' / name).read_bytes())
            self.assertEqual(json.loads((self.root/'lab.json').read_text())['kit_version'], '3.0.0-alpha.2')
            nojudge = self.script(self.root/'claims.py', 'compare', '--new', 'C-does-not-exist-001')
            self.assertNotEqual(nojudge.returncode, 0)
            code = "import pathlib,rectification; assert rectification.configured_judge(pathlib.Path('.')) is None"
            result = subprocess.run([sys.executable,'-c',code],cwd=self.root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            brief=self.brief('Compute 0+1+2+3 independently.', name='upgrade-canary.md')
            dispatch=self.script(self.root/'run.py','new','--brief',str(brief),'--role','manual','--no-launch')
            self.assertEqual(dispatch.returncode,0,dispatch.stderr)
            rid=dispatch.stdout.split()[0]
            self.packet(rid,command="python3 -c \"assert sum(range(4)) == 6; print('CHECK_OK')\"")
            ing=self.script(self.root/'run.py','ingest',rid,'--worker-done')
            self.assertEqual(ing.returncode,0,ing.stderr)
            rec=self.ingest_json(rid)
            self.assertEqual(rec['verdict'],'PASS'); self.assertTrue(rec['replayed'])
            self.assertIn(rec['replay']['isolation'],('bubblewrap-v1','seatbelt-v1'))
            self.assertEqual(git(self.root,'status','--porcelain').stdout,'')
            print(json.dumps({'old_source':SOURCE,'version':'3.0.0-alpha.2',
                              'canary':rid,'replayed':True,'isolation':rec['replay']['isolation'],
                              'live_judge_enabled':False}))


if __name__ == '__main__': unittest.main(verbosity=2)
