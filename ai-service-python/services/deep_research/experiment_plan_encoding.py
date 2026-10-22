"""Lossless private-plan wire format; never select, shorten or approve content."""
from copy import deepcopy
import json

ORDER=('intervention','data','state','poseError','measurement','pairingBudget')
LEGEND='Unverified tuple=[sourceRefs,[intervention,data,state,poseError,measurement,pairingBudget],unresolved]; NOT evidence:'


def enabled(record):
    return (type(record.get('experimentPlanEncodingContractVersion')) is int
        and record['experimentPlanEncodingContractVersion'] in (1,2,3,4)
        and type(record.get('experimentDraftContractVersion')) is int
        and record['experimentDraftContractVersion'] in (5,6)
        and (record['experimentPlanEncodingContractVersion'] not in (3,4) or record['experimentDraftContractVersion']==6))


def flexible(record):
    return enabled(record) and record['experimentPlanEncodingContractVersion'] in (2,3,4)


def encode(basis,*,version=1):
    if (not isinstance(basis,dict) or set(basis)!={'sourceRefs','protocol','unresolved'}
            or not isinstance(basis['protocol'],dict) or set(basis['protocol'])!=set(ORDER)):
        raise ValueError('Invalid private plan object')
    if type(version) is int and version==4:
        from services.deep_research.experiment_blueprint import columns
        basis=columns(basis)
    wire=[deepcopy(basis['sourceRefs']),[deepcopy(basis['protocol'][key]) for key in ORDER],deepcopy(basis['unresolved'])]
    _check(wire,version=version)
    return wire


def _check(wire,*,version=1):
    if type(version) is not int or version not in (1,2,3,4):
        raise ValueError('Invalid private plan encoding version')
    if (not isinstance(wire,list) or len(wire)!=3 or not all(isinstance(x,list) for x in wire)
            or len(wire[0])>20 or len(wire[1])!=len(ORDER) or len(wire[2])>8
            or any(not isinstance(x,str) or not x.strip() for group in (wire[0],wire[2]) for x in group)
            or len(wire[0])!=len(set(wire[0]))):
        raise ValueError('Invalid private plan tuple')
    if version in (3,4):
        from services.deep_research.experiment_blueprint import valid_state,valid_budget
        values=wire[1]
        if version==4:
            from services.deep_research.experiment_blueprint import columns
            values=list(columns({'sourceRefs':wire[0],'protocol':dict(zip(ORDER,values)),
                'unresolved':wire[2]},expand=True)['protocol'].values())
        if (any(not isinstance(values[i],str) or not values[i].strip() for i in (0,1,3,4))
                or not valid_state(values[2]) or not valid_budget(values[5])):
            raise ValueError('Invalid private execution blueprint')
    elif any(not isinstance(x,str) or not x.strip() for x in wire[1]):
        raise ValueError('Invalid private plan tuple')


def decode(wire,*,version=1):
    _check(wire,version=version)
    b={'sourceRefs':deepcopy(wire[0]),'protocol':dict(zip(ORDER,deepcopy(wire[1]))),
        'unresolved':deepcopy(wire[2])}
    if version==4:
        from services.deep_research.experiment_blueprint import columns
        return columns(b,expand=True)
    return b


def wire_text(basis,*,version=1):
    return json.dumps(encode(basis,version=version),ensure_ascii=False,separators=(',',':'),allow_nan=False)
