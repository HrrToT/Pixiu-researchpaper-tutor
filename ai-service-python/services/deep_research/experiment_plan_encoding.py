"""Lossless private-plan wire format; never select, shorten or approve content."""
from copy import deepcopy
import json

ORDER=('intervention','data','state','poseError','measurement','pairingBudget')
LEGEND='Unverified tuple=[sourceRefs,[intervention,data,state,poseError,measurement,pairingBudget],unresolved]; NOT evidence:'


def enabled(record):
    return (type(record.get('experimentPlanEncodingContractVersion')) is int
        and record['experimentPlanEncodingContractVersion'] in (1,2)
        and type(record.get('experimentDraftContractVersion')) is int
        and record['experimentDraftContractVersion'] in (5,6))


def flexible(record):
    return enabled(record) and record['experimentPlanEncodingContractVersion']==2


def encode(basis):
    if (not isinstance(basis,dict) or set(basis)!={'sourceRefs','protocol','unresolved'}
            or not isinstance(basis['protocol'],dict) or set(basis['protocol'])!=set(ORDER)):
        raise ValueError('Invalid private plan object')
    wire=[deepcopy(basis['sourceRefs']),[basis['protocol'][key] for key in ORDER],deepcopy(basis['unresolved'])]
    _check(wire)
    return wire


def _check(wire):
    if (not isinstance(wire,list) or len(wire)!=3 or not all(isinstance(x,list) for x in wire)
            or len(wire[0])>20 or len(wire[1])!=len(ORDER) or len(wire[2])>8
            or any(not isinstance(x,str) or not x.strip() for group in wire for x in group)
            or len(wire[0])!=len(set(wire[0]))):
        raise ValueError('Invalid private plan tuple')


def decode(wire):
    _check(wire)
    return {'sourceRefs':deepcopy(wire[0]),'protocol':dict(zip(ORDER,wire[1])),
        'unresolved':deepcopy(wire[2])}


def wire_text(basis):
    return json.dumps(encode(basis),ensure_ascii=False,separators=(',',':'),allow_nan=False)
