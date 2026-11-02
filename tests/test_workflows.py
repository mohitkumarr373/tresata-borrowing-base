import copy
from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import URLError
from http.client import HTTPConnection

from borrowcheck.audit import AuditLog
from borrowcheck.cli import ROOT, main
from borrowcheck.evidence import digest
from borrowcheck.extraction import (approve_proposal, local_candidate, openrouter_candidate,
                                   propose, retrieve, validate_candidate)
from borrowcheck.packets import documents_for, read_json, reconcile
from borrowcheck.web import make_server


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / 'examples/04_worked', self.root / 'packet')
        self.path = self.root / 'packet/packet.json'
        self.packet = read_json(self.path)
        self.docs = documents_for(self.path, self.packet)
        self.candidate = local_candidate(self.docs, self.packet['as_of'])

    def test_local_proposal_never_approves(self):
        p = propose(self.path)
        self.assertEqual(p['status'], 'PROPOSED_NOT_APPROVED')
        self.assertFalse(p['metadata']['live_model_call'])
        self.assertEqual(p['parameters']['concentration_bp'], 2000)

    def test_cache_reuses_checked_sources(self):
        first = propose(self.path, cache_dir=self.root/'cache')
        second = propose(self.path, cache_dir=self.root/'cache')
        self.assertFalse(first['cache_hit']); self.assertTrue(second['cache_hit'])
        self.assertEqual(first['parameters'], second['parameters'])

    def test_cache_cannot_promote_status(self):
        propose(self.path, cache_dir=self.root/'cache')
        path = next((self.root/'cache').glob('*.json'))
        p = read_json(path); p['status'] = 'APPROVED'; path.write_text(json.dumps(p))
        with self.assertRaises(ValueError):
            propose(self.path, cache_dir=self.root/'cache')

    def test_unknown_and_ambiguous_quotes_rejected(self):
        for change in [{'document_id':'invented'}, {'quote':'not present'}]:
            c = copy.deepcopy(self.candidate); c['evidence']['age_days'].update(change)
            with self.assertRaises(ValueError):
                validate_candidate(c, self.docs)

    def test_unexpected_schema_and_unsupported_conditions_rejected(self):
        for c in [dict(self.candidate, funding_authorized=True), dict(self.candidate, parameters=[]),
                  dict(self.candidate, unsupported_clauses=['cross-collateral guarantee'])]:
            with self.assertRaises(ValueError):
                validate_candidate(c, self.docs)

    def test_boolean_is_not_rate(self):
        self.candidate['parameters']['advance_bp'] = True
        with self.assertRaises(ValueError):
            validate_candidate(self.candidate, self.docs)

    def test_evidence_validation_is_not_semantic_proof(self):
        # This deliberately demonstrates the limit: a real quote can accompany a wrong value.
        self.candidate['parameters']['advance_bp'] = 8100
        checked = validate_candidate(self.candidate, self.docs)
        self.assertEqual(checked['parameters']['advance_bp'], 8100)
        self.assertIn('80.00', checked['evidence']['advance_bp']['quote'])

    def test_retrieval_expands_transitive_section_references(self):
        docs = {'x': {'text':'Section 1. Concentration refers to Section 2.\n\nSection 2. Apply Section 3.\n\nSection 3. Definition of pool.\n\nSection 4. Unrelated.'}}
        results = retrieve(docs, 'Concentration', limit=1)
        self.assertEqual(len(results), 3)

    def test_amendment_local_extraction(self):
        proposal = propose(ROOT/'examples/08_amendment/packet.json')
        self.assertEqual(proposal['parameters']['concentration_bp'], 2500)
        self.assertEqual(proposal['evidence']['concentration_bp']['document_id'], 'amendment')

    def test_review_writes_new_packet_and_changes_run(self):
        p = self.root/'proposal.json'; p.write_text(json.dumps(propose(self.path)))
        output = self.path.with_name('reviewed.json')
        old = reconcile(self.path)
        approve_proposal(self.path, p, 'Test reviewer', output)
        new = reconcile(output)
        self.assertEqual(new['status'], 'READY_FOR_REVIEW')
        self.assertEqual(new['base'], old['base'])
        self.assertNotEqual(new['run_id'], old['run_id'])
        self.assertEqual(read_json(self.path), self.packet)

    def test_review_blocks_changed_packet(self):
        p = self.root/'proposal.json'; p.write_text(json.dumps(propose(self.path)))
        self.packet['as_of'] = '2026-10-30'; self.path.write_text(json.dumps(self.packet))
        with self.assertRaises(ValueError):
            approve_proposal(self.path, p, 'Reviewer', self.path.with_name('reviewed.json'))

    def test_review_does_not_overwrite_original(self):
        p = self.root/'proposal.json'; p.write_text(json.dumps(propose(self.path)))
        with self.assertRaises(ValueError):
            approve_proposal(self.path, p, 'Reviewer', self.path)

    def transport(self, contents, calls):
        iterator = iter(contents)
        def respond(request, **kwargs):
            calls.append(json.loads(request.data))
            content = next(iterator)
            return io.BytesIO(json.dumps({'model':'mock/model', 'choices':[{'finish_reason':'stop',
                'message':{'content':json.dumps(content)}}], 'usage':{'total_tokens':12}}).encode())
        return respond

    @patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-token-not-a-real-secret'})
    def test_mock_model_schema_and_log(self):
        calls = []
        result, meta = openrouter_candidate(self.docs, '2026-10-31', 'mock/model', self.transport([self.candidate], calls))
        self.assertEqual(meta['attempts'], 1)
        self.assertTrue(calls[0]['response_format']['json_schema']['strict'])
        self.assertTrue(calls[0]['provider']['require_parameters'])
        self.assertEqual(result['parameters']['advance_bp'], 8000)
        self.assertEqual(len(meta['llm_log']), 1)
        self.assertNotIn('test-token-not-a-real-secret', json.dumps(meta))

    @patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-token-not-a-real-secret'})
    def test_mock_model_one_repair(self):
        calls = []
        result, meta = openrouter_candidate(self.docs, '2026-10-31', 'mock/model', self.transport([{}, self.candidate], calls))
        self.assertEqual(meta['attempts'], 2)
        self.assertEqual(len(calls), 2)
        self.assertIn('Validation failed', calls[1]['messages'][-1]['content'])

    @patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-token-not-a-real-secret'})
    def test_mock_model_stops_after_two_bad_answers(self):
        calls = []
        with self.assertRaises(ValueError):
            openrouter_candidate(self.docs, '2026-10-31', 'mock/model', self.transport([{}, {}], calls))
        self.assertEqual(len(calls), 2)

    @patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-token-not-a-real-secret'})
    def test_network_failure_no_retry_or_rule(self):
        def fail(*a, **kw): raise URLError('offline')
        with self.assertRaisesRegex(ValueError, 'no rule was approved'):
            openrouter_candidate(self.docs, '2026-10-31', 'mock/model', fail)

    @patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-token-not-a-real-secret'})
    def test_context_limit_does_not_truncate(self):
        with self.assertRaisesRegex(ValueError, 'context limit'):
            openrouter_candidate({'x':{'text':'x'*48001}}, '2026-10-31', 'mock/model')

    @patch.dict(os.environ, {}, clear=True)
    def test_no_paid_default(self):
        with self.assertRaises(ValueError):
            openrouter_candidate(self.docs, '2026-10-31', '')


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.log = AuditLog(Path(self.tmp.name)/'audit.sqlite')

    def test_roundtrip_and_concurrent_append(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i:self.log.append('TEST', {'i':i}), range(24)))
        self.assertEqual(len(self.log.events()), 24)

    def test_altered_event_detected(self):
        self.log.append('TEST', {'value':1})
        with self.log.connect() as c:
            c.execute("UPDATE events SET payload='{}' WHERE id=1")
        with self.assertRaises(ValueError): self.log.events()

    def test_blocked_result_cannot_be_signed(self):
        with self.assertRaises(ValueError): self.log.signoff({'status':'BLOCKED'}, 'A', 'Reviewed')

    def test_signoff_records_no_legal_authorization(self):
        self.log.signoff(reconcile(ROOT/'examples/04_worked/packet.json'), 'Test reviewer', 'Checked terms')
        self.assertFalse(self.log.events()[0]['data']['legal_authorization'])

    def test_empty_rationale_rejected(self):
        with self.assertRaises(ValueError):
            self.log.signoff(reconcile(ROOT/'examples/04_worked/packet.json'), 'A', '')


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server = make_server(0, Path(cls.tmp.name)/'audit.sqlite')
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.port = cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.tmp.cleanup()

    def request(self, path, body=None, headers=None):
        c = HTTPConnection('127.0.0.1', self.port, timeout=5)
        c.request('POST' if body is not None else 'GET', path,
                  json.dumps(body) if body is not None else None, headers or {})
        r = c.getresponse(); status = r.status; hdr = dict(r.getheaders()); raw = r.read(); c.close()
        return status, hdr, json.loads(raw) if 'application/json' in hdr.get('Content-Type','') else raw

    def auth(self):
        return {'Content-Type':'application/json', 'X-Review-Token':self.request('/api/state')[2]['csrf_token']}

    def test_state_and_all_ten_cases(self):
        status, _, data = self.request('/api/state')
        self.assertEqual(status, 200); self.assertEqual(len(data['cases']), 10)
        self.assertEqual(self.request('/api/evaluate')[2]['passed'], 10)

    def test_cross_origin_and_wrong_host_rejected(self):
        self.assertEqual(self.request('/api/state', headers={'Host':'attacker.invalid'})[0], 403)
        h = self.auth(); h['Origin'] = 'https://attacker.invalid'
        self.assertEqual(self.request('/api/run', {'case':'04_worked'}, h)[0], 403)

    def test_post_requires_token(self):
        self.assertEqual(self.request('/api/run', {'case':'04_worked'}, {'Content-Type':'application/json'})[0], 403)

    def test_run_then_signoff_and_stale_review(self):
        h = self.auth()
        status, _, data = self.request('/api/run', {'case':'04_worked'}, h)
        self.assertEqual(status, 200)
        body = {'case':'04_worked', 'run_id':data['result']['run_id'], 'reviewer':'Test', 'note':'Test review'}
        self.assertEqual(self.request('/api/signoff', body, h)[0], 200)
        body['run_id'] = 'stale'
        self.assertEqual(self.request('/api/signoff', body, h)[0], 400)

    def test_blocked_case_signoff_rejected(self):
        r = self.request('/api/result?case=09_missing_reserve')[2]
        self.assertEqual(self.request('/api/signoff', {'case':'09_missing_reserve', 'run_id':r['run_id'], 'reviewer':'Test', 'note':'Check'}, self.auth())[0], 400)

    def test_source_access_allowlist(self):
        self.assertEqual(self.request('/api/source?case=04_worked&id=agreement')[0], 200)
        self.assertEqual(self.request('/api/source?case=04_worked&id=../../secret')[0], 400)
        self.assertEqual(self.request('/api/result?case=../../secret')[0], 400)

    def test_csp_and_no_store(self):
        status, headers, _ = self.request('/')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])


class CLITests(unittest.TestCase):
    def test_blocked_returns_nonzero_and_exports_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['demo', '--case','09_missing_reserve','--out',tmp]), 2)
            self.assertIsNone(json.loads((Path(tmp)/'reconciliation.json').read_text())['base'])

    def test_external_call_requires_explicit_flag(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['extract',str(ROOT/'examples/04_worked/packet.json'),'--provider','openrouter']), 2)

    def test_approval_requires_attestation(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['approve-proposal','absent','absent','--reviewer','Test','--out','absent']), 2)


if __name__ == '__main__':
    unittest.main()
