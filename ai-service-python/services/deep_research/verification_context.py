"""Keep operational checks bounded without dropping explicit proposal dependencies."""
import re

CONFIG_ROLES = {'groups', 'controls', 'data', 'budget', 'steps', 'metrics'}


def configuration_context(targets, context):
    """Config checks need all operational definitions and explicit dependencies.

    Hypotheses, analysis and limits receive separate scientific review with the
    complete configuration. Their unreferenced prose is not another config
    definition. An exact ID reference keeps that statement and its dependencies;
    required content is never clipped to force a request to fit.
    """
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    selected = {row.get('claimId') for row in context if row.get('designRole') in CONFIG_ROLES}
    while True:
        text = '\n'.join(strings([*targets, *[row for row in context if row.get('claimId') in selected]]))
        extra = {row['claimId'] for row in context if isinstance(row.get('claimId'), str)
               and row['claimId'] not in selected
               and re.search(r'(?<![A-Za-z0-9_-])'+re.escape(row['claimId'])+r'(?![A-Za-z0-9_-])',text)}
        if not extra:
            break
        selected.update(extra)
    return [row for row in context if row.get('claimId') in selected]
