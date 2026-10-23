"""Bounded exact packing of complete prospective review requests, before dispatch."""
from functools import lru_cache


def plan(claims, preview):
    """Minimize requests, then full bytes; never trim inputs or judge claims.

    Canonical scientific batches have at most five roles. Bound arbitrary input
    to eight targets (255 previews), falling back to the original splitter.
    ``preview`` must only build the exact request, with no model invocation.
    """
    if not 2 <= len(claims) <= 8:
        return None
    ids = [claim.get('claimId') for claim in claims]
    if any(not isinstance(cid, str) or not cid for cid in ids) or len(set(ids)) != len(ids):
        return None

    @lru_cache(None)
    def size(mask):
        result = preview([claim for index, claim in enumerate(claims) if mask & (1 << index)])
        if (not isinstance(result, dict) or type(result.get('inputBytes')) is not int
                or type(result.get('maxInputBytes')) is not int
                or result['inputBytes'] < 0 or result['maxInputBytes'] <= 0):
            raise ValueError('Invalid complete review preview')
        return result['inputBytes'] if result['inputBytes'] <= result['maxInputBytes'] else None

    @lru_cache(None)
    def solve(mask):
        if not mask:
            return ()
        if size(mask) is not None:
            return (mask,)
        first = mask & -mask
        sub, best, best_score = mask, None, None
        while sub:
            if sub & first and sub != mask and size(sub) is not None:
                rest = solve(mask ^ sub)
                if rest is not None:
                    candidate = (sub, *rest)
                    score = (len(candidate), sum(size(group) for group in candidate), candidate)
                    if best_score is None or score < best_score:
                        best, best_score = candidate, score
            sub = (sub - 1) & mask
        return best

    solution = solve((1 << len(claims)) - 1)
    if solution is None:
        return None
    return [[claim for index, claim in enumerate(claims) if mask & (1 << index)]
            for mask in solution]
