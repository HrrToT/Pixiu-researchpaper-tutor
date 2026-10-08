import sqlite3
import pytest
from services.agent_state_repository import AgentStateRepository
from services.agent_migration_export import list_projects, export_project


def test_read_only_export_keeps_all_records_and_never_recovers_queued_runs(tmp_path, monkeypatch):
    path = tmp_path / 'agent.sqlite3'
    monkeypatch.setenv('AGENT_STATE_DB_PATH', str(path))
    repository = AgentStateRepository(str(path)); repository.initialize()
    repository.save_project({'projectId': 'A', 'paperIds': ['paper'], 'title': '旧项目'})
    repository.save_project({'projectId': 'B', 'paperIds': ['secret']})
    for index in range(105):
        repository.save_run({'runId': f'r{index}', 'projectId': 'A', 'status': 'queued', 'prompt': f'q{index}'})
    repository.save_run({'runId': 'other-run', 'projectId': 'B'})
    repository.save_research_task({'taskId': 'task', 'projectId': 'A'})
    repository.save_research_task({'taskId': 'other-task', 'projectId': 'B'})
    repository.save_message({'messageId': 'm', 'taskId': 'task', 'content': '原会话'})
    repository.save_message({'messageId': 'other-m', 'taskId': 'other-task', 'content': '不属于A'})
    repository.save_artifacts({'runId': 'r0', 'draftReport': '完整正文', 'reportSources': [{'sourceId': 's'}]})
    repository.save_plan_review({'runId': 'r0', 'reviewNotes': '原审核'})
    repository.save_final_review({'runId': 'r0', 'status': 'approved'})
    repository.append_timeline_entry({'runId': 'r0', 'id': 'event', 'message': '原轨迹'})
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO debate_results VALUES (?,?,?,?)", ('debate-A','A','{\"answer\":\"原辩论\"}','date'))
        db.execute("INSERT INTO debate_results VALUES (?,?,?,?)", ('debate-B','B','{\"answer\":\"其他项目\"}','date'))
        db.commit()
        before = list(db.iterdump())
    assert len(list_projects()['projects']) == 2
    snapshot = export_project('A')['snapshot']
    assert snapshot['counts']['runs'] == 105
    assert snapshot['debates'] == [{'runId': 'debate-A', 'projectId': 'A', 'result': {'answer': '原辩论'}}]
    assert snapshot['messages'][0]['content'] == '原会话'
    assert len(snapshot['messages']) == 1
    assert snapshot['artifacts'][0]['draftReport'] == '完整正文'
    assert len(snapshot['planReviews']) == len(snapshot['finalReviews']) == len(snapshot['timeline']) == 1
    assert all(run['status'] == 'queued' for run in snapshot['runs'])
    assert export_project('A') == {'status': 'success', 'snapshot': snapshot}
    with sqlite3.connect(path) as db:
        assert list(db.iterdump()) == before
    with pytest.raises(KeyError): export_project('missing')


def test_missing_storage_is_empty_and_does_not_create_database(tmp_path, monkeypatch):
    path = tmp_path / 'missing.sqlite3'
    monkeypatch.setenv('AGENT_STATE_DB_PATH', str(path))
    assert list_projects()['projects'] == []
    assert not path.exists()
