"""Explicit DeepSeek Responses adapter; no retry or chat fallback."""

API_KEY = '_deepseek_api'


def payload(messages, options, *, model, temperature):
    allowed={API_KEY,'response_format','thinking','reasoning_effort','max_tokens',
        'temperature','timeout_seconds','_workflow_init_target'}
    if set(options)-allowed or options.get(API_KEY)!='responses':
        raise ValueError('Invalid Responses transport options')
    fmt=options.get('response_format')
    if (not isinstance(fmt,dict) or set(fmt)!={'type','name','schema'}
            or fmt['type']!='json_schema' or not isinstance(fmt['name'],str)
            or not fmt['name'] or not isinstance(fmt['schema'],dict)):
        raise ValueError('Invalid Responses schema format')
    if '_workflow_init_target' in options:
        target = options['_workflow_init_target']
        if target not in ('baseline', 'component') or fmt['name'] != 'workflow_init_v2_' + target:
            raise ValueError('Invalid initialization target binding')
    cap=options.get('max_tokens')
    if type(cap) is not int or cap<=0:raise ValueError('Invalid Responses output cap')
    thinking=options.get('thinking')
    effort=options.get('reasoning_effort','low')
    if thinking=={'type':'disabled'}:effort='none'
    if effort not in ('none','low','high','max'):raise ValueError('Invalid Responses effort')
    if any(not isinstance(m.get('content'),str) or m.get('role') not in ('system','user','assistant')
           for m in messages):raise ValueError('Unsupported Responses message')
    return {'model':model,'input':messages,'temperature':options.get('temperature',temperature),
        'max_output_tokens':cap,'reasoning':{'effort':effort},'text':{'format':fmt},'stream':False}


def chat_view(data):
    """Preserve message text/usage; reasoning items never become answer text."""
    if (not isinstance(data,dict) or data.get('status') not in ('completed','incomplete','failed')
            or not isinstance(data.get('output'),list)):
        raise ValueError('Invalid Responses result')
    messages=[item for item in data['output'] if isinstance(item,dict) and item.get('type')=='message']
    if (len(messages)>1 or any(not isinstance(i,dict) or i.get('type') not in ('message','reasoning')
                              for i in data['output'])):
        raise ValueError('Unexpected Responses output items')
    parts=messages[0].get('content') if messages else []
    if (not isinstance(parts,list) or any(not isinstance(p,dict) or p.get('type')!='output_text'
        or not isinstance(p.get('text'),str) for p in parts)):
        raise ValueError('Invalid Responses message text')
    content=''.join(p['text'] for p in parts)
    finish={'completed':'stop','incomplete':'length','failed':'responses_failed'}[data['status']]
    usage=data.get('usage')
    mapped=({'prompt_tokens':usage.get('input_tokens'),'completion_tokens':usage.get('output_tokens'),
        'total_tokens':usage.get('total_tokens')} if isinstance(usage,dict) else None)
    if mapped is not None:
        values=list(mapped.values())
        if (any(type(v) is not int or v<0 for v in values) or values[2]!=values[0]+values[1]):mapped=None
    return {**data,'choices':[{'message':{'content':content},'finish_reason':finish}],'usage':mapped}
