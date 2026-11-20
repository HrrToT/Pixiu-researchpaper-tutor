"""The renderer's directional header is not necessarily the packet column key."""
from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.table_bindings import reference_guidance, REFERENCE_GUIDANCE
from services.deep_research.verification import verify_claims
from services.deep_research.repair import _prepare_repair
from test_deep_research_table_bindings import fixture


@pytest.mark.parametrize('version', [None, True, False, 0, 1, 2, 3, '4', 5])
def test_legacy_guidance_is_unchanged(version):
    assert reference_guidance(version) == REFERENCE_GUIDANCE


@pytest.mark.parametrize('kind', ['reported', 'inference', 'proposal', 'hypothesis'])
@pytest.mark.parametrize('metric', ['FPS↑', 'FPS↓', 'Other'])
def test_new_contract_never_repairs_a_wrong_packet_key_or_approves_it(kind, metric):
    ev, c = fixture(); c['kind'] = kind; c['tableBindings'][0]['metric'] = metric
    before = deepcopy((ev,c)); checker = Mock()
    out = verify_claims([c], [ev], checker, table_references_version=4)
    assert out['rejected'][0]['reason'] == 'unverified_table_cell'
    checker.assert_not_called()
    assert (ev,c) == before


def test_packet_key_with_its_own_arrow_stays_exact_and_unresolved_is_not_passed():
    ev, c = fixture(); c['kind']='inference'
    ev['tableData']['groups'][0][1][0]='FPS↑';c['tableBindings'][0]['metric']='FPS↑'
    checker=Mock(return_value=[{'claimId':'c','status':'unresolved','reason':'not independently checked'}])
    assert not verify_claims([c],[ev],checker,table_references_version=4)['accepted']
    checker.assert_called_once()
    c['tableBindings'][0]['metric']='FPS'
    checker.reset_mock()
    assert verify_claims([c],[ev],checker,table_references_version=4)['rejected'][0]['reason']=='unverified_table_cell'
    checker.assert_not_called()


@pytest.mark.parametrize('compact', [False, True])
def test_actual_repair_prompt_distinguishes_canonical_key_without_changing_permissions(compact):
    ev,c=fixture();c['kind']='inference';c['tableBindings'][0]['metric']='FPS↑'
    before=deepcopy((ev,c))
    rejected=verify_claims([c],[ev],table_references_version=4)
    old=_prepare_repair({'claims':[c]},rejected,[ev],'核查表格，200字以内',
        fact_redraft=True,concise_factual=True,declared_table_refs=True,
        source_aware_redraft=compact,compact_source_repair=compact)
    new=_prepare_repair({'claims':[c]},rejected,[ev],'核查表格，200字以内',
        fact_redraft=True,concise_factual=True,declared_table_refs=4,
        source_aware_redraft=compact,compact_source_repair=compact)
    assert new['prompt'].count(reference_guidance(4)) == 1
    if not compact: assert REFERENCE_GUIDANCE in old['prompt']
    assert new['allowed']==old['allowed'] and (ev,c)==before
    assert '"metrics":["FPS","Mem"]' in new['prompt']
