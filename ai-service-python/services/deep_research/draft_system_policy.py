"""Keep high-priority drafting instructions consistent with server permissions."""
DRAFT_NODES=frozenset({'synthesize','synthesize_compact','synthesize_audience','repair_claims'})
OLD='Use each target own original citations; preserve relationships and exact IDs/kinds. '
NEW='Use OWN allowed original sources; preserve IDs/relations and follow per-target kind permissions. '


def apply(record,node,framed,*,prospective=False):
    if not (isinstance(record,dict) and type(record.get('draftSystemContractVersion')) is int
            and record['draftSystemContractVersion']==1
            and type(record.get('structuredOutputContractVersion')) is int
            and record['structuredOutputContractVersion']==15 and node in DRAFT_NODES
            and prospective is False):return framed
    system=framed[0]['content']
    if system.count(OLD)!=1:raise ValueError('Draft system clause does not match frozen base policy')
    system=system.replace(OLD,NEW,1)
    if len(system.encode('utf8'))+128>1024:raise ValueError('Draft system message exceeds reserved framing')
    return [{**framed[0],'content':system},*framed[1:]]
