"""Persist stopped clocks without changing deadlines, reservations or old runs."""
from datetime import datetime,UTC
import math

_EXECUTING={'running','stopping'}
_STOPPED={'waiting_user','paused','cancelled','completed','failed'}


def enabled(record):
    return type(record.get('elapsedAccountingContractVersion')) is int and record['elapsedAccountingContractVersion']==1


def _stored(record):
    value=record.get('budget',{}).get('elapsedSeconds',0)
    return float(value) if type(value) in (int,float) and math.isfinite(value) and value>=0 else 0.0


def _wall(record,at):
    baseline=_stored(record)
    try:
        start=datetime.fromisoformat(record['startedAt'].replace('Z','+00:00'))
        end=datetime.fromisoformat(at.replace('Z','+00:00')) if isinstance(at,str) else at
        seconds=(end-start).total_seconds()
        return round(max(baseline,seconds,0),3)
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError):
        return baseline


def public_elapsed(record,*,now=None):
    if record.get('status') not in _EXECUTING:
        return _stored(record)
    # A running epoch must not reuse an old pause's finishedAt. The original
    # startedAt and reserve-call wall-clock enforcement remain authoritative.
    return _wall(record,now or datetime.now(UTC))


def freeze_transition(current,updated,at,*,recovery=False):
    if (not enabled(current) or current.get('status') not in _EXECUTING
            or updated.get('status') not in _STOPPED):return updated
    return {**updated,'budget':{**updated.get('budget',{}),
        'elapsedSeconds':_wall(current,at),
        'elapsedMeasurement':'recovery_wall_clock_upper_bound' if recovery else 'wall_clock'}}
