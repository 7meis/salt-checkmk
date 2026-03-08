import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import load_repo_module


class TestOmdExecutionModule(unittest.TestCase):
    def load_module(self):
        return load_repo_module('test_omd_exec', '_modules/omd.py')

    def test_virtual_checks_binary_state(self):
        module = self.load_module()

        with patch.object(module.os.path, 'isfile', return_value=False):
            self.assertEqual(module.__virtual__()[0], False)

        with patch.object(module.os.path, 'isfile', return_value=True), patch.object(module.os, 'access', return_value=False):
            self.assertEqual(module.__virtual__()[0], False)

        with patch.object(module.os.path, 'isfile', return_value=True), patch.object(module.os, 'access', return_value=True):
            self.assertEqual(module.__virtual__(), 'omd')

    def test_raise_command_error_includes_clean_stdout_and_stderr(self):
        module = self.load_module()

        with self.assertRaises(module.salt.exceptions.CommandExecutionError) as error:
            module._raise_command_error(
                ['omd', 'version'],
                1,
                stdout='\x1b[31mstdout\x1b[0m',
                stderr='stderr',
            )

        message = str(error.exception)
        self.assertIn("Command 'omd version' returned: 1", message)
        self.assertIn('STDOUT: stdout', message)
        self.assertIn('STDERR: stderr', message)

    def test_config_show_ignores_malformed_lines(self):
        module = self.load_module()
        output = 'FOO: on\nmalformed\n\nBAR: baz:qux\n'

        with patch.object(module, '_check_site_exists'), patch.object(module, '_exec_fetch', return_value=output):
            result = module.config_show('mysite')

        self.assertEqual(result, {'FOO': True, 'BAR': 'baz:qux'})

    def test_update_site_returns_early_when_version_matches(self):
        module = self.load_module()

        with patch.object(module, '_check_site_exists'), patch.object(module, 'site_version', return_value='2.0'), patch.object(module, 'site_running') as site_running, patch.object(module, 'site_stop') as site_stop, patch.object(module, 'site_start') as site_start, patch.object(module, '_exec_fetch_tty') as exec_fetch_tty:
            result = module.update_site('mysite', version='2.0')

        self.assertEqual(result, 'Site mysite already at the defined version 2.0')
        site_running.assert_not_called()
        site_stop.assert_not_called()
        site_start.assert_not_called()
        exec_fetch_tty.assert_not_called()

    def test_update_site_logs_output_and_restores_running_state(self):
        module = self.load_module()

        with tempfile.TemporaryDirectory() as tempdir:
            logfile = Path(tempdir) / 'omd_update.log'
            with patch.object(module, '_check_site_exists'), patch.object(module, 'site_version', return_value='1.0'), patch.object(module, 'site_running', return_value=True), patch.object(module, 'site_stop') as site_stop, patch.object(module, 'site_start') as site_start, patch.object(module, '_exec_fetch_tty', return_value=('\x1b[32mok\x1b[0m\n', 0)):
                result = module.update_site('mysite', version='2.0', logfile=str(logfile))

            content = logfile.read_text()

        self.assertEqual(result, 'ok\n')
        site_stop.assert_called_once_with('mysite')
        site_start.assert_called_once_with('mysite')
        self.assertIn('Exit Code: 0', content)
        self.assertIn('Details: ok', content)
        self.assertIn('\x1b[32mok\x1b[0m', content)

    def test_update_site_raises_and_preserves_stopped_state_on_failure(self):
        module = self.load_module()

        with tempfile.TemporaryDirectory() as tempdir:
            logfile = Path(tempdir) / 'omd_update.log'
            with patch.object(module, '_check_site_exists'), patch.object(module, 'site_version', return_value='1.0'), patch.object(module, 'site_running', return_value=False), patch.object(module, 'site_stop') as site_stop, patch.object(module, 'site_start') as site_start, patch.object(module, '_exec_fetch_tty', return_value=('failure output\n', 1)):
                with self.assertRaises(module.salt.exceptions.CommandExecutionError) as error:
                    module.update_site('mysite', version='2.0', logfile=str(logfile))

            content = logfile.read_text()

        message = str(error.exception)
        self.assertIn('Details: failure output', message)
        self.assertIn('Logfile: {}'.format(logfile), message)
        site_stop.assert_not_called()
        site_start.assert_not_called()
        self.assertIn('Exit Code: 1', content)
        self.assertIn('Details: failure output', content)


if __name__ == '__main__':
    unittest.main()