"""Opt-in real app-server checks with synthetic skills and a local mock model.

Set CODEX_THREADCTL_TEST_BINARY to a Codex binary to run. No account is used;
all configuration, threads, and model requests stay inside the temporary test.
"""
import asyncio
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from codex_threadctl.appserver import create_thread
from codex_threadctl.config_input import read_config_file
from codex_threadctl.configuration import resume_thread
from codex_threadctl.errors import AppServerResponseError


class MockModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.server.requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        response_id = f"r-{len(self.server.requests)}"
        events = [
            {'type': 'response.created', 'response': {'id': response_id}},
            {'type': 'response.output_item.done', 'item': {'type': 'message', 'id': 'm-' + response_id,
             'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'OK'}]}},
            {'type': 'response.completed', 'response': {'id': response_id,
             'usage': {'input_tokens': 10, 'output_tokens': 1, 'total_tokens': 11}}},
        ]
        payload = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class NativeServer:
    timeout = 30

    def __init__(self, home):
        self.home = home
        self.sequence = 0

    async def __aenter__(self):
        self.log = (self.home / 'server.log').open('a')
        self.process = await asyncio.create_subprocess_exec(
            os.environ['CODEX_THREADCTL_TEST_BINARY'], 'app-server',
            env=os.environ | {'CODEX_HOME': str(self.home)}, cwd=self.home,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=self.log,
        )
        try:
            await self.request('initialize', {
                'clientInfo': {'name': 'threadctl_config_test', 'version': '1'},
                'capabilities': {'experimentalApi': True},
            })
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def receive(self):
        raw = await asyncio.wait_for(self.process.stdout.readline(), self.timeout)
        if not raw:
            raise RuntimeError('test server exited: ' + (self.home / 'server.log').read_text())
        return json.loads(raw)

    async def request(self, method, params=None):
        self.sequence += 1
        self.process.stdin.write((json.dumps({
            'id': self.sequence, 'method': method, 'params': params or {},
        }) + '\n').encode())
        await self.process.stdin.drain()
        while True:
            message = await self.receive()
            if message.get('id') == self.sequence:
                if 'error' in message:
                    raise AppServerResponseError(message['error'])
                return message['result']

    async def turn(self, thread_id):
        await self.request('turn/start', {
            'threadId': thread_id, 'input': [{'type': 'text', 'text': 'Configuration fixture.'}],
        })
        while True:
            message = await self.receive()
            if message.get('method') == 'turn/completed':
                if message['params']['turn']['status'] != 'completed':
                    raise AssertionError(message)
                return

    async def __aexit__(self, *args):
        self.process.stdin.close()
        try:
            await asyncio.wait_for(self.process.wait(), self.timeout)
        except TimeoutError:
            self.process.kill()
            await self.process.wait()
        finally:
            self.log.close()


@unittest.skipUnless(os.environ.get('CODEX_THREADCTL_TEST_BINARY'), 'opt-in real Codex binary')
class NativeConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_skill_isolation_precedence_and_cold_resume(self):
        backend = ThreadingHTTPServer(('127.0.0.1', 0), MockModel)
        backend.requests = []
        serving = threading.Thread(target=backend.serve_forever, daemon=True)
        serving.start()
        try:
            with tempfile.TemporaryDirectory(prefix='threadctl-config-test-') as directory:
                home = Path(directory)
                (home / 'config.toml').write_text(
                    'model = "gpt-6-sol"\nmodel_provider = "mock"\napproval_policy = "never"\n'
                    'default_permissions = ":read-only"\n[skills.bundled]\nenabled = false\n'
                    '[model_providers.mock]\nname = "Local mock"\nwire_api = "responses"\n'
                    f'base_url = "http://127.0.0.1:{backend.server_port}"\n'
                )
                for name in ('alpha-smoke', 'beta-smoke'):
                    path = home / 'skills' / name / 'SKILL.md'
                    path.parent.mkdir(parents=True)
                    path.write_text(f'---\nname: {name}\ndescription: Synthetic test fixture.\n---\nFixture.\n')
                path = home / 'overlays' / 'worker.toml'
                path.parent.mkdir()
                path.write_text('model = "gpt-6-sol"\nmodel_reasoning_effort = "low"\n'
                                'sandbox_mode = "danger-full-access"\n[[skills.config]]\n'
                                'path = "skills/alpha-smoke/SKILL.md"\nenabled = false\n')
                config = read_config_file(str(path))

                def visible_skills():
                    blocks = [item['text'] for msg in backend.requests[-1]['input']
                              if msg.get('role') == 'developer'
                              for item in msg.get('content', [])
                              if isinstance(item, dict) and '<skills_instructions>' in item.get('text', '')]
                    self.assertTrue(blocks)
                    # Codex appends a new catalog; older catalogs remain in history.
                    return {name for name in ('alpha-smoke', 'beta-smoke') if name in blocks[-1]}

                async with NativeServer(home) as server:
                    created = await create_thread(server, directory, config_overrides=config,
                                                  model='gpt-6-luna', effort='high',
                                                  permission_profile=':read-only')
                    target = created['threadId']
                    self.assertEqual(created['settings']['activePermissionProfile']['id'], ':read-only')
                    self.assertEqual(created['settings']['reasoningEffort'], 'high')
                    await server.turn(target)
                    self.assertEqual(backend.requests[-1]['model'], 'gpt-6-luna')
                    self.assertEqual(visible_skills(), {'beta-smoke'})
                    control = await create_thread(server, directory)
                    await server.turn(control['threadId'])
                    self.assertEqual(visible_skills(), {'alpha-smoke', 'beta-smoke'})
                    named = await create_thread(server, directory, config_overrides={
                        'skills': {'config': [{'name': 'alpha-smoke', 'enabled': False}]},
                    })
                    await server.turn(named['threadId'])
                    self.assertEqual(visible_skills(), {'beta-smoke'})
                async with NativeServer(home) as server:
                    await resume_thread(server, target, continue_goal=True)
                    await server.turn(target)
                    self.assertEqual(visible_skills(), {'alpha-smoke', 'beta-smoke'})
                async with NativeServer(home) as server:
                    await resume_thread(server, target, continue_goal=True,
                                        config_overrides=config, permission_profile=':read-only')
                    await server.turn(target)
                    self.assertEqual(visible_skills(), {'beta-smoke'})
        finally:
            await asyncio.to_thread(backend.shutdown)
            backend.server_close()
            serving.join()
