"""Criterion/source premise allocation inside the existing synthesis window.

Selections and role hints do not approve relevance, provenance or scientific
inference. Original evidence, exact quotations and permissions remain intact.
"""
from copy import deepcopy
import re
from services.deep_research.criterion_sources import criterion_targets
from services.deep_research.method_intent import operation_score
from services.deep_research.selection import surrounding_context


def enabled(record):
    version=record.get('synthesisEvidenceContractVersion')
    return type(version) is int and version in (1,2,3,4,5,6)


def result_role(row):
    text=str(row.get('quote',''))+'\n'+str(row.get('location',{}).get('section',''))
    if re.search(r'profil\w*|overhead|渲染剖析|渲染分解',text,re.I):
        return 'profiling'
    if re.search(r'quantitative comparison|benchmark comparison|定量比较',text,re.I):
        return 'quantitative_comparison'
    return 'unspecified'


def order_premises(evidence,plan,limit=20, *, membership_intents=False,module_intents=False,condition_intents=False,
                   definition_context=False,read_sources=(),operational_context=False):
    obligations={o['obligationId']:o for item in plan for o in item.get('obligations',[])}
    rows=[e for e in evidence if e.get('verification',{}).get('literal')=='passed']
    works=list(dict.fromkeys(e.get('sourceWorkId') for e in rows))
    chosen=[];seen=set();bundles=[]
    for oid,view,intent in criterion_targets(obligations,membership_intents=membership_intents,module_intents=module_intents,
                                           condition_intents=condition_intents):
        for source in view.get('requiredSources') or works:
            own=[e for e in rows if source in {e.get('sourceWorkId'),e.get('sourceVersionId'),e.get('ownerMaterialId')}]
            from services.deep_research.operational_premises import requested_operation
            active_intent=('operation' if operational_context and intent is None and requested_operation(view) else intent)
            def score(row):
                context=surrounding_context(row)
                text=row.get('quote','')+'\n'+str(context)
                value=operation_score(text,str(row.get('location',{}).get('section','')),active_intent,operational=True)
                if module_intents and isinstance(intent,str) and intent.startswith('shared_module:'):
                    from services.deep_research.shared_modules import definition_score
                    if definition_context:
                        from services.deep_research.shared_modules import definition_premise
                        value=definition_premise(row,intent.split(':',1)[1],read_sources)[0]*30
                    else:
                        value=definition_score(row.get('quote',''),intent.split(':',1)[1])*30
                if intent=='operation' and row.get('extractionKind')=='literal_method_equation':
                    value+=30
                if membership_intents and intent=='data_membership' and row.get('extractionKind')=='literal_dataset_member_rows':
                    value+=30
                if isinstance(intent,str) and intent.startswith('measurement:') and re.search(r'主表|\bmain (?:results? )?table\b',view['question'],re.I):
                    role=result_role(row)
                    value-=20 if role=='profiling' else 0
                # Unclassified explanations still prioritize a method premise,
                # not a repeated packet of numerical cells.
                return (value,not bool(row.get('tableData')),len(set(re.findall(r'[A-Za-z]{4,}',view['question'].lower()))
                    & set(re.findall(r'[A-Za-z]{4,}',row.get('quote','').lower()))))
            ranked=sorted(own,key=score,reverse=True)
            if not ranked:
                continue
            lead=ranked[0];bundle=[lead]
            method_contexts={};used_method_bundle=False
            if operational_context and active_intent=='operation':
                from services.deep_research.operational_premises import operational_bundle
                method_bundle,method_contexts=operational_bundle(rows,read_sources,oid,source)
                if method_bundle:bundle=method_bundle;used_method_bundle=True
            measurement=isinstance(intent,str) and intent.startswith('measurement:')
            if not used_method_bundle and (intent in {'operation','training','temporal'} or measurement
                    or condition_intents and isinstance(intent,str) and intent.startswith('data_condition:')) and lead.get('sourceId'):
                sibling=next((e for e in ranked[1:] if e.get('sourceId')==lead['sourceId']
                              and e['quote']!=lead['quote'] and (score(e)[0]>0 or measurement and re.search(
                                  r'\b(?:GPU|NVIDIA|RTX|resolution|hardware|timing)\b|硬件|分辨率',e['quote'],re.I))),None)
                if sibling:
                    bundle.append(sibling)
            ids=[e['evidenceId'] for e in bundle]
            contexts=dict(method_contexts)
            if definition_context and isinstance(intent,str) and intent.startswith('shared_module:'):
                from services.deep_research.shared_modules import definition_premise
                for e in bundle:
                    _,context=definition_premise(e,intent.split(':',1)[1],read_sources)
                    if context:contexts[e['evidenceId']]=context
            bundles.append({'obligationId':oid,'criterionId':(view.get('completionCriteria') or [{}])[0].get('criterionId','whole_obligation'),
                            'requirement':view['question'],'source':source,'evidenceIds':ids,
                            **({'requiredContextByEvidenceId':contexts} if contexts else {})})
            for row in bundle:
                if row['evidenceId'] not in seen:
                    chosen.append(row);seen.add(row['evidenceId'])
    chosen.extend(row for row in rows if row['evidenceId'] not in seen)
    return chosen[:limit],bundles


def fit_premises(rows,render,bundles,max_bytes=24000, *, omit_optional_table_data=False,required_contexts=None):
    """Keep whole premise bundles before optional rows/context; no quote clipping."""
    if len(render([]).encode('utf8'))>max_bytes:
        raise ValueError('prompt_fixed_content_too_large')
    compact=[]
    required_contexts=required_contexts or {}
    for row in rows:
        item=deepcopy(row)
        if row['evidenceId'] in required_contexts:
            item['sourceContext']=deepcopy(required_contexts[row['evidenceId']])
            item['sourceContextRequired']=True
            item.pop('contextOmitted',None)
        elif item.get('sourceContext'):
            item['sourceContext']={};item['contextOmitted']=True
        compact.append(item)
    by_id={row['evidenceId']:row for row in compact};selected=[];seen=set();missing=[]
    for bundle in bundles:
        ids=bundle['evidenceIds']
        if any(eid not in by_id for eid in ids):
            missing.append(bundle);continue
        additions=[by_id[eid] for eid in ids if eid not in seen]
        if len(selected)+len(additions)<=20 and len(render([*selected,*additions]).encode('utf8'))<=max_bytes:
            selected.extend(additions);seen.update(ids)
        else:
            trial=deepcopy([*selected,*additions])
            if omit_optional_table_data:
                for row in trial:
                    if row.get('tableDataRef'):
                        row.pop('tableDataRef');row['tableDataOmitted']=True
            if (omit_optional_table_data and len(trial)<=20
                    and len(render(trial).encode('utf8'))<=max_bytes):
                selected=trial;seen.update(ids)
            else:
                missing.append(bundle)
    for row in compact:
        if row['evidenceId'] not in seen and len(selected)<20 and len(render([*selected,row]).encode('utf8'))<=max_bytes:
            selected.append(row);seen.add(row['evidenceId'])
    originals={row['evidenceId']:row for row in rows}
    for i,row in enumerate(selected):
        if row['evidenceId'] in required_contexts:
            continue
        restored=[*selected];restored[i]=deepcopy(row)
        if originals[row['evidenceId']].get('sourceContext'):
            restored[i]['sourceContext']=originals[row['evidenceId']]['sourceContext']
            restored[i].pop('contextOmitted',None)
        if len(render(restored).encode('utf8'))<=max_bytes:
            selected=restored
    return render(selected),selected,missing
