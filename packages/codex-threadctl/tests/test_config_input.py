import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

from codex_threadctl import appserver, cli, commands, configuration, parser
from codex_threadctl.config_input import read_config_file, request_config
from codex_threadctl.errors import ThreadctlError, ThreadStateError
from test_appserver import FakeApp
from test_cli import FakeContext


class ConfigInputTests(unittest.TestCase):
    def test_toml_is_read_without_rebasing_server_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.toml"
            path.write_text('model_context_window = 120000\n[[skills.config]]\n'
                            'path = "skills/sample/SKILL.md"\nenabled = false\n')
            self.assertEqual(read_config_file(str(path)), {
                "model_context_window": 120000,
                "skills": {"config": [{"path": "skills/sample/SKILL.md", "enabled": False}]},
            })

    def test_unrepresentable_and_invalid_files_fail_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.toml"
            for text in ('broken = [', 'x = inf', 'x = nan', 'x = 2026-01-01',
                         'profile = "worker"', '[profiles.worker]\nmodel = "test"'):
                with self.subTest(text=text):
                    path.write_text(text)
                    with self.assertRaises(ThreadctlError):
                        read_config_file(str(path))
            with self.assertRaises(ThreadctlError):
                read_config_file(str(path / 'missing'))

    def test_explicit_flags_win_without_mutating_the_file_configuration(self):
        config = {"model": "file-model", "model_provider": "file-provider",
                  "model_reasoning_effort": "low", "approval_policy": "on-request",
                  "sandbox_mode": "danger-full-access", "default_permissions": "file-profile",
                  "skills": {"config": [{"name": "sample", "enabled": False}]}}
        original = copy.deepcopy(config)
        self.assertEqual(request_config(
            config, model="flag-model", model_provider="flag-provider", effort="high",
            approval_policy="never", permission_profile="worker",
        ), {"model_reasoning_effort": "high", "skills": original["skills"]})
        self.assertEqual(config, original)
        for key in ("sandbox_mode", "default_permissions"):
            self.assertNotIn(key, request_config(config, sandbox="read-only"))
        self.assertEqual(request_config(config), original)

    def test_file_is_not_a_live_configuration_option(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.build_parser().parse_args(['configure', 'thread', '--config-file', 'worker.toml'])

    def test_invalid_file_does_not_connect_and_has_structured_error(self):
        for argv in (['create', '--cwd', '/project'], ['resume', 'thread', '--continue-goal']):
            with (
                mock.patch.object(commands, 'AppServer') as connect,
                redirect_stdout(io.StringIO()) as output,
                redirect_stderr(io.StringIO()),
            ):
                code = cli.main(argv + ['--config-file', '/nonexistent/threadctl-test.toml', '--json'])
            self.assertEqual(code, 1)
            self.assertIn('cannot load config file', json.loads(output.getvalue())['error']['message'])
            connect.assert_not_called()


class ConfigOperationsTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_sends_file_values_and_keeps_output_to_keys(self):
        app = FakeApp()
        app.request = mock.AsyncMock(side_effect=[{'thread': {'id': 'created'}}, {}])
        config = {'skills': {'config': [{'name': 'sample', 'enabled': False}]},
                  'model': 'old', 'model_reasoning_effort': 'low',
                  'sandbox_mode': 'danger-full-access', 'default_permissions': 'old',
                  'model_providers': {'private': {'experimental_bearer_token': 'do-not-print'}}}
        result = await appserver.create_thread(app, '/project', model='new', effort='high',
                                              permission_profile='worker', config_overrides=config)
        self.assertEqual(app.request.call_args_list[0], mock.call('thread/start', {
            'cwd': '/project', 'model': 'new', 'permissions': 'worker',
            'config': {'skills': config['skills'], 'model_reasoning_effort': 'high',
                       'model_providers': config['model_providers']},
        }))
        self.assertEqual(result['configRequest'], {'keys': ['model_providers', 'model_reasoning_effort', 'skills']})
        self.assertNotIn('do-not-print', json.dumps(result))

    async def test_command_reads_file_before_create(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'worker.toml'
            path.write_text('[skills]\ninclude_instructions = false\n')
            args = parser.build_parser().parse_args(['create', '--cwd', directory, '--config-file', str(path)])
            with (mock.patch.object(commands, 'AppServer', return_value=FakeContext(FakeApp())),
                  mock.patch.object(commands, 'create_thread', mock.AsyncMock(return_value={'threadId': 'created'})) as create,
                  redirect_stdout(io.StringIO()) as output):
                await commands.cmd_create(args)
            self.assertEqual(output.getvalue(), 'created\n')
            self.assertEqual(create.call_args.kwargs['config_overrides'], {'skills': {'include_instructions': False}})

    async def test_resume_reapplies_file_in_same_loading_request(self):
        app = FakeApp(loaded=False)
        original = app.request
        async def request(method, params=None):
            if method == 'thread/resume':
                app.calls.append((method, params))
                return {'thread': {'id': 'thread'}, 'reasoningEffort': 'high'}
            return await original(method, params)
        app.request = request
        config = {'skills': {'config': [{'name': 'sample', 'enabled': False}]}}
        result = await configuration.resume_thread(app, 'thread', continue_goal=True,
                                                   config_overrides=config, effort='high')
        self.assertEqual(app.calls[-1], ('thread/resume', {
            'threadId': 'thread', 'excludeTurns': True,
            'config': config | {'model_reasoning_effort': 'high'},
        }))
        self.assertEqual(result['configRequest'], {'keys': ['model_reasoning_effort', 'skills']})

    async def test_loaded_resume_rejects_config_only_overrides(self):
        app = FakeApp()
        with self.assertRaisesRegex(ThreadStateError, 'unloaded thread'):
            await configuration.resume_thread(app, 'thread', continue_goal=True,
                                               config_overrides={'skills': {'include_instructions': False}})
        self.assertEqual([method for method, _ in app.calls], ['thread/loaded/list'])

    async def test_goal_consent_still_required_for_file_overrides(self):
        app = FakeApp(loaded=False)
        with self.assertRaisesRegex(ThreadStateError, 'continue-goal'):
            await configuration.resume_thread(app, 'thread', config_overrides={'model': 'test'})
        self.assertEqual(app.calls, [])

    async def test_resume_command_passes_file_and_preserves_request_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'worker.toml'
            path.write_text('[skills]\ninclude_instructions = false\n')
            args = parser.build_parser().parse_args([
                'resume', 'thread', '--continue-goal', '--config-file', str(path), '--json',
            ])
            with (
                mock.patch.object(commands, 'AppServer', return_value=FakeContext(FakeApp())),
                mock.patch.object(commands, 'resolve_thread_reference', mock.AsyncMock(return_value='thread')),
                mock.patch.object(commands, 'resume_thread', mock.AsyncMock(return_value={
                    'id': 'thread', 'configRequest': {'keys': ['skills']},
                })) as resume,
                redirect_stdout(io.StringIO()) as output,
            ):
                await commands.cmd_resume(args)
            self.assertEqual(resume.call_args.kwargs['config_overrides'], {'skills': {'include_instructions': False}})
            self.assertEqual(json.loads(output.getvalue())['configRequest'], {'keys': ['skills']})
