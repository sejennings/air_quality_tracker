"""Fail deployment before applying a plan that would remove production resources."""
import json
import sys

plan = json.load(sys.stdin)
changes = plan.get('resource_changes', [])
unsafe = [change['address'] for change in changes if 'delete' in change['change']['actions']]
if unsafe:
    raise SystemExit('Refusing destructive Terraform plan: ' + ', '.join(unsafe))
counts = {action: sum(action in change['change']['actions'] for change in changes) for action in ('create', 'update', 'delete')}
print('Plan verified; action counts: ' + json.dumps(counts))
