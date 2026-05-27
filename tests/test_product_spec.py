import os
import pytest

def test_spec_contains_phase2():
    '''Verify that PRODUCT_SPEC.md includes the Phase 2 section.'''
    spec_path = os.path.join(os.path.dirname(__file__), '..', 'PRODUCT_SPEC.md')
    assert os.path.exists(spec_path), f'Spec file not found at {spec_path}'
    with open(spec_path) as f:
        content = f.read()
    assert '## Phase 2: Live Executor Integration' in content, 'Phase 2 section missing'
    assert 'NW-016' in content, 'NW-016 reference missing'

def test_spec_contains_executor_status_table():
    '''Verify that PRODUCT_SPEC.md includes the executor component status table.'''
    spec_path = os.path.join(os.path.dirname(__file__), '..', 'PRODUCT_SPEC.md')
    assert os.path.exists(spec_path), f'Spec file not found at {spec_path}'
    with open(spec_path) as f:
        content = f.read()
    assert '### Executor Component Status' in content, 'Executor component status section missing'
    assert '| Component | Status | Description |' in content, 'Table header missing'
    assert '| CloakBridge |' in content, 'CloakBridge row missing'
    assert '| Mode Switching |' in content, 'Mode Switching row missing'
    assert '| Phase Verification |' in content, 'Phase Verification row missing'
