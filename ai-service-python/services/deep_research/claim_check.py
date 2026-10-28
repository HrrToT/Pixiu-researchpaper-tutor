"""Distinguish checking an author claim from reporting that the author said it."""


def enabled(record):
    return (type(record.get('claimCheckContractVersion')) is int
            and record['claimCheckContractVersion'] in (1,2,3)
            and record.get('state',{}).get('outputKind')=='claim_verification')


def prioritize_results(rows, bundles, question):
    """Reserve a result packet and its available provenance before summaries.

    Selection is not a factual link or a relevance verdict. Every selected item
    keeps its own exact quote, ownership, version and independent checks.
    """
    import re
    def tokens(text):
        return set(re.findall(r'[a-z0-9]{3,}',re.sub(r'[-_]+','',text.lower())))
    targets=tokens(question)
    tables=[r for r in rows if r.get('tableData') and r.get('sourceWorkId') and r.get('sourceVersionId')
        and r.get('verification',{}).get('literal')=='passed']
    if not tables:return rows,bundles
    # Prefer literal overlap with the requested comparator, then stable source
    # order. No metric, paper name, table number or expected value is prescribed.
    table=max(tables,key=lambda r:len(targets & tokens(r.get('quote',''))))
    owner=(table.get('sourceWorkId'),table.get('sourceVersionId'))
    notes=[r for r in rows if not r.get('tableData')
        and r.get('verification',{}).get('literal')=='passed'
        and (r.get('sourceWorkId'),r.get('sourceVersionId'))==owner
        and re.search(r're[- ]?train|fair (?:metric|comparison)|original code|baseline.{0,30}(?:config|platform)|重训|重新训练',r.get('quote',''),re.I)]
    table_id=table.get('location',{}).get('table')
    fragments=[r for r in tables if table_id and r.get('location',{}).get('table')==table_id
        and (r.get('sourceWorkId'),r.get('sourceVersionId'))==owner]
    packet=[*(fragments or [table]),*notes[:1]]
    ids=[r['evidenceId'] for r in packet]
    priority={'obligationId':next(iter(table.get('obligationIds',[])),'claim_check'),
        'criterionId':'underlying_result_packet','requirement':question,
        'source':owner[0],'evidenceIds':ids}
    return packet+[r for r in rows if r['evidenceId'] not in ids],[priority,*bundles]


GUIDANCE='''
The requested deliverable is a CLAIM CHECK, not merely an author-claim summary.
Separate what the authors report from your qualified assessment against the
underlying supplied observations. An abstract/introduction repeating the claim
does not by itself check that claim. If relevant main results or experimental
observations are supplied, use the minimum sufficient evidence to explain what
supports, weakens or limits the precise claim. A generic 'not all settings are
guaranteed' boundary cannot replace checking the reported claim at its own scope.
Respect brevity: choose a small informative comparison, not complete table rows
or every metric. If using table cells, keep their exact method/baseline variant,
dataset/group, metric direction and conditions. Similar quality is not lossless;
original published and author re-trained baselines must not be conflated.
Do not invent an experimental difference from unknown alignment. State concrete
known conditions needed to interpret the judgement, not unrelated parameter lists.
If only author summaries are actually available, distinguish reporting the claim
from independently checking it in the acquired material. Do not claim paper-wide
absence or demand a universal guarantee that the user did not ask for.
Each factual premise still needs its own allowed citations; inferential judgements
remain inferences and pass the normal independent checks. No new facts or results
are supplied by these instructions.
'''


AUDIT_GUIDANCE='''
For this claim-check request, evaluate whether the accepted answer actually gives
its own qualified assessment against the underlying supplied evidence. Reporting
an author conclusion plus a generic non-universality disclaimer may answer what
the authors say, but does not alone perform the requested check when relevant
underlying results are available. Read all claims jointly. Necessary conditions
must be sufficiently concrete to interpret that assessment. Do not require a
particular metric, number, extra experiment or exhaustive table that the question
does not need. Do not approve the paper's conclusion merely because the author
reported it. A properly bounded inability to verify from the acquired material
can satisfy a genuine uncertainty question; it is not a paper-absence assertion.
'''


INFERENCE_GUIDANCE='''
For a claim check, a point that combines reported observations with YOUR derived
comparison or qualified judgement has kind=inference, even if it begins with
"the authors report". Cite the exact reported input cells in tableBindings;
do not bind a computed difference to a cell as if the authors reported it.
Prefer a concise qualitative judgement when arithmetic is not needed. A numeric
difference alone does not establish perceptual equivalence or a user tolerance.
Retain the comparison's actual metric, dataset and baseline conditions. Do not
drop the requested assessment merely to produce a safe list of reported values.
'''
