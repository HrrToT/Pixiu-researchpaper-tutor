"""Input capacity changes never transfer evidence or scientific authority."""
from copy import deepcopy
import json

import pytest

from services.deep_research.factual_prompt import enabled, scope_guidance
from services.deep_research.factual_template import build
from services.deep_research.repository import DeepResearchRepository


def template(record, kind='paper_comparison'):
    return build(record, '比较两种方法；不能把不同设置的时间当方法加速。限500字。', kind,
        500, 5, ['比较结论', '选用条件'],
        [{'obligationId':'o', 'question':'比较', 'requiredSources':['paper-v1'],
          'completionCriteria':[{'criterionId':'human', 'requirement':'保留原始条件',
                                 'responseType':'explanation'}]}],
        {'P1':{'workId':'paper', 'title':'Paper'}}, 'EVIDENCE', 'TABLES', drafting_schema=True)


@pytest.mark.parametrize('version', [None, True, False, 0, 4, '1'])
def test_only_strict_opt_in_changes_factual_prompts_and_legacy_text_stays_exact(version):
    legacy = {'factualScopeContractVersion':4, 'comparisonReasoningContractVersion':4}
    assert not enabled({'factualPromptContractVersion':version}, 'paper_comparison')
    assert template({**legacy, 'factualPromptContractVersion':version}) == template(legacy)
    assert not enabled({'factualPromptContractVersion':1}, 'experiment_design')
    assert template({**legacy, 'factualPromptContractVersion':1}, 'experiment_design') == template(legacy, 'experiment_design')


def test_compact_template_keeps_frozen_ids_exact_schema_and_comparison_boundaries():
    record={'factualPromptContractVersion':1, 'scopeExpressionContractVersion':4,
            'tableReferencesContractVersion':4, 'factualScopeContractVersion':4,
            'comparisonReasoningContractVersion':4, 'claimCheckContractVersion':9,
            'tableIdentityContextContractVersion':2}
    before=deepcopy(record); prompt=template(record)
    assert '"obligationId":"o"' in prompt and '"criterionId":"human"' in prompt
    assert '保留原始条件' in prompt and 'paper-v1' in prompt
    assert 'scopeExpression' in prompt and 'draftingBasis' in prompt
    assert 'premiseStatus' in prompt and 'scopeDecision' in prompt
    assert 'exact member of tableData.groups[groupIndex][1]' in prompt
    assert 'Whole systems may intentionally use different hardware' in prompt
    assert 'Unknown alignment is not a demonstrated difference' in prompt
    assert 'Selected excerpts are not the whole pool' in prompt
    assert 'independent factual, scope, numeric and final-answer coverage checks' in prompt
    assert record==before
    assert len(prompt.encode()) < len(template({**record, 'factualPromptContractVersion':None}).encode())


@pytest.mark.parametrize('version', [1, 2, 3, 4])
def test_boundary_shape_preserves_quantifiers_private_text_and_quantity_rules(version):
    prompt=scope_guidance(version)
    assert 'kind="inference",text="",conditions={}' in prompt
    assert 'observedSettings' in prompt and 'notEstablished' in prompt
    assert 'rendered text counts toward' in prompt and 'never negation' in prompt
    assert ('"quantifier":"all|exists"' in prompt) is (version>=2)
    assert ('quantity and unit are explicitly anchored' in prompt) is (version==4)


def node_capture(version):
    from services.deep_research.graph import make_synthesize_node
    from services.deep_research.verification import make_evidence
    rows=[]
    packet={'groups':[['Benchmark',['PSNR']]], 'rows':[[3,'Own method',['27.3']]]}
    for work in ('left','right'):
        source={'workId':work,'versionId':work+'-v1','contentHash':work,'accessLevel':'fulltext'}
        for index,quote in enumerate(('We fuse measured depth to reconstruct a surface.',
                                      'Table: Own method PSNR 27.3.',
                                      'All measurements use the stated GPU and resolution.')):
            row=make_evidence(source,quote,quote,location={'page':index+1},obligation_ids=['o'])
            if index==1:row['tableData']=deepcopy(packet)
            rows.append(row)
    record={'factualPromptContractVersion':version, 'synthesisEvidenceContractVersion':6,
        'question':'比较两篇方法的几何表示、渲染质量与实验设置，限500字。', 'budget':{},
        'state':{'outputKind':'paper_comparison', 'evidence':rows, 'plan':[{'itemId':'i','obligations':[
            {'obligationId':'o','question':'比较方法与设置','requiredSources':['left','right'],
             'completionCriteria':[{'criterionId':'c','requirement':'比较方法与设置','responseType':'comparison'}]}]}]}}
    original=deepcopy(record);sent=[]
    def update(rid,change,**kwargs):
        nonlocal record
        record=change(record);return deepcopy(record)
    def invoke(rid,node,prompt,options,**kwargs):
        assert node=='synthesize';sent.append(prompt)
        # No canned positive claim can grant a scientific acceptance.
        return {'content':json.dumps({'sections':[],'claims':[]})}
    make_synthesize_node(invoke,update)({'run_id':'r'})
    assert len(sent)==1 and original['state']['evidence']==rows
    return sent[0],record,original


