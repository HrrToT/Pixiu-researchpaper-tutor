"""Compact source identities for a factual rewrite, never source permissions."""


def factual_source_context(selected, requirements, related):
    sources, by_identity, evidence_sources = {}, {}, {}
    for item in selected:
        # Indexed contentHash can identify a passage, not the whole PDF. P IDs
        # describe work/version/access ownership; each E row retains its OWN hash.
        fields=('sourceWorkId','sourceVersionId','accessLevel','ownerMaterialId')
        identity=tuple(item.get(field) for field in fields)
        alias=by_identity.get(identity)
        if alias is None:
            alias=f'P{len(sources)+1}';by_identity[identity]=alias
            sources[alias]={key:item[key] for key in fields if item.get(key) is not None}
            if item.get('sourceTitle'):
                sources[alias]['title']=item['sourceTitle']
        evidence_sources[item['evidenceId']]=alias
    targets=[]
    for row in requirements:
        if related and row.get('obligationId') not in related:
            continue
        required=row.get('requiredSources',[])
        if not isinstance(required,list) or any(not isinstance(value,str) for value in required):
            raise ValueError('Frozen source requirements must be a list of identities')
        matches={value:[alias for alias,source in sources.items() if value in {
            source.get('sourceWorkId'),source.get('sourceVersionId'),source.get('ownerMaterialId')}]
            for value in required}
        targets.append({'obligationId':row['obligationId'],'requiredSources':matches})
    return {'sources':sources,'requirements':targets},evidence_sources
