"""Known visible parameter indices are identities, not new measurements."""
import re
from services.deep_research.audit_source_fields import resolve
from services.deep_research.measurement_numbers import parameter_identifiers,without_parameter_identifiers
from services.deep_research.verification import _measurement_numbers


def scanner(own):
    known=set()
    for eid in own:
        for path in (['quote'],['sourceContext'],['sourceContext','before'],['sourceContext','after']):
            resolved=resolve({'evidenceId':eid,'path':path},own)
            if resolved is not None:known.update(parameter_identifiers(resolved[1]))
    def numbers(text):
        # Adjacent quantity/unit spellings remain conservatively numeric. A
        # coefficient assigned to the identifier is outside the removed token.
        allowed={name for name in known if not re.search(re.escape(name)+r'(?=[A-Za-z%％×倍])',text)}
        return _measurement_numbers(without_parameter_identifiers(text,allowed),word_counts=True)
    return numbers
