"""Fail closed if the intended GHCR package already has non-private visibility."""
import json
import os
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def get(path):
    request = Request('https://api.github.com/' + path, headers={
        'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    with urlopen(request, timeout=30) as response:
        return json.load(response)


repo = get('repos/' + os.environ['GITHUB_REPOSITORY'])
owner = repo['owner']['login']
kind = 'orgs' if repo['owner']['type'] == 'Organization' else 'users'
package = quote('air-quality-tracker-runtime', safe='')
try:
    info = get(f'{kind}/{owner}/packages/container/{package}')
except HTTPError as error:
    raise SystemExit("Package privacy could not be verified; publishing is disabled") from error
else:
    if info['visibility'] != 'private':
        raise SystemExit('Refusing to publish: package visibility is not private')
    print('Verified private GHCR package')


