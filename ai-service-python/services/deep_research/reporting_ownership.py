"""Bind explicitly named numerical reports to the reporting paper's own sources.

Titles provide routing identities, never scientific support. This prerequisite
does not certify row/variant/metric alignment or the independent semantic verdict.
"""
import json
import re


def enabled(record):
    return type(record.get('reportingOwnershipContractVersion')) is int and record['reportingOwnershipContractVersion']==1


def aliases(evidence):
    found={}
    for item in evidence:
        if item.get('accessLevel')=='user_note':continue
        work=item.get('sourceWorkId',item.get('workId'));title=item.get('sourceTitle','')
        if not isinstance(work,str) or not work or not isinstance(title,str):continue
        prefix=title.split(':',1)[0].strip()
        if not prefix or len(prefix)>180:continue
        labels={prefix}
        words=re.findall(r'[A-Za-z][A-Za-z0-9]*',prefix)
        if ':' in title and 2<=len(words)<=8:
            short=''.join(word[0].upper() for word in words if word.casefold() not in {'a','an','the','of','for','and','in','with','on','to'})
            if 2<=len(short)<=8:labels.add(short)
        for label in labels:found.setdefault(label,set()).add(work)
    return found


def targets(claim,evidence):
    if claim.get('kind') not in {'reported','inference'}:return []
    from services.deep_research.verification import _measurement_numbers
    labels=aliases(evidence)
    if not labels:return []
    pattern=re.compile(r'(?<![A-Za-z0-9_])('+ '|'.join(re.escape(x) for x in sorted(labels,key=len,reverse=True))+r')(?![A-Za-z0-9_])')
    fields=[(['text'],claim.get('text',''))]
    if isinstance(claim.get('conditions'),dict):
        fields.extend((['conditions',k],v) for k,v in claim['conditions'].items() if isinstance(v,str))
    result=[]
    for path,text in fields:
        if not isinstance(text,str):continue
        names=list(pattern.finditer(text))
        report=re.compile(r"\s*(?:(?:的)?作者|论文(?:中)?|文中|(?:'s|’s)?\s*(?:paper|authors?))?\s*(?:自报|报告|reports?(?![A-Za-z])|reported(?![A-Za-z]))")
        for pos,match in enumerate(names):
            tail=text[match.end():]
            if not report.match(tail):continue
            end=len(text)
            stop=re.search(r'[。；;\n]|(?<!\d)\.(?!\d)|因此|因而|所以|据此|故而|(?<![A-Za-z])(?:therefore|thus|hence|implying)(?![A-Za-z])',tail,re.I)
            if stop:end=match.end()+stop.start()
            for other in names[pos+1:]:
                if (labels[other[0]]!=labels[match[0]] and (report.match(text[other.end():])
                        or re.search(r'(?:比|than|versus|vs\.?)[ \t]*$',text[match.end():other.start()],re.I))):
                    end=min(end,other.start());break
            excerpt=text[match.start():end].strip()
            if not _measurement_numbers(excerpt):continue
            result.append({'statementPath':path,'statementExcerpt':excerpt,
                'reporter':match[0],'reportingWorkIds':sorted(labels[match[0]])})
    return result


def guidance(required):
    return '''\nNamed numerical reporting targets (routing metadata, not evidence):
'''+json.dumps(required,ensure_ascii=False,separators=(',',':'))+'''
A supported whole-claim decision also requires reportingOwnershipAudit: one row per
listed target in order, {"index":0,"supported":true,"premises":[{"evidenceId":"own E ID","path":["quote"]}]}.
Each premise must be this claim's own visible source field from the listed reporting
paper, not another paper's comparator row. Bind every numerical clause attributed to
that reporter, including its method/variant, dataset/group, units and actual conditions.
The reporting-paper title is not proof. A GPU sentence cannot support table values;
do not join a competitor row from paper A to paper B's hardware and call it B's report.
If A reports a comparator B, attribute that experiment to A explicitly. A table row
named B is not B's author self-report. Unknown or ambiguous ownership must fail.
Do not approve a weaker paraphrase, or invent premises to populate this structure.
'''


def validate(claim,verdict,evidence, *, identity_evidence=None):
    from services.deep_research.audit_source_fields import resolve
    from services.deep_research.verification import _measurement_numbers
    required=targets(claim,evidence if identity_evidence is None else identity_evidence)
    if not required:return []
    audit=verdict.get('reportingOwnershipAudit')
    if not isinstance(audit,list) or len(audit)!=len(required):return ['reporting_ownership_audit_missing']
    own={e['evidenceId']:e for e in evidence if e.get('evidenceId') in claim.get('evidenceRefs',[])}
    for index,(row,target) in enumerate(zip(audit,required)):
        if len(target['reportingWorkIds'])!=1:return ['reporting_identity_ambiguous']
        if (not isinstance(row,dict) or set(row)!={'index','supported','premises'}
                or type(row['index']) is not int or row['index']!=index or row['supported'] is not True):
            return ['reporting_ownership_unresolved']
        premises=row['premises']
        if not isinstance(premises,list) or not 1<=len(premises)<=20:return ['reporting_premises_missing']
        numbers=set()
        for premise in premises:
            bound=resolve(premise,own)
            if bound is None:return ['reporting_premise_not_bound']
            source,text=bound
            if source.get('accessLevel') not in {'fulltext','abstract'}:
                return ['reporting_source_not_original_text']
            if source.get('sourceWorkId',source.get('workId'))!=target['reportingWorkIds'][0]:
                return ['reporting_paper_mismatch']
            numbers.update(_measurement_numbers(text))
        if _measurement_numbers(target['statementExcerpt'])-numbers:
            return ['reporting_numbers_not_in_own_premises']
    return []


DRAFT_GUIDANCE='''When naming paper B as reporting a numerical result, cite B's original
measurement and matching settings. If the number is a B-labelled comparator in paper A,
state that A reports it; do not present it as B's self-report or attach B's separate
hardware. Missing own-paper values remain unresolved, never copied from another paper.'''
