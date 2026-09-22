"""Regression probes use only dummy credentials and disposable native sandboxes."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from run import confined_replay as replay
import run
from test_run import LabCase, git


class ReplayBoundaryTests(unittest.TestCase):
    def test_environment_is_allowlisted_not_director_or_role_environment(self):
        with patch.dict(os.environ, {'TYPESAFE_API_KEY':'dummy', 'PGPASSWORD':'dummy',
                 'BASH_ENV':'/private/startup', 'PYTHONPATH':'/private/python',
                 'GIT_CONFIG_VALUE_0':'dummy', 'XDG_CONFIG_HOME':'/private/config'}):
            env = replay.environment('/empty-home', '/empty-tmp')
        for key in ('TYPESAFE_API_KEY','PGPASSWORD','PGSERVICEFILE','BASH_ENV',
                    'PYTHONPATH','GIT_CONFIG_VALUE_0','XDG_CONFIG_HOME'):
            self.assertNotIn(key, env)
        self.assertEqual(env['HOME'], '/empty-home')
        self.assertEqual(env['PYTHONNOUSERSITE'], '1')

    def test_missing_backend_never_executes_worker_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / 'ESCAPED'
            with patch.object(replay.sys, 'platform', 'unsupported'):
                with self.assertRaises(replay.ReplayUnavailable):
                    replay.execute(root, 'touch ' + str(marker), 2)
            self.assertFalse(marker.exists())

    def test_snapshot_rejects_symlinks_and_hardlinks_before_reading_targets(self):
        for link in ('symlink','hardlink'):
            with self.subTest(link=link), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); source = root / 'run'; source.mkdir()
                secret = root / 'private'; secret.write_text('DUMMY_PRIVATE')
                if link == 'symlink': (source / 'escape').symlink_to(secret)
                else: os.link(secret, source / 'escape')
                with self.assertRaises(replay.ReplayUnavailable):
                    replay.copy_run(source, root / 'snapshot')
                self.assertFalse((root / 'snapshot/escape').exists())

    def test_snapshot_copies_regular_executable_and_enforces_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'run';source.mkdir()
            (source/'check').write_text('echo CHECK_OK');(source/'check').chmod(0o755)
            replay.copy_run(source,root/'copy')
            self.assertEqual((root/'copy/check').read_text(),'echo CHECK_OK')
            self.assertTrue(os.access(root/'copy/check',os.X_OK))
            with patch.object(replay,'MAX_BYTES',1):
                with self.assertRaises(replay.ReplayUnavailable): replay.copy_run(source,root/'too-large')


class NativeReplayTests(LabCase):
    def test_real_ingest_cannot_read_director_keys_files_or_host_processes(self):
        sentinel = 'DUMMY_REPLAY_CREDENTIAL_MUST_NOT_BE_COMMITTED'
        private = self.root.parent / (self.root.name + '-private')
        private.mkdir(); self.addCleanup(__import__('shutil').rmtree,private,ignore_errors=True)
        for name in ('.pgpass','.pg_service.conf','jev-key','cookie-secret','jwt-secret'):
            (private/name).write_text(sentinel)
        listener = socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
        self.addCleanup(listener.close)
        port = listener.getsockname()[1]
        rid,_=self.dispatch()
        self.packet(rid,command='python3 packet/probe.py')
        packet=self.problem/'runs'/rid/'packet'
        (packet/'own.txt').write_text('readable packet input')
        paths=[str(private/n) for n in ('.pgpass','.pg_service.conf','jev-key','cookie-secret','jwt-secret')]
        paths += [str(self.root/'lab.local.json'), '/proc/%d/environ'%os.getpid(),
                  '/proc/1/root'+str(private/'jev-key')]
        code = '''import os, pathlib, socket, subprocess, sys
for key in ['TYPESAFE_API_KEY','PGPASSWORD','PGSERVICEFILE','BASH_ENV','PYTHONPATH','GIT_CONFIG_VALUE_0']:
    assert key not in os.environ, key
for path in PATHS:
    try: pathlib.Path(path).read_bytes()
    except OSError: print('DENIED private input')
    else: raise AssertionError('private input was readable')
assert pathlib.Path('packet/own.txt').read_text() == 'readable packet input'
pathlib.Path(os.environ['HOME'],'own-home-file').write_text('safe output')
pathlib.Path('sandbox-output').write_text('not a research mutation')
try:
    s=socket.create_connection(('127.0.0.1',PORT),timeout=.2)
except OSError: print('DENIED host network')
else:
    s.close(); raise AssertionError('host network was reachable')
subprocess.run([sys.executable,'-c',"import os; assert 'TYPESAFE_API_KEY' not in os.environ"],check=True)
assert sum(range(4)) == 6
print('CHECK_OK')
'''.replace('PATHS',repr(paths)).replace('PORT',str(port))
        if sys.platform == 'darwin':
            # Verify the OTHER host process's argument/environment interface is
            # actually readable outside, then denied inside the sandbox. Use
            # the platform header rather than hard-coded sysctl numbers.
            src = packet / 'proc_probe.c'
            src.write_text("""#include <sys/types.h>
