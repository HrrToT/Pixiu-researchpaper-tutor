"""Rank owned operations for a requested input, temporal model or training task.

Scores select passages only; they do not prove relevance, identity or support.
"""
import re


def query_intent(query):
    if re.search(r'\b(?:input|inputs)\b|(?:什么|哪些|使用|采用).{0,8}输入|输入(?:数据|材料)', query, re.I):
        return 'input'
    if re.search(r'\btemporal (?:representation|model\w*)|\b(?:represent\w*|model\w*)[^.!?]{0,25}\btime\b'
                 r'|时间(?:变化|表示)|怎样表示时间', query, re.I):
        return 'temporal'
    if re.search(r'\b(?:online|offline|per.frame|joint)\b[^.!?]{0,22}\btrain\w*|训练(?:模式|流程|方式)', query, re.I):
        return 'training'
    return None


def operation_score(body, section, intent):
    if not intent or re.search(r'related work|background|concurrent works|references|Table\s*\d', section, re.I):
        return 0
    text = re.sub(r'(?<=[A-Za-z])-[ \t]*\r?\n[ \t]*(?=[A-Za-z])', '', body)
    method = bool(re.search(r'^(?:\d+[. ]*)?(?:Method|Approach|Proposed)', section, re.I))
    own = bool(re.search(r'\bwe\b|\bour\b|我们的|本文', text, re.I))
    if not method and not own:
        return 0
    if intent == 'input':
        explicit = bool(re.search(r'\binput(?:s)?\s+(?:to|of)\s+(?:our|the proposed)\s+(?:method|model|system)', text, re.I))
        data = bool(re.search(r'\b(?:monocular|multi.view|single.view|camera poses?|time labels?|video streams?)\b', text, re.I))
        operation = bool(re.search(r'\b(?:inputs?|construct\w*|initializ\w*|takes?|given|calibrat\w*)\b', text, re.I))
        return (4*explicit+2*method+own+data) if data and operation else 0
    if intent == 'temporal':
        state = bool(re.search(r'\b(?:previous|subsequent|current|canonical|timesteps?|time)\b', text, re.I))
        change = bool(re.search(r'\b(?:transform\w*|deform\w*|offsets?|translat\w*|rotat\w*|carr\w*|pass\w*)\b', text, re.I))
        output = bool(re.search(r'\b(?:output\w*|maps?[^.\n]{0,100}\bto\b|indicate\w*|given as)\b', text, re.I))
        types = sum(bool(re.search(pattern,text,re.I)) for pattern in
                    (r'\b(?:translation|position|mean)\b',r'\b(?:rotation|quaternion)\b',r'\b(?:scale|scaling)\b'))
        return 3*output+types+2*method+own+state if state and change else 0
    if intent == 'training':
        train = bool(re.search(r'\b(?:train\w*|optimiz\w*|learn\w*)\b', text, re.I))
        schedule = sum(bool(re.search(pattern,text,re.I)) for pattern in
                       (r'\b(?:per.frame|each timestep|subsequent timestep|online|offline)\b',
                        r'\b(?:jointly|joint optimization|entire|whole)\b',r'\b(?:initializ\w*|warm.up|stages?|iterations?)\b'))
        return 3*schedule+2*method+own if train and schedule else 0
    return 0
