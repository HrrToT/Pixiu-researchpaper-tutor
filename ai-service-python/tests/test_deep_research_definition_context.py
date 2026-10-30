from copy import deepcopy
import json

import pytest

from services.deep_research.shared_modules import definition_premise
from services.deep_research.synthesis_evidence import order_premises,fit_premises

PREFIX='We implement the ABC with a shallow MLP. '
QUOTE='This maps the hash encoding to an output containing translation and quaternion rotation.'
TEXT='Paper: ABC everywhere\nContent:\n'+PREFIX+QUOTE


def fixture():
    row={'evidenceId':'definition','sourceId':'s','sourceWorkId':'p','sourceVersionId':'v','contentHash':'h',
        'accessLevel':'fulltext','quote':QUOTE,'sourceContext':TEXT,'location':{'section':'Method'},
        'verification':{'literal':'passed','semantic':'unchecked'}}
    source={'sourceId':'s','workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext',
            'pages':[{'text':TEXT}]}
    return row,source


def test_literal_antecedent_is_retained_only_from_exact_owned_read_text():
    row,source=fixture();before=deepcopy((row,source))
    rank,context=definition_premise(row,'ABC',[source])
    assert rank>0 and context['before'].strip()==PREFIX.strip() and context['before'] in TEXT
    assert context['after']=='' and (row,source)==before


@pytest.mark.parametrize('field',['sourceId','workId','versionId','contentHash','accessLevel'])
def test_foreign_or_changed_read_identity_cannot_supply_antecedent(field):
    row,source=fixture();source[field]='different'
    assert definition_premise(row,'ABC',[source])==(0,None)


@pytest.mark.parametrize('variant',['duplicate_source','duplicate_quote','header_only','different_text','long','dict_context','profiling','table'])
def test_ambiguous_nonliteral_distant_or_table_context_never_becomes_module_definition(variant):
    row,source=fixture();sources=[source]
    if variant=='duplicate_source':sources.append(deepcopy(source))
    if variant=='duplicate_quote':row['sourceContext']=source['pages'][0]['text']=TEXT+' '+QUOTE
    if variant=='header_only':row['sourceContext']=source['pages'][0]['text']='Paper: ABC\nContent:\nA generic MLP. '+QUOTE
    if variant=='different_text':source['pages'][0]['text']='Another source.'
    if variant=='long':row['sourceContext']=source['pages'][0]['text']='ABC '+('x'*700)+'. '+QUOTE
    if variant=='dict_context':row['sourceContext']={'before':PREFIX}
    if variant=='profiling':row['location']['section']='Rendering profiling'
    if variant=='table':row['location']['table']='table1'
    assert definition_premise(row,'ABC',sources)==(0,None)


def test_actual_anaphoric_shape_outranks_keyword_profiling_and_context_is_atomic():
    row,source=fixture()
    table={**row,'evidenceId':'profiling','sourceId':'table','quote':'ABC query and rotation overhead.',
        'location':{'section':'Table 7. Rendering profiling'},'sourceContext':''}
    plan=[{'obligations':[{'obligationId':'o','question':'两组固定相同ABC结果','requiredSources':['p']}]}]
    before=deepcopy((row,source,plan))
    old,_=order_premises([table,row],plan,module_intents=True)
    assert old[0]['evidenceId']=='profiling'
    new,bundles=order_premises([table,row],plan,module_intents=True,definition_context=True,read_sources=[source])
    assert new[0]==row and bundles[0]['requiredContextByEvidenceId']['definition']['before'].strip()==PREFIX.strip()
    contexts=bundles[0]['requiredContextByEvidenceId']
    render=lambda rows:json.dumps(rows,separators=(',',':'))
    _,supplied,missing=fit_premises(new,render,bundles,required_contexts=contexts)
    assert not missing and supplied[0]['sourceContextRequired'] is True
    assert supplied[0]['sourceContext']['before'].strip()==PREFIX.strip()
    assert not supplied[0].get('contextOmitted') and supplied[0]['quote']==QUOTE
    # If only the bare quote would fit, report the whole missing premise. Do not
    # strip the antecedent and call the module definition present.
    bare={**row,'sourceContext':{},'contextOmitted':True}
    cap=len(render([bare]).encode())+1
    _,tiny,missing=fit_premises([row],render,[bundles[0]],max_bytes=cap,required_contexts=contexts)
    assert not tiny and missing==[bundles[0]]
    assert (row,source,plan)==before


def test_old_fitter_remains_allowed_to_drop_optional_context():
    row,_=fixture();render=lambda rows:json.dumps(rows,separators=(',',':'))
    bare={**row,'sourceContext':{},'contextOmitted':True};cap=len(render([bare]).encode())+1
    _,supplied,missing=fit_premises([row],render,[{'evidenceIds':['definition']}],max_bytes=cap)
    assert not missing and supplied[0]['contextOmitted'] and not supplied[0]['sourceContext']
