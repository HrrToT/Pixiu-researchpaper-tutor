from copy import deepcopy

from services.deep_research.selection import balanced_sample, proposal_evidence_order


def test_requested_scene_and_actual_mechanism_precede_unrequested_benchmark_tables():
    rows = [
        {'evidenceId': 'b', 'sourceWorkId': 'paper', 'quote': 'Table caption: ExampleNet on another dataset'},
        {'evidenceId': 'c', 'sourceWorkId': 'paper', 'quote': 'Table caption: ExampleNet on target_scene'},
        {'evidenceId': 'm', 'sourceWorkId': 'paper', 'quote': 'While training the new component, update the old weights.',
         'conditions': {'stage': 'training'}},
        {'evidenceId': 'n', 'sourceWorkId': 'paper', 'quote': 'ExampleNet on a third dataset.'}]
    before = deepcopy(rows)
    ordered = proposal_evidence_order(rows, 'Design an ExampleNet experiment on target_scene.')
    assert [r['evidenceId'] for r in ordered][:2] == ['c', 'm']
    assert len(ordered) == len(rows) and rows == before
    assert {id(r) for r in ordered} == {id(r) for r in rows}


def test_common_paper_name_does_not_outvote_specific_target_or_bypass_paper_balance():
    rows = [{'evidenceId': str(i), 'sourceWorkId': 'a', 'quote': 'Table caption: ExampleNet results'} for i in range(4)]
    rows += [{'evidenceId': 'scene', 'sourceWorkId': 'a', 'quote': 'Table caption: ExampleNet on kitchen'},
             {'evidenceId': 'method', 'sourceWorkId': 'b', 'quote': 'Update a new parameter from its error.'}]
    ordered = proposal_evidence_order(rows, 'Design an ExampleNet experiment on kitchen.')
    balanced = balanced_sample(ordered, lambda r: r['sourceWorkId'], 2)
    assert [r['evidenceId'] for r in balanced] == ['scene', 'method']
