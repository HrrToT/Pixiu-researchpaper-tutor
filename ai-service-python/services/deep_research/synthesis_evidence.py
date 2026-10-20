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
    return type(version) is int and version in (1,2)


def result_role(row):
    text=str(row.get('quote',''))+'\n'+str(row.get('location',{}).get('section',''))
    if re.search(r'profil\w*|overhead|渲染剖析|渲染分解',text,re.I):
        return 'profiling'
    if re.search(r'quantitative comparison|benchmark comparison|定量比较',text,re.I):
        return 'quantitative_comparison'
    return 'unspecified'


def order_premises(evidence,plan,limit=20, *, membership_intents=False):
    obligations={o['obligationId']:o for item in plan for o in item.get('obligations',[])}
    rows=[e for e in evidence if e.get('verification',{}).get('literal')=='passed']
    works=list(dict.fromkeys(e.get('sourceWorkId') for e in rows))
    chosen=[];seen=set();bundles=[]
    for oid,view,intent in criterion_targets(obligations,membership_intents=membership_intents):
        for source in view.get('requiredSources') or works:
            own=[e for e in rows if source in {e.get('sourceWorkId'),e.get('sourceVersionId'),e.get('ownerMaterialId')}]
            def score(row):
                context=surrounding_context(row)
                text=row.get('quote','')+'\n'+str(context)
                value=operation_score(text,str(row.get('location',{}).get('section','')),intent,operational=True)
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
            measurement=isinstance(intent,str) and intent.startswith('measurement:')
            if (intent in {'operation','training','temporal'} or measurement) and lead.get('sourceId'):
                sibling=next((e for e in ranked[1:] if e.get('sourceId')==lead['sourceId']
                              and e['quote']!=lead['quote'] and (score(e)[0]>0 or measurement and re.search(
                                  r'\b(?:GPU|NVIDIA|RTX|resolution|hardware|timing)\b|硬件|分辨率',e['quote'],re.I))),None)
                if sibling:
                    bundle.append(sibling)
            ids=[e['evidenceId'] for e in bundle]
            bundles.append({'obligationId':oid,'criterionId':view['completionCriteria'][0].get('criterionId','whole_obligation'),
                            'requirement':view['question'],'source':source,'evidenceIds':ids})
            for row in bundle:
                if row['evidenceId'] not in seen:
                    chosen.append(row);seen.add(row['evidenceId'])
    chosen.extend(row for row in rows if row['evidenceId'] not in seen)
    return chosen[:limit],bundles


def fit_premises(rows,render,bundles,max_bytes=24000, *, omit_optional_table_data=False):
    """Keep whole premise bundles before optional rows/context; no quote clipping."""
    if len(render([]).encode('utf8'))>max_bytes:
        raise ValueError('prompt_fixed_content_too_large')
    compact=[]
    for row in rows:
        item=deepcopy(row)
        if item.get('sourceContext'):
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
        restored=[*selected];restored[i]=deepcopy(row)
        if originals[row['evidenceId']].get('sourceContext'):
            restored[i]['sourceContext']=originals[row['evidenceId']]['sourceContext']
            restored[i].pop('contextOmitted',None)
        if len(render(restored).encode('utf8'))<=max_bytes:
            selected=restored
    return render(selected),selected,missing
