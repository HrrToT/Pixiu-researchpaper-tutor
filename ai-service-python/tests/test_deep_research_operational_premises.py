from copy import deepcopy
import hashlib
import json

import pytest

from services.deep_research.operational_premises import operational_bundle,requested_operation
from services.deep_research.synthesis_evidence import order_premises,fit_premises


def fixture():
    texts=[
        'However, we sample new positions from selected high-gradient points. We select gradients above 0.002. '
        'For each selected point, draw X ~ N(mu, 3*Sigma).',
        'For each selected point, copy its scale. Set opacity to 0.2 and rotation to [1,0,0,0]. '
        'After creation, optimize only the new parameters. Keep all original states fixed.',
        'After spawning, we optimize positions and prune points. Set threshold to 0.02 at each epoch. '
        'Split scales to 70% of their parent. Discard the low-opacity points.']
    quotes=['We select gradients above 0.002.','Set opacity to 0.2 and rotation to [1,0,0,0].',
        'Set threshold to 0.02 at each epoch.']
    sources=[];rows=[]
    for i,(body,quote) in enumerate(zip(texts,quotes),10):
        text='Paper: Example\nContent:\n'+body
        s={'sourceId':f'p-v{"a"*16}-chunk-{i}','workId':'p','ownerMaterialId':'p','versionId':'v',
            'contentHash':hashlib.sha256(text.encode()).hexdigest(),'accessLevel':'fulltext',
            'text':text,'pages':[{'text':text}],'location':{'chunk':i,'section':'Method'},'obligationIds':['o']}
        e={'evidenceId':f'e{i}','sourceId':s['sourceId'],'sourceWorkId':'p','sourceVersionId':'v',
            'contentHash':s['contentHash'],'accessLevel':'fulltext','quote':quote,'sourceContext':text,
            'location':deepcopy(s['location']),'verification':{'literal':'passed','semantic':'unchecked'},'obligationIds':['o']}
        sources.append(s);rows.append(e)
    return rows,sources


def test_procedural_chain_keeps_three_own_quotes_and_exact_following_rules_without_mutation():
    rows,sources=fixture();before=deepcopy((rows,sources))
    bundle,contexts=operational_bundle(rows,sources,'o','p')
    assert [r['evidenceId'] for r in bundle]==['e10','e11','e12']
    assert contexts['e10']['after']==' For each selected point, draw X ~ N(mu, 3*Sigma).'
    assert 'only the new parameters' in contexts['e11']['after']
    assert '70%' in contexts['e12']['after']
    for row in bundle:
        assert contexts[row['evidenceId']]['after'] in row['sourceContext']
        assert contexts[row['evidenceId']]['before']==''
    assert (rows,sources)==before


@pytest.mark.parametrize('field',['sourceId','workId','ownerMaterialId','versionId','contentHash',
    'accessLevel','chunk_bool','section','context','duplicate','table','literal','obligation','ambiguous_text'])
def test_unproven_predecessor_never_supplies_the_complete_chain(field):
    rows,sources=fixture()
    if field in ('sourceId','workId','ownerMaterialId','versionId','contentHash','accessLevel'):sources[0][field]='other'
    elif field=='chunk_bool':sources[0]['location']['chunk']=True
    elif field=='section':sources[0]['location']['section']='Other'
    elif field=='context':rows[0]['sourceContext']='an unrelated invented context'
    elif field=='duplicate':sources.append(deepcopy(sources[0]))
    elif field=='table':rows[0]['tableData']={'rows':['not a method']}
    elif field=='literal':rows[0]['verification']['literal']='unchecked'
    elif field=='obligation':rows[0]['obligationIds']=['other']
    else:sources[0]['text']='changed text without changing pages/hash'
    bundle,contexts=operational_bundle(rows,sources,'o','p')
    assert 'e10' not in [r['evidenceId'] for r in bundle]
    assert 'e10' not in contexts


def test_complete_long_sentence_becomes_capacity_gap_instead_of_silent_context_loss():
    rows,sources=fixture();suffix=' This rule includes '+('unaltered operands '*90)+'and ends here.'
    text=sources[1]['text']+suffix
    sources[1].update(text=text,pages=[{'text':text}],contentHash=hashlib.sha256(text.encode()).hexdigest())
    rows[1].update(sourceContext=text,contentHash=sources[1]['contentHash'])
    bundle,contexts=operational_bundle(rows,sources,'o','p')
    # First three complete sentences already cover this passage's two short
    # continuation sentences and the one long sentence; it must not be clipped.
    assert contexts['e11']['after'].endswith('and ends here.')
    render=lambda rs:json.dumps(rs,ensure_ascii=False,separators=(',',':'))
    _,selected,missing=fit_premises(bundle,render,[{'evidenceIds':[r['evidenceId'] for r in bundle]}],
        max_bytes=1000,required_contexts=contexts)
    assert missing and len(selected)<3


def test_explicit_procedure_allocates_method_before_incidental_high_overlap_result():
    rows,sources=fixture()
    other={**deepcopy(rows[0]),'evidenceId':'result','sourceId':'other',
        'quote':'The experiment design has better quality and speed.', 'sourceContext':'',
        'location':{'section':'Evaluation'}}
    plan=[{'obligations':[{'obligationId':'o','question':'Give an experiment design','requiredSources':['p'],
        'completionCriteria':[{'criterionId':'config','responseType':'procedure','requirement':'Give concrete initialization.'}]}]}]
    _,old=order_premises([other,*rows],plan,definition_context=True,read_sources=sources)
    new,bundles=order_premises([other,*rows],plan,definition_context=True,read_sources=sources,operational_context=True)
    assert old[0]['evidenceIds']!=['e10','e11','e12']
    assert bundles[0]['evidenceIds']==['e10','e11','e12'] and new[:3]==rows
    assert bundles[0]['requiredContextByEvidenceId']['e10']['after'].endswith('3*Sigma).')


@pytest.mark.parametrize('view,expected',[
    ({'question':'给出初始化','completionCriteria':[]},True),
    ({'question':'设计一个最小实验'},True),
    ({'question':'Explain inputs','completionCriteria':[{'responseType':'procedure'}]},True),
    ({'question':'识别一个场景'},False),({'question':'列出局限'},False)])
def test_only_operational_requirements_get_new_method_intent(view,expected):
    assert requested_operation(view) is expected
