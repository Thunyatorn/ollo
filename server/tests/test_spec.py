"""Spec traceability: docs/SPEC.md and the tests must agree (see "How this spec is used")."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / 'docs' / 'SPEC.md'
TESTS = Path(__file__).resolve().parent


def requirements():
    """{id: {'status': str, 'verify': [refs]}} from '#### ID · Title' sections."""
    reqs, current = {}, None
    for line in SPEC.read_text().splitlines():
        heading = re.match(r'^#### ([A-Z]+-\d+) · ', line)
        if heading:
            current = heading.group(1)
            assert current not in reqs, f'Duplicate requirement ID {current}'
            reqs[current] = {'status': None, 'verify': []}
        elif current and line.startswith('- **Status:**'):
            reqs[current]['status'] = line.split('**Status:**')[1].split()[0]
        elif current and line.startswith('- **Verify:**'):
            reqs[current]['verify'] = re.findall(r'`([\w./-]+(?:::\w+)?)`', line)
    return reqs


def test_functions():
    return {f'{path.name}::{name}' for path in TESTS.glob('test_*.py') if path.name != 'test_spec.py'
            for name in re.findall(r'^def (test_\w+)', path.read_text(), re.M)}


def test_spec_requirements_and_tests_agree():
    reqs, tests = requirements(), test_functions()
    assert reqs, 'No requirements parsed from docs/SPEC.md'
    assert all(r['status'] in ('Done', 'Planned') for r in reqs.values()), {k: r['status'] for k, r in reqs.items()}
    claimed = set()
    for rid, req in reqs.items():
        for ref in req['verify']:
            if ref.startswith('scripts/'):
                assert (ROOT / ref).is_file(), f'{rid} names missing script {ref}'
            else:
                assert ref in tests, f'{rid} names missing test {ref}'
                claimed.add(ref)
        if req['status'] == 'Done':
            assert req['verify'], f'{rid} is Done but names no verifying test'
    orphans = sorted(tests - claimed)
    assert not orphans, f'Tests not claimed by any requirement in docs/SPEC.md: {orphans}'
