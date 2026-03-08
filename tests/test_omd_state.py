import unittest
from unittest.mock import Mock, call

from tests.support import load_repo_module


class TestOmdStateModule(unittest.TestCase):
    def load_module(self):
        module = load_repo_module('test_omd_state', '_states/omd.py')
        module.__opts__ = {'test': False}
        return module

    def test_site_absent_removes_existing_site(self):
        module = self.load_module()
        remove_site = Mock()
        module.__salt__ = {
            'omd.site_exists': Mock(return_value=True),
            'omd.remove_site': remove_site,
        }

        result = module.site_absent('mysite')

        remove_site.assert_called_once_with('mysite')
        self.assertTrue(result['result'])
        self.assertEqual(result['comment'], 'Site mysite removed')

    def test_site_absent_dry_run_does_not_remove(self):
        module = self.load_module()
        module.__opts__ = {'test': True}
        remove_site = Mock()
        module.__salt__ = {
            'omd.site_exists': Mock(return_value=True),
            'omd.remove_site': remove_site,
        }

        result = module.site_absent('mysite')

        remove_site.assert_not_called()
        self.assertIsNone(result['result'])
        self.assertEqual(result['comment'], 'Site mysite removed')

    def test_site_present_updates_version_and_config(self):
        module = self.load_module()
        update_site = Mock()
        site_stop = Mock()
        site_set_config_value = Mock()
        site_start = Mock()
        module.__salt__ = {
            'omd.site_exists': Mock(return_value=True),
            'omd.site_version': Mock(return_value='2.1'),
            'omd.update_site': update_site,
            'omd.create_site': Mock(),
            'omd.site_is_config_value': Mock(return_value=False),
            'omd.config_show_value': Mock(return_value='off'),
            'omd.site_stop': site_stop,
            'omd.site_set_config_value': site_set_config_value,
            'omd.site_start': site_start,
        }

        result = module.site_present('mysite', version='2.2', params={'LIVESTATUS_TCP': 'on'})

        update_site.assert_called_once_with('mysite', '2.2')
        site_stop.assert_called_once_with('mysite')
        site_set_config_value.assert_has_calls([call('mysite', 'LIVESTATUS_TCP', 'on')])
        site_start.assert_called_once_with('mysite')
        self.assertEqual(result['changes']['diff']['detailed-changes']['old'], {'LIVESTATUS_TCP': 'off'})
        self.assertEqual(result['changes']['diff']['detailed-changes']['new'], {'LIVESTATUS_TCP': 'on'})

    def test_site_present_reports_no_changes_when_version_and_params_match(self):
        module = self.load_module()
        update_site = Mock()
        create_site = Mock()
        module.__salt__ = {
            'omd.site_exists': Mock(return_value=True),
            'omd.site_version': Mock(return_value='2.2'),
            'omd.update_site': update_site,
            'omd.create_site': create_site,
            'omd.site_is_config_value': Mock(return_value=True),
            'omd.config_show_value': Mock(),
            'omd.site_stop': Mock(),
            'omd.site_set_config_value': Mock(),
            'omd.site_start': Mock(),
        }

        result = module.site_present('mysite', version='2.2', params={'LIVESTATUS_TCP': 'on'})

        update_site.assert_not_called()
        create_site.assert_not_called()
        self.assertEqual(result['changes'], {})
        self.assertEqual(
            result['comment'],
            'OMD site mysite already exists with defined version: 2.2 and specified parameters',
        )

    def test_site_present_dry_run_new_site_skips_config_queries(self):
        module = self.load_module()
        module.__opts__ = {'test': True}
        create_site = Mock()
        site_is_config_value = Mock(side_effect=AssertionError('must not be called for non-existing dry-run site'))
        config_show_value = Mock(side_effect=AssertionError('must not be called for non-existing dry-run site'))
        module.__salt__ = {
            'omd.site_exists': Mock(return_value=False),
            'omd.site_version': Mock(),
            'omd.update_site': Mock(),
            'omd.create_site': create_site,
            'omd.site_is_config_value': site_is_config_value,
            'omd.config_show_value': config_show_value,
            'omd.site_stop': Mock(),
            'omd.site_set_config_value': Mock(),
            'omd.site_start': Mock(),
        }

        result = module.site_present('mysite', version='2.2', params={'LIVESTATUS_TCP': 'on'})

        create_site.assert_not_called()
        site_is_config_value.assert_not_called()
        config_show_value.assert_not_called()
        self.assertIsNone(result['result'])
        self.assertEqual(result['changes']['diff']['actions'], ['Create new Site'])


if __name__ == '__main__':
    unittest.main()