"""Literal display axes and fixed answer slots, never scientific coverage."""
from copy import deepcopy
import re


def explicit_axes(question):
    """Recognize a short explicit list after a table-comparison instruction.

    Ambiguous/multiple lists retain the existing planned layout. Conjunctions
    inside a dimension remain intact; no generated label supplies missing text.
    """
    if not isinstance(question,str):return []
    patterns=(r'表格[^。！？；;\n]{0,12}?(?:比较|对比|对照)\s*([^。！？；;\n]+)',
              r'\btable\s+(?:to\s+)?compare\s+([^.!?;\n]+)')
    layers=getattr(question,'point_instruction_layers',getattr(question,'instruction_layers',(question,)))
    for layer in layers:
        if not isinstance(layer,str):continue
        if re.search(r'(?:不要|不用|无需|取消|去掉)[^。！？\n]{0,8}表格|\b(?:no|without)\s+(?:a\s+)?table\b',layer,re.I):return []
        lists=[];matched=False
        for pattern in patterns:
            for match in re.finditer(pattern,layer,re.I):
                matched=True;text=match[1].strip(' ：:')
                parts=re.split('、',text) if '、' in text else re.split(r',\s*(?:and\s+)?',text)
                parts=[p.strip() for p in parts]
                if (2<=len(parts)<=6 and len(set(parts))==len(parts)
                        and all(p and len(p)<=40 and p in layer for p in parts)):
                    lists.append(parts)
        if matched:return lists[0] if len(lists)==1 else []
    return []


def apply_slots(plan,question):
    """Separate display rows from frozen research goals and source scopes."""
    result=deepcopy(plan);result['fixedSlots']=True
    roles=plan['roles'];axes=explicit_axes(question)
    if axes:
        cells=[]
        for axis_index,label in enumerate(axes):
            for source_index,(source,info) in enumerate(plan['sources'].items()):
                allowed=[oid for oid,role in roles.items() if role['kind']!='supporting'
                         and source in role['sourceAliases']]
                if not allowed:continue
                from services.deep_research.source_labels import source_display_title
                cells.append({'cellId':f'table_{axis_index}_{source_index}',
                    'axisId':f'table_axis_{axis_index}','axisTitle':label,
                    'obligationId':allowed[0],  # Navigation only until a claim binds actual goals.
                    'allowedObligationIds':allowed,'question':label,'source':source,
                    'sourceTitle':source_display_title(info.get('title'),f'论文{source_index+1}'),
                    'evidenceIds':[eid for eid,e in plan['evidence'].items() if e['source']==source],
                    'preferredEvidenceIds':[eid for eid,e in plan['evidence'].items()
                                            if e['source']==source and set(e['obligations'])&set(allowed)]})
        result.update(cells=cells,explicitAxes=axes)
    result['conclusionSlots']=sum(max(1,len(o.get('completionCriteria',[])))
        for o in plan['requirements'] if roles[o['obligationId']]['kind']=='joint')
    return result


def decode_slots(payload,plan,*,max_claims):
    """Normalize one point per cell without accepting arrays or truncating data."""
    if (not isinstance(payload,dict) or set(payload)!={'cells','conclusions'}
            or not isinstance(payload['cells'],list) or not isinstance(payload['conclusions'],list)):
        raise ValueError('Invalid fixed comparison slots')
    limit=min(plan['conclusionSlots'],max(0,max_claims-len(plan['cells'])))
    if len(payload['conclusions'])>limit:
        raise ValueError('Comparison conclusion slots exceeded')
    expected={c['cellId']:c for c in plan['cells']};cells=[];bindings={}
    for row in payload['cells']:
        if not isinstance(row,dict) or not isinstance(row.get('cellId'),str) or row['cellId'] not in expected:
            raise ValueError('Invalid comparison slot identity')
        cell=expected[row['cellId']];dynamic='allowedObligationIds' in cell
        keys={'cellId','claim','unresolved'}|({'obligationIds'} if dynamic else set())
        if (set(row)!=keys or type(row.get('unresolved')) is not bool
                or row['claim'] is not None and not isinstance(row['claim'],dict)
                or row['claim'] is None and not row['unresolved']):
            raise ValueError('Invalid comparison slot shape')
        goals=row.get('obligationIds',[cell['obligationId']])
        if (not isinstance(goals,list) or row['claim'] is not None and not goals
                or any(not isinstance(oid,str) or oid not in cell.get('allowedObligationIds',[cell['obligationId']]) for oid in goals)
                or len(set(goals))!=len(goals)):
            raise ValueError('Invalid comparison slot goals')
        bindings[row['cellId']]=list(goals)
        cells.append({'cellId':row['cellId'],'claims':[] if row['claim'] is None else [deepcopy(row['claim'])],
                      'unresolved':row['unresolved']})
    return {'cells':cells,'conclusions':deepcopy(payload['conclusions'])},bindings
