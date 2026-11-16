"""Opt-in graph adapter, preserving the shared definition and all failed attempts."""
from copy import deepcopy

from services.deep_research.contracts import DeepResearchError,digest


def _save(update,rid,key):
    def save(value):
        update(rid,lambda r:{**r,'state':{**r.get('state',{}),key:deepcopy(value)}},expected_revision=None)
    return save


def synthesize(record,rows,aliases,sources,tables,bundles,update,invoke):
    from services.deep_research.shared_experiment_generation import prepare,INSTRUCTIONS,NODE,MAX_INPUT
    from services.deep_research.shared_strings import input_text
    from services.deep_research.planning_transport import overhead_bytes
    from services.deep_research.synthesis_evidence import fit_premises
    from services.deep_research.design_drafting import synthesis_obligations
    from services.deep_research.request_context import effective_question
    rid=record['runId']; reverse={v:k for k,v in aliases.items()}
    wire_bundles=[{**b,'evidenceIds':[reverse.get(e,e) for e in b['evidenceIds']]} for b in bundles]
    required={e for b in wire_bundles for e in b['evidenceIds']}
    requirements=synthesis_obligations(record['state'].get('plan',[]))
    def data_for(selected):
        tids={row['tableDataRef'] for row in selected if row.get('tableDataRef')}
        return {'question':effective_question(record),'requirements':requirements,'sources':sources,
                'evidence':selected,'tables':{k:v for k,v in tables.items() if k in tids}}
    def render(selected):return INSTRUCTIONS+input_text(data_for(selected))
    # Preserve complete selected contexts; optional quotes cannot displace a
    # necessary context merely because they are shorter without it.
    _,selected,missing=fit_premises(rows,render,wire_bundles,max_bytes=MAX_INPUT-overhead_bytes(record,NODE),
                                    required_contexts={row['evidenceId']:row.get('sourceContext',{}) for row in rows})
    if missing or not selected:
        return {'error_code':'synthesis_evidence_capacity'}
    selected_aliases={row['evidenceId']:aliases[row['evidenceId']] for row in selected}
    domains=[m['domain'] for m in record['state'].get('metricDomains',[]) if isinstance(m,dict) and m.get('domain') in {'quality','storage','speed','memory'}]
    snapshot={'data':data_for(selected),'aliases':selected_aliases,'requiredDomains':sorted(set(domains))}
    prior=record['state'].get('sharedExperimentInput')
    if prior is not None and digest(prior)!=digest(snapshot):
        raise DeepResearchError('invalid_shared_experiment_input','已保存共享方案材料或目标已改变，不能重发。')
    _save(update,rid,'sharedExperimentInput')(snapshot)
    _save(update,rid,'sharedExperimentMaterialAllocation')({
        'requiredEvidenceIds':[aliases[e] for e in sorted(required)],
        'suppliedEvidenceIds':list(selected_aliases.values()),
        'optionalEvidenceIdsRetainedInRun':[aliases[row['evidenceId']] for row in rows if row['evidenceId'] not in selected_aliases],
        'allFrozenPremiseBundlesRetained':not missing,'scientificApproval':False})
    record=update(rid,lambda r:r,expected_revision=None)
    result=prepare(record,snapshot['data'],snapshot['aliases'],required_domains=snapshot['requiredDomains'],
        invoke=lambda node,prompt,opts:invoke(rid,node,prompt,opts,use_reserve=True),
        checkpoint=_save(update,rid,'sharedExperimentGeneration'))
    if result is None:return {'error_code':'budget_exhausted'}
    version='report_'+rid+'_shared_'+result['bindingDigest'][:16]
    update(rid,lambda r:{**r,'state':{**r['state'],'reportVersionId':version}},expected_revision=None)
    return {'report_version_id':version}


