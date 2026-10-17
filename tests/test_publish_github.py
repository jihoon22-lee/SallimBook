"""Offline unit/integration tests using a deliberately small in-memory GitHub API."""
from __future__ import annotations

import base64
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_github as p
import validate_docs as v


def sample_plan():
    item = {'id': 'SB-001', 'title': '기반', 'description': '합성 예시', 'milestone': 'M0',
            'priority': 'P0', 'area': 'foundation', 'requirements': ['R-01'],
            'depends_on': [], 'acceptance': ['확인한다'], 'tests': ['검증한다'], 'docs': ['README.md']}
    second = {**copy.deepcopy(item), 'id': 'SB-002', 'title': '연결', 'depends_on': ['SB-001']}
    return {'schema_version': 1, 'project': 'SallimBook', 'milestones': [
        {'id': 'M0', 'title': 'M0', 'description': '기반'}],
        'labels': [{'name': n, 'color': 'abcdef', 'description': 'test'} for n in
                   ['type:feature', 'priority:P0', 'area:foundation']], 'issues': [item, second]}


def make_bundle(root: Path):
    plan = sample_plan()
    files = {'README.md': b'# SallimBook\n', 'planning/backlog.json': json.dumps(plan).encode()}
    meta = {'schema_version': 1, 'package_id': p.PACKAGE_ID,
            'files': {name: {'sha256': p.sha256(data), 'git_sha1': p.git_sha(data)} for name, data in files.items()}}
    files[p.MANIFEST] = json.dumps(meta).encode()
    for name, data in files.items():
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return files, meta, plan


class FakeApi:
    """Enough Git data and Issues endpoints to exercise actual Publisher code."""
    def __init__(self):
        self.calls = []
        self.login = 'jihoon22-lee'
        self.repo = None
        self.head = None
        self.blobs, self.trees, self.commits = {}, {}, {}
        self.labels, self.milestones, self.issues = [], [], []
        self.counter = 0
        self.refuse_patch = False
        self.url = 'https://github.com/jihoon22-lee/SallimBook'

    def ident(self):
        self.counter += 1
        return f'{self.counter:040x}'

    def seed(self, files, private=True, branch='main'):
        self.repo = {'private': private, 'archived': False, 'default_branch': branch,
                     'html_url': self.url, 'has_issues': True}
        self.head = self.commit_files(files)

    def commit_files(self, files):
        tree = {}
        for path, data in files.items():
            sha = p.git_sha(data)
            self.blobs[sha] = data
            tree[path] = sha
        tree_id, commit_id = self.ident(), self.ident()
        self.trees[tree_id] = tree
        self.commits[commit_id] = {'tree': {'sha': tree_id}}
        return commit_id

    def request(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, copy.deepcopy(payload)))
        path = endpoint.split('?')[0]
        base = 'repos/jihoon22-lee/SallimBook'
        if method == 'GET' and path == 'user':
            return {'login': self.login}
        if method == 'GET' and path == base:
            if self.repo is None:
                raise p.ApiError(404, 'Not Found')
            return copy.deepcopy(self.repo)
        if method == 'POST' and path == 'user/repos':
            self.seed({'README.md': b'# Initial README\n'}, private=payload['private'])
            return copy.deepcopy(self.repo)
        if method == 'GET' and path.startswith(base + '/git/ref/heads/'):
            return {'object': {'sha': self.head}}
        if method == 'GET' and path.startswith(base + '/git/commits/'):
            return copy.deepcopy(self.commits[path.rsplit('/', 1)[1]])
        if method == 'GET' and path.startswith(base + '/git/trees/'):
            tree = self.trees[path.rsplit('/', 1)[1]]
            return {'truncated': False, 'tree': [{'path': k, 'sha': val, 'type': 'blob', 'mode': '100644'}
                                                for k, val in tree.items()]}
        if method == 'GET' and path.startswith(base + '/git/blobs/'):
            data = self.blobs[path.rsplit('/', 1)[1]]
            return {'content': base64.b64encode(data).decode(), 'encoding': 'base64'}
        if method == 'POST' and path == base + '/git/trees':
            tree = dict(self.trees[payload['base_tree']])
            for entry in payload['tree']:
                data = entry['content'].encode()
                sha = p.git_sha(data)
                self.blobs[sha] = data
                tree[entry['path']] = sha
            ident = self.ident()
            self.trees[ident] = tree
            return {'sha': ident}
        if method == 'POST' and path == base + '/git/commits':
            ident = self.ident()
            self.commits[ident] = {'tree': {'sha': payload['tree']}, 'parents': payload['parents']}
            return {'sha': ident}
        if method == 'PATCH' and path.startswith(base + '/git/refs/heads/'):
            if payload.get('force') is not False:
                raise AssertionError('force push is forbidden')
            if self.refuse_patch:
                raise p.ApiError(422, 'Reference update failed')
            self.head = payload['sha']
            return {'object': {'sha': self.head}}
        for kind, store in [('labels', self.labels), ('milestones', self.milestones), ('issues', self.issues)]:
            if path == base + '/' + kind:
                if method == 'GET':
                    return copy.deepcopy(store)
                if method == 'POST':
                    number = len(store) + 1
                    obj = {**copy.deepcopy(payload), 'number': number,
                           'html_url': f'{self.url}/{kind}/{number}', 'state': 'open'}
                    store.append(obj)
                    return copy.deepcopy(obj)
        raise AssertionError(f'Unexpected fake endpoint: {method} {endpoint}')


