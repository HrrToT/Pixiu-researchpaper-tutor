"""Read-only legacy export: never invokes project loading or queued-job recovery."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path


def _path():
    return Path(os.environ.get('AGENT_STATE_DB_PATH') or Path(__file__).resolve().parents[1] / 'data' / 'agent_state.sqlite3')


def _open():
    return sqlite3.connect(_path().resolve().as_uri() + '?mode=ro', uri=True)


def list_projects():
    if not _path().exists():
        return {'status': 'success', 'projects': []}
    with closing(_open()) as db:
        rows = db.execute('SELECT payload FROM agent_projects_v2 ORDER BY rowid ASC').fetchall()
    return {'status': 'success', 'projects': [json.loads(row[0]) for row in rows]}


def export_project(project_id):
    if not _path().exists():
        raise KeyError(project_id)
    with closing(_open()) as db:
        db.execute('BEGIN')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        row = db.execute('SELECT payload FROM agent_projects_v2 WHERE project_id=?', (project_id,)).fetchone()
        if row is None:
            raise KeyError(project_id)
        project = json.loads(row[0])
        def records(table, column='payload'):
            if table not in tables:
                return []
            return [json.loads(row[0]) for row in db.execute(f'SELECT {column} FROM {table} ORDER BY rowid ASC')]
        runs = [item for item in records('agent_runs_v2') if item.get('projectId') == project_id]
        tasks = [item for item in records('agent_research_tasks_v3') if item.get('projectId') == project_id]
        run_ids = {item.get('runId') for item in runs}
        task_ids = {item.get('taskId') for item in tasks}
        snapshot = {'snapshotVersion': 1, 'project': project, 'runs': runs, 'researchTasks': tasks,
            'messages': [item for item in records('agent_messages_v3') if item.get('taskId') in task_ids],
            'planReviews': [item for item in records('agent_plan_reviews_v2') if item.get('runId') in run_ids],
            'finalReviews': [item for item in records('agent_final_reviews_v2') if item.get('runId') in run_ids],
            'artifacts': [item for item in records('agent_run_artifacts_v2') if item.get('runId') in run_ids],
            'timeline': [item for item in records('agent_run_timeline_entries_v2') if item.get('runId') in run_ids],
            'debates': [{'runId': row[0], 'projectId': project_id, 'result': json.loads(row[1])}
                for row in db.execute('SELECT run_id,result_json FROM debate_results WHERE project_id=? ORDER BY rowid ASC', (project_id,))]
                if 'debate_results' in tables else []}
        snapshot['counts'] = {key: len(value) for key, value in snapshot.items() if isinstance(value, list)}
        db.rollback()
    return {'status': 'success', 'snapshot': snapshot}
