"""One read-only balance query; never send prompts or print credentials."""
from pathlib import Path
import argparse,json,os
import requests
from dotenv import dotenv_values

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',required=True,type=Path)
args=parser.parse_args()
if args.output.exists():raise SystemExit('Evidence file exists; choose a new output path')
root=Path(__file__).resolve().parents[1]
config={k.lower():v for path in (root/'.env',root/'ai-service-python/.env') for k,v in dotenv_values(path).items()}
key=os.environ.get('DEEPSEEK_API_KEY') or os.environ.get('deepseek_api_key') or config.get('deepseek_api_key')
if not key:raise SystemExit('No configured key; no request sent')
session=requests.Session();session.trust_env=False
try:
    response=session.get('https://api.deepseek.com/user/balance',headers={'Authorization':'Bearer '+key},timeout=20)
    result={'httpStatus':response.status_code,'modelCalls':0,'automaticRetry':False}
    if response.status_code==200:result['balance']=response.json()
    else:result['error']='Official balance endpoint did not return success'
except requests.RequestException as error:
    result={'httpStatus':None,'errorType':type(error).__name__,'modelCalls':0,'automaticRetry':False}
with args.output.open('x',encoding='utf8') as out:json.dump(result,out,ensure_ascii=False,indent=2)
print(json.dumps(result,ensure_ascii=False))
