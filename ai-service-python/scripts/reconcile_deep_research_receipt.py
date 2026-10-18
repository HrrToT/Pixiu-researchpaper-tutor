"""Read an exact legacy failed continuation receipt; never submit model work."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.deep_research.legacy_action_reconciliation import reconcile_legacy_failure


def main():
    root=Path(__file__).resolve().parents[2]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt',type=Path);parser.add_argument('--case',required=True)
    parser.add_argument('--origin',default='http://127.0.0.1:8081/api')
    args=parser.parse_args()
    path=args.receipt.resolve()
    allowed=[root/'tmp/dr-live-cases',root/'tmp/dr-acceptance-receipts']
    if path.parent not in [p.resolve() for p in allowed]:
        raise ValueError('Reconciliation is limited to existing canonical/legacy acceptance receipt folders')
    import requests
    def api(method,path):
        if method!='GET':raise ValueError('Reconciliation cannot submit actions')
        response=requests.get(args.origin.rstrip('/')+path,timeout=25);response.raise_for_status()
        return response.json()
    identity=reconcile_legacy_failure(path,args.case,api)
    print(json.dumps({'caseId':identity['caseId'],'kind':identity['kind'],
        'parentRunId':identity['parentRunId'],'requestId':identity['requestId'],
        'originalReceiptUnchanged':True,'modelCalls':0,
        'boundary':'Only this exact failed pre-child intent is reconciled; future admission rechecks the live receipt and all other prior runs.'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
