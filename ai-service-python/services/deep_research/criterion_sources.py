"""Select each frozen requested aspect within existing source slots."""
from services.deep_research.method_intent import query_intents,operation_score


def acquisition_questions(record,query,owned_id):
    """Only the matching, source-permitted frozen plan supplies aspect hints."""
    questions=[]
    for item in record.get('state',{}).get('plan',[]):
        for obligation in item.get('obligations',[]):
            required=obligation.get('requiredSources',[])
            if required and owned_id not in required:
                continue
            question=obligation.get('question','')
            if not (query==obligation.get('searchQuery') or query==question
                    or len(question)>=10 and question in query):
                continue
            questions.extend(c['requirement'] for c in obligation.get('completionCriteria',[])[:4])
            if not obligation.get('completionCriteria'):
                questions.append(question)
    return list(dict.fromkeys(questions))


def criterion_targets(obligations, *, membership_intents=False, module_intents=False):
    """Private ranking views; real obligation IDs and requirements stay intact."""
    targets=[]
    for oid,obligation in obligations.items():
        criteria=obligation.get('completionCriteria') or [{'requirement':obligation['question'],
            'responseType':'explanation'}]
        if module_intents:
            from services.deep_research.shared_modules import named_modules
            for name in named_modules(obligation['question']):
                targets.append((oid,obligation,'shared_module:'+name))
        for criterion in criteria[:4]:
            question=criterion['requirement']
            view={**obligation,'question':question,'searchQuery':'','requestExcerpt':question,
                  'completionCriteria':[criterion]}
            intents=query_intents(question)
            if membership_intents:
                from services.deep_research.dataset_membership import requested
                if requested(question) and 'data_membership' not in intents:
                    intents.append('data_membership')
            for intent in intents or [None]:
                targets.append((oid,view,intent))
    return targets


def include_indexed_criteria(indexed,candidates,questions,owned_id,limit, *, modules=()):
    from services.deep_research.method_details import include_method_details
    selected=list(indexed[:limit]);protected=set()
    for name in modules[:2]:
        selected=include_method_details(selected,candidates,name+' input output',owned_id,limit,
            preserve_targets=protected)
    intents=list(dict.fromkeys(i for q in questions for i in query_intents(q)))[:8]
    for intent in intents:
        selected=include_method_details(selected,candidates,'',owned_id,limit,
            semantic_intent=True,operational_intent=True,intent_override=intent,preserve_targets=protected)
    return selected


def include_pdf_criteria(indexed,candidates,questions,owned_id,content_hash,limit, *, modules=()):
    """PDF fallback keeps the same snapshot/hash, source IDs and whole snippets."""
    selected=list(indexed[:limit])
    owned=[r for r in candidates if r.get('pdfId')==owned_id and r.get('contentHash')==content_hash
           and r.get('accessLevel')=='fulltext']
    if not selected:
        return selected
    protected={selected[0]['sourceId']}
    targets=[('shared_module:'+name) for name in modules[:2]]
    targets+=list(dict.fromkeys(i for q in questions for i in query_intents(q)))[:8]
    for intent in targets:
        def score(row):
            if intent.startswith('shared_module:'):
                from services.deep_research.shared_modules import definition_score
                return definition_score(row['text'],intent.split(':',1)[1])
            return operation_score(row['text'],row.get('location',{}).get('section',''),intent,operational=True)
        ranked=sorted(owned,key=score,reverse=True)
        if not ranked or score(ranked[0])<=0:
            continue
        detail=ranked[0]
        if detail['sourceId'] not in {r['sourceId'] for r in selected}:
            removable=[i for i,r in enumerate(selected) if r['sourceId'] not in protected]
            if len(selected)>=limit:
                if not removable:
                    continue
                selected.pop(removable[-1])
            selected.append(detail)
        protected.add(detail['sourceId'])
    return selected


def acquisition_modules(record,query,owned_id):
    """Intersect literal human terms with the matching source-bound obligation."""
    from services.deep_research.shared_modules import named_modules
    human=named_modules(record.get('question',''))
    result=[]
    for item in record.get('state',{}).get('plan',[]):
        for obligation in item.get('obligations',[]):
            required=obligation.get('requiredSources',[])
            question=obligation.get('question','')
            if required and owned_id not in required:
                continue
            if not (query==obligation.get('searchQuery') or query==question
                    or len(question)>=10 and question in query):
                continue
            result.extend(name for name in named_modules(question) if name in human and name not in result)
    return result[:2]
