"""Frozen shared publication budget for text-only coverage edits."""
from copy import deepcopy
from services.deep_research.answer_constraints import requested_character_limit,visible_count,answer_character_count
from services.deep_research.audience_writing_roles import allocation


def build(report,verification,evidence,question,originals,requirements,prior,context):
    if (not isinstance(context,dict) or set(context)!={'outputKind','presentationVersion'}
            or not isinstance(context['outputKind'],str) or not context['outputKind']
            or type(context['presentationVersion']) is not int or context['presentationVersion'] not in (2,3,4)):
        raise ValueError('Invalid text edit publication context')
    fixed={c['claimId']:c for c in [*verification.get('accepted',[]),*prior]}
    shadow=deepcopy(report)
    for index,c in enumerate(shadow['claims']):
        if c['claimId'] in fixed:shadow['claims'][index]=deepcopy(fixed[c['claimId']])
        else:c['text']=''  # Original fixed conditions and publication identity stay.
    known={c['claimId'] for c in shadow['claims']}
    shadow['claims'] += [deepcopy(c) for cid,c in fixed.items() if cid not in known]
    limit=requested_character_limit(question)
    budget=None
    if limit:
        reserved=visible_count(shadow,limit,context['outputKind'],evidence,context['presentationVersion'])
        budget={'totalCharacters':limit,'reservedCharacters':reserved,
                'editableTextCharacters':max(0,limit-reserved),'editableClaimIds':list(originals),
                'fixedSiblingIds':list(fixed),'includesFixedConditionsAndPublicationLayout':True}
    roles=allocation(shadow,requirements,None)
    responsibilities=([c for c in roles['targets'] if c['claimId'] in originals] if roles else [])
    return {'version':1,'budget':budget,'responsibilities':responsibilities,'publicationContext':deepcopy(context)}


def text_count(rows):
    return answer_character_count({'claims':[{'text':r['text'],'conditions':{}} for r in rows]})


def fits(rows,originals,plan):
    budget=plan['budget']
    if budget is None:return True
    edited={c['claimId']:c for c in rows}
    # Omitted verified targets remain in the original answer, so count them too.
    return text_count([edited.get(cid,c) for cid,c in originals.items()])<=budget['editableTextCharacters']