def verify(record,update,invoke):
    from services.deep_research.shared_experiment_review import prepare as science,review_slot
    from services.deep_research.shared_experiment_answer import prepare as answer,slot as answer_slot,claim_for
    from services.deep_research.shared_experiment_revision import prepare as repair
    rid=record['runId']; snapshot=record['state']['sharedExperimentInput']; data=snapshot['data'];aliases=snapshot['aliases']
    def current():return update(rid,lambda r:r,expected_revision=None)
    def run_science():
        r=current();return science(r,data,aliases,required_domains=snapshot['requiredDomains'],
            invoke=lambda node,prompt,opts:invoke(rid,node,prompt,opts,use_reserve=True),
            checkpoint=_save(update,rid,review_slot(r)))
    def run_answer():
        r=current();return answer(r,data,aliases,invoke=invoke,checkpoint=_save(update,rid,answer_slot(r)))
    reviewed=run_science(); release=None
    if reviewed.get('assessment',{}).get('complete'): release=run_answer()
    eligible=(reviewed['status']=='not_started_precheck' or reviewed.get('assessment',{}).get('valid') is True
              and reviewed['assessment']['complete'] is False or release is not None and release['repairEligible'])
    if eligible and 'sharedExperimentRevision' not in current()['state']:
        revised=repair(current(),data,aliases,required_domains=snapshot['requiredDomains'],
            invoke=lambda node,prompt,opts:invoke(rid,node,prompt,opts,use_reserve=True),
            checkpoint=_save(update,rid,'sharedExperimentRevision'))
        if revised['status']=='awaiting_scientific_review':
            reviewed=run_science();release=run_answer() if reviewed.get('assessment',{}).get('complete') else None
        else:release=None
    complete=release is not None and release['complete'] is True
    certificate={'complete':complete,'repairAttempted':'sharedExperimentRevision' in current()['state']}
    if complete:
        certificate.update(candidateDigest=release['candidate']['candidateDigest'],certificateDigest=release['certificateDigest'])
        claims=[claim_for(release['candidate'])];version='report_'+rid+'_shared_'+release['candidate']['candidateDigest'][:16]
    else:
        claims=[];version='report_'+rid+'_shared_incomplete'
    update(rid,lambda r:{**r,'state':{**r['state'],'sharedExperimentRelease':certificate,'reportVersionId':version}},expected_revision=None)
    return {'claim_ids':[c['claimId'] for c in claims],'report_version_id':version}


def publish(record,state,update,publish,scope_validator):
    from services.deep_research.shared_experiment_answer import validated_saved,claim_for
    from services.deep_research.reporting import render_report
    rid=record['runId']; release=record['state'].get('sharedExperimentRelease',{})
    if scope_validator is None:raise DeepResearchError('scope_revoked','发布前缺少材料范围确认。')
    check_run=getattr(scope_validator,'validate_run',None)
    if callable(check_run):
        allowed=check_run(rid) and all(scope_validator(rid,m['materialId']) for m in record.get('materials',[]))
    else:
        materials=record.get('materials',[])
        allowed=all(scope_validator(rid,m['materialId']) for m in materials) if materials else scope_validator(rid,'')
    if not allowed:raise DeepResearchError('scope_revoked','任务或材料范围已改变，不能发布。')
    claims=[];gaps=[];outcome='inconclusive'
    if release.get('complete') is True:
        snapshot=record['state']['sharedExperimentInput'];final=validated_saved(record,snapshot['data'],snapshot['aliases'])
        if (not final['complete'] or final['certificateDigest']!=release.get('certificateDigest')
                or final['candidate']['candidateDigest']!=release.get('candidateDigest')):
            raise DeepResearchError('invalid_shared_experiment_release','最终方案或审核身份已改变。')
        claims=[claim_for(final['candidate'])];outcome='complete'
    else:gaps=[{'wholeQuestion':True,'question':record['question'],'missingEvidence':'实验方案尚有未通过或未完成的核验，草稿与原材料已保留。'}]
    version=record['state'].get('reportVersionId') or 'report_'+rid+'_shared_incomplete'
    payload={'presentationVersion':4,'reportVersionId':version,'outputKind':'experiment_design',
        'sharedExperimentDocumentVersion':1,
        'summary':'四组实验方案已保存，训练与测量尚未执行。' if claims else '实验方案尚未完成，草稿与原材料已保留。',
        'sections':[{'title':'实验方案','claimIds':[c['claimId'] for c in claims]}] if claims else [],
        'claims':claims,'evidence':record['state'].get('evidence',[]),'limitations':'假设与实验建议尚未经过实验验证。' if claims else '',
        'gaps':gaps,'researchNotes':[],'outcome':outcome,'sharedExperimentCertificate':release}
    text=render_report(payload)
    pub,_=publish(run_id=rid,dedup_key=rid+':'+version,payload=payload,outcome=outcome,
                  expected_epoch=state.get('execution_epoch',record.get('executionEpoch',0)),report_text=text)
    update(rid,lambda r:{**r,'state':{**r['state'],'publicationId':pub.get('publicationId',''),'reportText':text}},expected_revision=None)
    return {'publication_id':pub.get('publicationId',''),'outcome':outcome}
