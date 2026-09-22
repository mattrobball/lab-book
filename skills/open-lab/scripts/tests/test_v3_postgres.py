"""Real PostgreSQL ownership/expiry tests; ONLY an explicit disposable DB.

CI supplies a fresh postgres service with database name labbook_test. These
checks do not substitute a mock database for RLS, and do not contact a lab host.
"""
import json
import os
import subprocess
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

DSN = os.environ.get('LAB_BOOK_TEST_POSTGRES')
SQL = Path(__file__).resolve().parents[2] / 'assets' / 'v3' / 'reservations.sql'


@unittest.skipUnless(DSN, 'requires explicit disposable PostgreSQL service')
class PostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parsed = urlparse(DSN)
        if parsed.path != '/labbook_test' or parsed.hostname not in ('localhost', '127.0.0.1'):
            raise RuntimeError('test requires the disposable local labbook_test database')
        cls.sql(SQL.read_text(), user='postgres')
        cls.sql("CREATE ROLE alice LOGIN PASSWORD 'alice-fixture' IN ROLE lab_book_member; "
                "CREATE ROLE bob LOGIN PASSWORD 'bob-fixture' IN ROLE lab_book_member;", user='postgres')

    @classmethod
    def sql(cls, statement, user='alice', fail=False):
        parsed=urlparse(DSN)
        password=parsed.password if user=='postgres' else user+'-fixture'
        # Intentionally local non-TLS fixture; the production libpq client is
        # separately tested to force verify-full and never uses this DSN.
        env=dict(os.environ,PGPASSWORD=password)
        p=subprocess.run(['psql','-X','-qAt','--no-password','-v','ON_ERROR_STOP=1',
                          '-h',parsed.hostname,'-p',str(parsed.port or 5432),
                          '-U',user,'-d','labbook_test'],input=statement,
                         capture_output=True,text=True,env=env,timeout=10)
        if fail:
            if p.returncode==0: raise AssertionError('expected SQL denial')
            return p.stderr
        if p.returncode: raise AssertionError(p.stderr)
        return p.stdout.strip()

    @classmethod
    def rpc(cls, op, payload, user='alice', fail=False):
        literal=json.dumps(payload).replace("'","''")
        out=cls.sql("SELECT lab_book.%s('%s'::jsonb);"%(op,literal),user,fail)
        return out if fail else json.loads(out)

    def payload(self, run, seconds=60):
        return {'run':run,'problem':'problems/demo','question_id':'Q-same',
                'question':'Compute the invariant.','method':'Independent computation.',
                'model':'fixture-model','expected_claim_shape':'An integer.',
                'budget_seconds':seconds}

    def test_1_concurrent_work_is_allowed_and_visible_to_both_actors(self):
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda who:self.rpc('take_lease',self.payload('R-'+who+'-001'),who),('alice','bob')))
        self.assertNotEqual(results[0]['reservation']['lease'],results[1]['reservation']['lease'])
        for actor in ('alice','bob'):
            view=self.rpc('list_leases',{},actor)
            self.assertEqual(view['actor'],actor)
            self.assertEqual({r['actor'] for r in view['reservations']},{'alice','bob'})

    def test_2_peer_release_and_actor_forgery_cannot_change_peer_state(self):
        rows=self.rpc('list_leases',{})['reservations']
        bob=next(r for r in rows if r['actor']=='bob')
        outcome=self.rpc('release_lease',{'lease':bob['lease'],'run':bob['run_id']})
        self.assertEqual(outcome['outcome'],'unsolicited')
        self.assertTrue(any(r['lease']==bob['lease'] for r in self.rpc('list_leases',{})['reservations']))
        self.rpc('take_lease',dict(self.payload('R-alice-002'),actor='bob'),fail=True)
        self.rpc('take_lease',self.payload('R-bob-002'),fail=True)
        self.sql("UPDATE lab_book.reservations SET deadline=deadline+interval '1 day';",fail=True)
        self.sql("UPDATE lab_book.reservations SET actor='bob';",fail=True)
        self.sql("SET ROLE bob;",fail=True)

    def test_3_reannouncement_does_not_renew_or_change_the_promise(self):
        p=self.payload('R-alice-003')
        first=self.rpc('take_lease',p)['reservation']
        second=self.rpc('take_lease',p)['reservation']
        self.assertEqual(first,second)
        self.rpc('take_lease',dict(p,method='Changed after the fact.'),fail=True)

    def test_4_expiry_is_stale_and_late_return_unsolicited_not_rejected(self):
        p=self.payload('R-alice-004',seconds=1)
        row=self.rpc('take_lease',p)['reservation']
        time.sleep(1.1)
        self.rpc('reap_leases',{})
        view=self.rpc('list_leases',{})['reservations']
        self.assertEqual(next(r for r in view if r['lease']==row['lease'])['state'],'stale')
        self.assertEqual(self.rpc('release_lease',{'lease':row['lease'],'run':p['run']})['outcome'],'unsolicited')
        self.assertFalse(any(r['lease']==row['lease'] for r in self.rpc('list_leases',{})['reservations']))

    def test_5_own_release_and_reap_do_not_remove_peer_notices(self):
        p=self.payload('R-alice-005')
        row=self.rpc('take_lease',p)['reservation']
        self.assertEqual(self.rpc('release_lease',{'lease':row['lease'],'run':p['run']})['outcome'],'released')
        self.rpc('reap_leases',{})
        view=self.rpc('list_leases',{})['reservations']
        self.assertTrue(any(r['actor']=='bob' for r in view))

    def direct_insert(self, run, payload, deadline="statement_timestamp() + interval '60 seconds'", fail=False):
        literal=json.dumps(payload).replace("'","''")
        return self.sql("INSERT INTO lab_book.reservations(run_id,payload,deadline) VALUES ('%s','%s'::jsonb,%s);" % (run,literal,deadline),fail=fail)

    def test_direct_sql_namespace_payload_and_budget_are_table_invariants(self):
        base=self.payload('R-alice-601')
        cases=[('R-bob-999',dict(base,run='R-bob-999')),
               ('R-alice-601',{}), ('R-alice-601',dict(base,actor='bob')),
               ('R-alice-601',dict(base,run='R-alice-602')),
               ('R-alice-601',dict(base,budget_seconds=0)),
               ('R-alice-601',dict(base,budget_seconds=604801)),
               ('R-alice-601',dict(base,budget_seconds='60')),
               ('R-alice-601',dict(base,budget_seconds=True)),
               ('R-alice-601',dict(base,question=['not a statement'])),
               ('R-alice-601',dict(base,method='   '))]
        for run,payload in cases:
            with self.subTest(payload=payload): self.direct_insert(run,payload,fail=True)
        self.direct_insert('R-alice-601',base,"statement_timestamp() + interval '1 year'",fail=True)
        self.direct_insert('R-alice-601',base,"statement_timestamp() + interval '30 seconds'",fail=True)
        self.direct_insert('R-alice-601',base)
        rows=self.rpc('list_leases',{})['reservations']
        row=next(r for r in rows if r['run_id']=='R-alice-601')
        self.assertEqual(row['actor'],'alice');self.assertEqual(row['payload'],base)
        self.assertEqual(self.rpc('release_lease',{'lease':row['lease'],'run':row['run_id']})['outcome'],'released')

    def test_direct_sql_cannot_rewrite_registered_promise_or_deadline(self):
        p=self.payload('R-alice-603'); row=self.rpc('take_lease',p)['reservation']
        self.sql("UPDATE lab_book.reservations SET payload='{}'::jsonb WHERE run_id='R-alice-603';",fail=True)
        self.sql("UPDATE lab_book.reservations SET started_at=statement_timestamp() WHERE run_id='R-alice-603';",fail=True)
        self.sql("UPDATE lab_book.reservations SET deadline=deadline+interval '1 second' WHERE run_id='R-alice-603';",fail=True)
        self.assertEqual(self.rpc('take_lease',p)['reservation'],row)


    def test_6_no_preemption_renewal_or_public_function_privileges(self):
        names=self.sql("SELECT proname FROM pg_proc JOIN pg_namespace n ON n.oid=pronamespace WHERE n.nspname='lab_book' ORDER BY proname;",user='postgres')
        self.assertEqual(names.splitlines(),['list_leases','reap_leases','release_lease','take_lease'])
        self.sql("CREATE ROLE outsider LOGIN PASSWORD 'outsider-fixture';",user='postgres')
        self.rpc('list_leases',{},user='outsider',fail=True)

    def test_z_migrate_actual_alpha1_schema_without_rewriting_live_notices(self):
        repo = SQL.parents[4]
        old = subprocess.check_output(['git','show','0a0ac1b3404f731edce6c25ec6280eb36e9c9482:skills/open-lab/assets/v3/reservations.sql'], cwd=repo, text=True)
        migration = SQL.with_name('migrate-alpha1-alpha2.sql').read_text()
        # Restore the actual old schema in this disposable service only. The
        # shared membership role is retained; its original creation is omitted.
        self.sql('DROP SCHEMA lab_book CASCADE;',user='postgres')
        self.sql(old.replace('CREATE ROLE lab_book_member NOLOGIN;',''),user='postgres')
        payload=self.payload('R-alice-701'); row=self.rpc('take_lease',payload)['reservation']
        self.sql(migration,user='postgres',fail=True)
        self.assertEqual(self.rpc('take_lease',payload)['reservation'],row)
        self.rpc('release_lease',{'lease':row['lease'],'run':row['run_id']})
        self.rpc('reap_leases',{})
        self.sql(migration,user='postgres')
        self.rpc('take_lease',self.payload('R-alice-702'))
        self.direct_insert('R-bob-999',dict(payload,run='R-bob-999'),fail=True)
        self.direct_insert('R-alice-703',self.payload('R-alice-703'))
        self.assertEqual(self.sql("SELECT count(*) FROM pg_proc JOIN pg_namespace n ON n.oid=pronamespace WHERE n.nspname='lab_book';",user='postgres'),'4')
