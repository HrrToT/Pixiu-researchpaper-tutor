"""Distinguish checking an author claim from reporting that the author said it."""


def enabled(record):
    return (type(record.get('claimCheckContractVersion')) is int
            and record['claimCheckContractVersion']==1
            and record.get('state',{}).get('outputKind')=='claim_verification')


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