#include <sys/sysctl.h>
#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
int main(int argc,char **argv) {
  if (argc != 3) return 2;
  int mib[3] = {CTL_KERN, KERN_PROCARGS2, atoi(argv[1])};
  char buf[262144]; size_t len = sizeof(buf);
  int result = sysctl(mib,3,buf,&len,NULL,0);
  int denied = result < 0 && (errno == EPERM || errno == EACCES);
  if (!strcmp(argv[2],"deny")) { if (!denied) return 3; puts("DENIED host process environment"); }
  else { if (result) return 4; puts("OUTSIDE process read control"); }
  return 0;
}
""")
            exe=packet/'proc_probe'
            subprocess.run(['cc',str(src),'-o',str(exe)],check=True,capture_output=True)
            subprocess.run([str(exe),str(os.getpid()),'allow'],check=True,capture_output=True)
            code = "import subprocess\nsubprocess.run(['./packet/proc_probe', %r, 'deny'], check=True)\n" % str(os.getpid()) + code
        (packet/'probe.py').write_text(code)
        self.ok('ingest',rid,'--worker-done',env={'HOME':str(private),'TYPESAFE_API_KEY':sentinel,
                'PGPASSWORD':sentinel,'PGSERVICEFILE':str(private/'.pg_service.conf'),
                'GIT_CONFIG_VALUE_0':sentinel})
        record=self.ingest_json(rid)
        self.assertTrue(record['replayed'],record)
        self.assertEqual(record['verdict'],'PASS')
        self.assertIn(record['replay']['isolation'],('bubblewrap-v1','seatbelt-v1'))
        self.assertIn('DENIED',record['replay']['tail'])
        committed=git(self.root,'show','HEAD:problems/demo/runs/'+rid+'/ingest.json').stdout
        self.assertNotIn(sentinel,committed)
        self.assertFalse((self.problem/'runs'/rid/'sandbox-output').exists())
        print('REPLAY_ISOLATION: native denial controls and recomputed canary passed')

    def test_link_packet_files_as_unverified_without_unsafe_fallback(self):
        secret=self.root/'private-credential';secret.write_text('DUMMY_LINK_SECRET')
        git(self.root,'add','--',str(secret));git(self.root,'commit','-qm','dummy outside packet')
        rid,_=self.dispatch();self.packet(rid,command='cat packet/escape; echo CHECK_OK')
        (self.problem/'runs'/rid/'packet/escape').symlink_to(secret)
        self.ok('ingest',rid,'--worker-done')
        record=self.ingest_json(rid)
        self.assertFalse(record['replayed']);self.assertEqual(record['verdict'],'UNDECIDED')
        self.assertEqual(record['replay']['isolation'],'unavailable')
        self.assertNotIn('DUMMY_LINK_SECRET',json.dumps(record))

    def test_timeout_never_claims_a_replay_pass(self):
        rid,_=self.dispatch(extra=['--timeout','1'])
        self.packet(rid,command='sleep 5; echo CHECK_OK')
        self.ok('ingest',rid,'--worker-done')
        record=self.ingest_json(rid)
        self.assertFalse(record['replayed']);self.assertEqual(record['verdict'],'UNDECIDED')
        self.assertIsNone(record['replay']['exit'])


if __name__=='__main__': unittest.main(verbosity=2)
