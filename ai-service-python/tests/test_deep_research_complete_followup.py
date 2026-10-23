from services.deep_research.facade import _compute_allowed_actions


def test_completed_report_advertises_explicit_new_followup_without_mutating_parent():
    record={'status':'completed','outcome':'complete','state':{'reportText':'已保存正文'}}
    assert _compute_allowed_actions(record)==['open_report','view_sources','continue']
    assert record=={'status':'completed','outcome':'complete','state':{'reportText':'已保存正文'}}


def test_paused_unknown_never_advertises_resume_or_followup():
    assert _compute_allowed_actions({'status':'paused','errorCode':'unresolved_unknown'})==['cancel']


def test_active_run_only_advertises_existing_pause_and_cancel():
    assert _compute_allowed_actions({'status':'running'})==['pause','cancel']