class PureTests(unittest.TestCase):
    def test_git_blob_hash_known(self):
        self.assertEqual(p.git_sha(b''), 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391')

    def test_path_safety(self):
        for bad in ['', '.', '/etc/file', '../file', 'a/../b', 'a\\b', 'a//b', './file']:
            with self.subTest(bad=bad):
                self.assertFalse(p.valid_path(bad))
        self.assertTrue(p.valid_path('.github/ISSUE_TEMPLATE/feature.yml'))

    def test_topological_order(self):
        items = sample_plan()['issues'][::-1]
        self.assertEqual([x['id'] for x in p.ordered_issues(items)], ['SB-001', 'SB-002'])

    def test_cycle_rejected(self):
        plan = sample_plan()
        plan['issues'][0]['depends_on'] = ['SB-002']
        with self.assertRaisesRegex(p.PublishError, '순환'):
            p.validate_plan(plan, {'README.md': b''})

    def test_unknown_dependency_rejected(self):
        plan = sample_plan()
        plan['issues'][0]['depends_on'] = ['SB-999']
        with self.assertRaises(p.PublishError):
            p.validate_plan(plan, {'README.md': b''})

    def test_missing_doc_rejected(self):
        with self.assertRaises(p.PublishError):
            p.validate_plan(sample_plan(), {})

    def test_unchanged_file_skipped(self):
        self.assertEqual(p.plan_changes({'x': b'ok'}, {'x': p.git_sha(b'ok')}, None), {})

    def test_safe_update_from_previous_hash(self):
        prev = {'files': {'x': {'git_sha1': p.git_sha(b'old')}}}
        self.assertEqual(p.plan_changes({'x': b'new'}, {'x': p.git_sha(b'old')}, prev), {'x': b'new'})

    def test_user_modified_file_rejected(self):
        prev = {'files': {'x': {'git_sha1': p.git_sha(b'old')}}}
        with self.assertRaises(p.PublishError):
            p.plan_changes({'x': b'new'}, {'x': p.git_sha(b'user edit')}, prev)

    def test_unknown_file_collision_rejected(self):
        with self.assertRaises(p.PublishError):
            p.plan_changes({'x': b'new'}, {'x': p.git_sha(b'old')}, None)

    def test_unknown_remote_file_not_deleted(self):
        self.assertEqual(p.plan_changes({'x': b'new'}, {'other': p.git_sha(b'keep')}, None), {'x': b'new'})

    def test_initial_readme_requires_permission(self):
        local, remote = {'README.md': b'new'}, {'README.md': p.git_sha(b'old')}
        with self.assertRaises(p.PublishError):
            p.plan_changes(local, remote, None)
        self.assertEqual(p.plan_changes(local, remote, None, True), local)

    def test_issue_dependency_urls_not_guessed(self):
        item = sample_plan()['issues'][1]
        with self.assertRaises(p.PublishError):
            p.issue_body(item, 'u/r', 'main', {})
        body = p.issue_body(item, 'u/r', 'main', {'SB-001': {'html_url': 'https://github.com/u/r/issues/37'}})
        self.assertIn('/issues/37', body)
        self.assertIn('sallimbook:issue:SB-002', body)

    def test_paginate_lists(self):
        class Pages:
            def request(self, method, endpoint):
                return [{'id': i} for i in range(100)] if endpoint.endswith('&page=1') else [{'id': 101}]
        self.assertEqual(len(p.list_all(Pages(), 'items?state=all')), 101)

    def test_gh_json_error_and_no_secret_logging(self):
        with patch.object(p.shutil, 'which', return_value='/bin/gh'):
            api = p.GhApi()
        response = subprocess.CompletedProcess([], 1, 'HTTP/2.0 404 Not Found\nContent-Type: application/json\n\n{"message":"Not Found"}', 'fake-secret')
        with patch.object(p.subprocess, 'run', return_value=response):
            with self.assertRaises(p.ApiError) as ctx:
                api.request('GET', 'repos/a/b')
        self.assertEqual(ctx.exception.status, 404)
        self.assertNotIn('fake-secret', str(ctx.exception))

    def test_gh_success(self):
        with patch.object(p.shutil, 'which', return_value='/bin/gh'):
            api = p.GhApi()
        response = subprocess.CompletedProcess([], 0, 'HTTP/2.0 200 OK\r\n\r\n{"login":"example"}', '')
        with patch.object(p.subprocess, 'run', return_value=response):
            self.assertEqual(api.request('GET', 'user'), {'login': 'example'})

    def test_gh_timeout_does_not_retry(self):
        with patch.object(p.shutil, 'which', return_value='/bin/gh'):
            api = p.GhApi()
        with patch.object(p.subprocess, 'run', side_effect=subprocess.TimeoutExpired('gh', 90)) as run:
            with self.assertRaises(p.PublishError):
                api.request('POST', 'user/repos', {})
            self.assertEqual(run.call_count, 1)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.files, self.meta, self.plan = make_bundle(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_bundle_roundtrip(self):
        files, meta = p.load_bundle(self.root)
        self.assertEqual(files, self.files)
        p.validate_plan(self.plan, files)

    def test_tampered_file_rejected(self):
        (self.root / 'README.md').write_text('changed')
        with self.assertRaises(p.PublishError):
            p.load_bundle(self.root)

    def test_unlisted_secret_ignored(self):
        (self.root / '.env').write_text('NOT_A_REAL_SECRET=test')
        files, _ = p.load_bundle(self.root)
        self.assertNotIn('.env', files)

    def test_symlink_rejected(self):
        source = self.root / 'README.md'
        source.unlink()
        source.symlink_to(self.root / 'planning/backlog.json')
        with self.assertRaises(p.PublishError):
            p.load_bundle(self.root)

    def test_broken_link_detected_and_code_ignored(self):
        (self.root / 'README.md').write_text('[broken](missing.md)\n```\n[code](no.md)\n```\n[good](planning/backlog.json)')
        errors, count = v.local_link_errors(self.root, [self.root / 'README.md'])
        self.assertEqual(count, 2)
        self.assertEqual(len(errors), 1)

    def test_link_escape_rejected(self):
        (self.root / 'README.md').write_text('[escape](../outside.md)')
        errors, _ = v.local_link_errors(self.root, [self.root / 'README.md'])
        self.assertTrue(errors)

    def test_dependency_documents_do_not_enter_project_validation(self):
        for directory in ('node_modules/package', 'services/api/.venv/package', 'apps/client/dist'):
            path = self.root / directory / 'README.md'
            path.parent.mkdir(parents=True)
            path.write_text('[vendor link](missing.md)')
        paths = [path for path in v.project_files(self.root) if path.suffix == '.md']
        self.assertEqual(paths, [self.root / 'README.md'])
        self.assertEqual(v.local_link_errors(self.root, paths)[0], [])

    def test_new_project_document_is_still_validated(self):
        new = self.root / 'docs/new.md'
        new.parent.mkdir()
        new.write_text('[broken](missing.md)')
        paths = [path for path in v.project_files(self.root) if path.suffix == '.md']
        self.assertIn(new, paths)
        self.assertEqual(len(v.local_link_errors(self.root, paths)[0]), 1)

    def test_document_discovery_does_not_follow_symlink_directory(self):
        (self.root / 'loop').symlink_to(self.root, target_is_directory=True)
        self.assertEqual(len(v.project_files(self.root)), 3)


class IntegrationTests(unittest.TestCase):
    setUp = BundleTests.setUp
    tearDown = BundleTests.tearDown

    def publish(self, api, **kwargs):
        with redirect_stdout(io.StringIO()):
            return p.Publisher(api, self.root, self.files, self.meta, self.plan, p.Options(**kwargs)).publish()

    def test_full_publish_and_idempotent_rerun(self):
        api = FakeApi()
        first = self.publish(api)
        self.assertEqual(first['status'], 'completed')
        self.assertTrue(api.repo['private'])
        self.assertEqual(len(api.issues), 2)
        self.assertEqual(len(api.milestones), 1)
        self.assertEqual(first['files_verified'], len(self.files))
        api.issues[0]['body'] += '\nUser completed notes\n'
        api.issues[0]['state'] = 'closed'
        before = sum(m != 'GET' for m, _, _ in api.calls)
        second = self.publish(api)
        after = sum(m != 'GET' for m, _, _ in api.calls)
        self.assertEqual(before, after)
        self.assertEqual(first['commit_sha'], second['commit_sha'])
        self.assertEqual(api.issues[0]['state'], 'closed')
        self.assertIn('User completed notes', api.issues[0]['body'])

    def test_real_nine_milestones_forty_issues_plan(self):
        root = Path(__file__).resolve().parents[1]
        real_plan = json.loads((root / 'planning/backlog.json').read_text(encoding='utf-8'))
        api = FakeApi()
        with redirect_stdout(io.StringIO()):
            report = p.Publisher(api, self.root, self.files, self.meta, real_plan, p.Options()).publish()
        self.assertEqual(len(report['milestones']), 9)
        self.assertEqual(len(report['issues']), 40)
        self.assertEqual(len(api.issues), 40)
        self.assertEqual(len(api.milestones), 9)
        self.assertTrue(all('sallimbook:issue:' in i['body'] for i in api.issues))

    def test_wrong_account_no_writes(self):
        api = FakeApi()
        api.login = 'someone-else'
        with self.assertRaises(p.PublishError):
            self.publish(api)
        self.assertTrue(all(method == 'GET' for method, _, _ in api.calls))

    def test_existing_foreign_repo_refused(self):
        api = FakeApi()
        api.seed({'app.py': b'keep me'})
        with self.assertRaises(p.PublishError):
            self.publish(api)
        self.assertTrue(all(m == 'GET' for m, _, _ in api.calls))

    def test_explicit_readme_adoption(self):
        api = FakeApi()
        api.seed({'README.md': b'old readme'}, branch='trunk')
        self.publish(api, adopt_empty=True)
        self.assertIn('/blob/trunk/README.md', api.issues[0]['body'])

    def test_visibility_mismatch_never_changed(self):
        api = FakeApi()
        api.seed({'README.md': b'x'}, private=False)
        with self.assertRaises(p.PublishError):
            self.publish(api, adopt_empty=True)
        self.assertTrue(all(m == 'GET' for m, _, _ in api.calls))

    def test_nonforce_ref_conflict_stops_before_issues(self):
        api = FakeApi()
        api.refuse_patch = True
        with self.assertRaises(p.ApiError):
            self.publish(api)
        self.assertEqual(api.issues, [])
        updates = [payload for m, e, payload in api.calls if m == 'PATCH' and '/git/refs/' in e]
        self.assertEqual(len(updates), 1)
        self.assertIs(updates[0]['force'], False)

    def test_docs_only_then_plan_resume(self):
        api = FakeApi()
        self.publish(api, docs_only=True)
        self.assertEqual(api.issues, [])
        self.publish(api)
        self.assertEqual(len(api.issues), 2)

    def test_remote_user_edit_preserved(self):
        api = FakeApi()
        self.publish(api)
        new_files = dict(self.files)
        new_files['README.md'] = b'important user edit\n'
        api.head = api.commit_files(new_files)
        head = api.head
        with self.assertRaises(p.PublishError):
            self.publish(api)
        self.assertEqual(api.head, head)

    def test_unmanaged_same_title_issue_refused(self):
        api = FakeApi()
        self.publish(api, docs_only=True)
        api.issues.append({'number': 23, 'title': '[SB-001] 기반', 'body': 'unmanaged', 'html_url': api.url + '/issues/23'})
        with self.assertRaises(p.PublishError):
            self.publish(api)
        self.assertEqual(len(api.issues), 1)

    def test_duplicate_remote_issue_id_refused(self):
        api = FakeApi()
        self.publish(api)
        clone = copy.deepcopy(api.issues[0])
        clone['number'] = 99
        api.issues.append(clone)
        with self.assertRaises(p.PublishError):
            self.publish(api)


if __name__ == '__main__':
    unittest.main()
