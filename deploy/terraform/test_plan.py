"""The deployment guard must reject replacement as well as outright deletion."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

GUARD = Path(__file__).resolve().parents[2] / 'scripts' / 'check-terraform-plan.py'


class PlanGuardTests(unittest.TestCase):
    def check(self, actions):
        return subprocess.run([sys.executable, str(GUARD)], input=json.dumps({'resource_changes': [{'address': 'production.dashboard', 'change': {'actions': actions}}]}), text=True, capture_output=True)

    def test_update_allowed(self):
        self.assertEqual(self.check(['update']).returncode, 0)

    def test_delete_rejected(self):
        self.assertNotEqual(self.check(['delete']).returncode, 0)

    def test_replacement_rejected(self):
        self.assertNotEqual(self.check(['create', 'delete']).returncode, 0)


if __name__ == '__main__':
    unittest.main()
