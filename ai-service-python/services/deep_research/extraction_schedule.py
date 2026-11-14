"""Finish the bounded read pool before paying for evidence-readiness review.

This changes acquisition scheduling only. A received extraction (including an
empty/invalid one) never establishes relevance, factual support or completeness.
Old checkpoints keep their interleaved scheduling and exact request identities.
"""


def enabled(record):
    version=record.get('extractionScheduleContractVersion')
    return type(version) is int and version == 1


def defer_assessment(state, record, update):
    if not enabled(record) or not state.get('extraction_pending') or state.get('budget_exhausted'):
        return None
    # Mark the criteria unassessed rather than inheriting an earlier overview's
    # readiness. The graph needs gaps to return to its next unreviewed batch.
    gaps=[{'obligationId':o['obligationId'],'question':o['question'],
           'checked':False,'missingEvidence':'等待其余已读片段完成证据提取，尚未评估覆盖。'}
          for item in record.get('state',{}).get('plan',[]) for o in item.get('obligations',[])]
    if not gaps:
        return None
    update(state['run_id'],lambda r:{**r,'state':{**r.get('state',{}),
        'assessmentStatus':'deferred','gaps':gaps}},expected_revision=None)
    return {'gaps':gaps,'stop_reason':'','extraction_pending':True,'requery_queries':[],
            'requery_count':state.get('requery_count',0)}
