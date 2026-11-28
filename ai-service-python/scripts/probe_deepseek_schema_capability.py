"""Bounded synthetic provider diagnostic; never sends papers or retries a receipt.

Run inside the configured service with --submit and a fresh absolute directory.
Each case creates its intent BEFORE dispatch. Existing intents are never resent,
including when observation or response persistence previously failed.
"""
from dataclasses import asdict
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def cases():
    group = {'type': 'array', 'minItems': 1, 'maxItems': 1,
             'items': {'type': 'string', 'enum': ['0', '1']}}
    def obj(properties):
        return {'type': 'object', 'properties': properties,
                'required': list(properties), 'additionalProperties': False}
    return [
        ('constant', obj({'value': {'type': 'string', 'const': 'allowed'}}),
         'Return JSON with value forbidden. Follow the required output schema if these conflict.'),
        ('single_group', obj({'groups': group}),
         'Return JSON with groups ["0","1"]. Follow the required output schema if these conflict.'),
        ('referenced_branch', {**obj({'step': {'$ref': '#/$defs/step'}}), '$defs': {
            'step': {'anyOf': [obj({'kind': {'const': 'observe'}, 'groups': group}),
                               obj({'kind': {'const': 'record'}, 'groups': group})]}}},
         'Return JSON with step kind observe and groups ["0","1"]. '
         'Follow the required output schema if these conflict.'),
    ]


def assess(name, value):
    """Only the declared diagnostic obligations, not a JSON Schema validator."""
    if not isinstance(value, dict): return False
    if name == 'constant': return value == {'value': 'allowed'}
    if name == 'referenced_branch':
        if set(value) != {'step'} or not isinstance(value['step'], dict): return False
        value = value['step']
        if value.get('kind') not in ('observe', 'record'): return False
        if set(value) != {'kind', 'groups'}: return False
    elif set(value) != {'groups'}: return False
    return (isinstance(value.get('groups'), list) and len(value['groups']) == 1
            and value['groups'][0] in ('0', '1'))


def run(directory, invoke):
    directory = Path(directory)
    if not directory.is_absolute(): raise ValueError('Absolute receipt directory required')
    directory.mkdir(parents=True, exist_ok=True)
    summary = []
    from llm.provider import LLMRequest
    for name, schema, prompt in cases():
        intent = directory / (name + '.intent.json')
        options = {'_deepseek_api': 'responses', 'max_tokens': 256,
                   'thinking': {'type': 'disabled'}, 'reasoning_effort': 'none',
                   'response_format': {'type': 'json_schema', 'name': 'probe_' + name, 'schema': schema}}
        request = LLMRequest(prompt=prompt, extra_body=options, timeout_seconds=30)
        with intent.open('x', encoding='utf8') as out:
            json.dump(asdict(request), out, ensure_ascii=False, indent=2)
        try:
            result = invoke(request)
        except Exception as error:
            # Error text/URLs can include credentials; retain only a bounded category.
            failure = {'status': 'unresolved_no_retry', 'errorType': type(error).__name__}
            (directory / (name + '.failure.json')).write_text(json.dumps(failure), encoding='utf8')
            raise RuntimeError('Synthetic diagnostic stopped; inspect receipt, do not resend') from None
        with (directory / (name + '.result.json')).open('x', encoding='utf8') as out:
            json.dump(asdict(result), out, ensure_ascii=False, indent=2)
        try: valid = result.finish_reason == 'stop' and assess(name, json.loads(result.content))
        except (ValueError, TypeError): valid = False
        summary.append({'case': name, 'satisfiesDiagnosticObligations': valid,
                        'finishReason': result.finish_reason, 'tokens': result.usage.total_tokens})
    with (directory / 'summary.json').open('x', encoding='utf8') as out:
        json.dump(summary, out, indent=2)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--submit', action='store_true')
    args = parser.parse_args()
    if not args.submit:
        print(json.dumps({'cases': [name for name, _, _ in cases()], 'maxCalls': 3,
                          'maxOutputTokensPerCall': 256, 'paperContent': False}))
        return
    from llm.client import DeepSeekLLM
    provider = DeepSeekLLM(timeout_seconds=30)
    print(json.dumps(run(args.directory, provider.invoke)))


if __name__ == '__main__': main()