def test_actual_synthesis_encodes_exact_evidence_and_keeps_each_table_source_local():
    from services.deep_research.evidence_wire import decode
    new,record,original=node_capture(1);old,_,_=node_capture(None)
    parse=json.JSONDecoder().raw_decode
    rows=decode(parse(new.split('Evidence summaries:\n',1)[1])[0])
    legacy_rows=parse(old.split('Evidence summaries:\n',1)[1])[0]
    assert rows==legacy_rows  # Every quote, ID, context, packet and permission retained.
    tables=parse(new.split('Shared table packets (tableDataRef resolves ONLY for its own source/evidence row):\n',1)[1])[0]
    own={row['source']:row['tableDataRef'] for row in rows if row.get('tableDataRef')}
    assert len(own)==2 and len(set(own.values()))==2
    assert all(tables[tid]['source']==source for source,tid in own.items())
    assert {r['accessLevel'] for r in rows}=={'fulltext'}
    assert len(new.encode())<=24000 and len(rows)==6
    assert record['state']['evidence']==original['state']['evidence']
    assert not record['state'].get('verifiedReport')


@pytest.mark.parametrize('replacement', [None, True, '1', 2])
def test_saved_prompt_policy_is_immutable_even_for_equal_boolean(tmp_path,replacement):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','factualPromptContractVersion':1})
    before=repo.require_run('r')
    with pytest.raises(ValueError,match='Immutable run field changed'):
        repo.update_run('r',lambda r:{**r,'factualPromptContractVersion':replacement})
    assert repo.require_run('r')==before


def test_historical_or_unknown_run_cannot_switch_to_the_new_prompt(tmp_path):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t'})
    before=repo.require_run('r')
    with pytest.raises(ValueError,match='Immutable run field changed'):
        repo.update_run('r',lambda r:{**r,'factualPromptContractVersion':1})
    assert repo.require_run('r')==before


def test_v2_post_guidance_is_new_only_and_does_not_change_saved_v1_text():
    from services.deep_research.factual_prompt import post_guidance
    for version in (None,True,1,4,'2'):
        assert post_guidance({'factualPromptContractVersion':version},'points','legacy exact')=='legacy exact'
    assert 'conditions={}' in post_guidance({'factualPromptContractVersion':2},'points','legacy')
    assert 'server labels' in post_guidance({'factualPromptContractVersion':2},'access','legacy')
    assert 'proposal' in post_guidance({'factualPromptContractVersion':2},'semantics','legacy')
    assert 'never requested scope' in post_guidance({'factualPromptContractVersion':2},'preservation','legacy')


def test_v2_requirement_packet_roundtrips_all_frozen_criteria_and_source_requirements():
    from services.deep_research.evidence_wire import decode
    prompt=template({'factualPromptContractVersion':2})
    packet=json.JSONDecoder().raw_decode(prompt.split('Encoding changes no scope.\n',1)[1])[0]
    requirements=decode(packet)
    assert requirements==[{'obligationId':'o','question':'比较','requiredSources':['paper-v1'],
        'completionCriteria':[{'criterionId':'human','requirement':'保留原始条件','responseType':'explanation'}],
        'requiredSourceAliases':[]}]
    # A bare work registry must not guess a revision mapping. An actual owned
    # version identity can supply the reversible alias without changing scope.
    owned=template({'factualPromptContractVersion':2,'state':{'evidence':[
        {'sourceWorkId':'paper','sourceVersionId':'paper-v1'}]}})
    packet=json.JSONDecoder().raw_decode(owned.split('Encoding changes no scope.\n',1)[1])[0]
    assert decode(packet)==[{**requirements[0],'requiredSourceAliases':['P1']}]
