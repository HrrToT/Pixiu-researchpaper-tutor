"""Run the complete offline research suite with exclusive, reproducible evidence.

Each run uses a new directory. A baseline JUnit must retain every previously
collected research module; collection cannot silently select a smaller suite.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_snapshot(root):
    paths = {p for part in ('services', 'llm', 'core', 'api', 'routes', 'schemas', 'tests')
             for p in (root / 'ai-service-python' / part).rglob('*.py')}
    paths.add(root / 'ai-service-python/pytest.ini')
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(paths)}


def junit_modules(path):
    modules = set()
    for case in ET.parse(path).iter('testcase'):
        module = next((v for v in case.get('classname', '').split('.')
                       if v.startswith('test_deep_research')), None)
        if module:
            modules.add(module + '.py')
    return modules


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--baseline-junit', required=True, type=Path)
    parser.add_argument('--diagnostic-timeout', type=int, default=0,
                        help='Dump slow-test thread stacks after N seconds; does not fail or stop a test.')
    args = parser.parse_args()
    if args.diagnostic_timeout and not 5 <= args.diagnostic_timeout <= 600:
        parser.error('Diagnostic timeout must be0 or5..600 seconds')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', args.run_id):
        parser.error('Invalid run ID')
    root = Path(__file__).resolve().parents[1]
    baseline = args.baseline_junit.resolve(strict=True)
    tests = root / 'ai-service-python/tests'
    expected = {p.name for p in tests.glob('test_deep_research*.py')}
    prior = junit_modules(baseline)
    if not expected or not prior or prior - expected:
        parser.error('Missing baseline research modules: ' + str(sorted(prior - expected)))
    work = root / 'tmp' / ('research-offline-' + args.run_id)
    evidence = root / 'docs/deep-research-evidence' / (args.run_id + '.json')
    if evidence.exists():
        parser.error('Evidence already exists; choose a new run ID')
    work.mkdir(exist_ok=False)
    before = source_snapshot(root)
    pytest_args = [str(tests), '-q', '-m', 'not live_llm', '--basetemp', str(work / 'pytest'),
                   '--junitxml', str(work / 'junit.xml'), '--durations=12']
    if args.diagnostic_timeout:
        pytest_args += ['-o', 'faulthandler_timeout=' + str(args.diagnostic_timeout),
                        '-o', 'faulthandler_exit_on_timeout=false']
    inputs = {'args': pytest_args, 'modules': sorted(expected), 'sourceBefore': before,
              'baselineJUnit': str(baseline), 'baselineSha256': sha(baseline),
              'runnerSha256': sha(Path(__file__)),
              'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()}
    with (work / 'inputs.json').open('x', encoding='utf8') as out:
        json.dump(inputs, out, ensure_ascii=False, indent=2)
    bootstrap = '''import json,sys,pytest
from pathlib import Path
v=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'));expected=set(v['modules'])
class ResearchOnly:
 def pytest_ignore_collect(self,collection_path,config):
  if collection_path.suffix=='.py' and collection_path.name.startswith('test_') and collection_path.name not in expected:return True
 def pytest_collection_finish(self,session):
  actual={item.path.name for item in session.items}
  if actual!=expected:raise pytest.UsageError('Frozen module collection changed: '+str(actual^expected))
  print('Verified all '+str(len(actual))+' frozen research modules',flush=True)
sys.exit(pytest.main(v['args'],plugins=[ResearchOnly()]))
'''
    started = time.monotonic()
    with (work / 'pytest.log').open('x', encoding='utf8') as out:
        result = subprocess.run([sys.executable, '-u', '-X', 'utf8', '-c', bootstrap,
                                 str(work / 'inputs.json')], cwd=root, stdout=out, stderr=subprocess.STDOUT)
    after = source_snapshot(root)
    suites = list(ET.parse(work / 'junit.xml').iter('testsuite')) if (work / 'junit.xml').exists() else []
    counts = {k: sum(int(s.get(k, '0')) for s in suites) for k in ('tests', 'failures', 'errors', 'skipped')}
    collected = junit_modules(work / 'junit.xml') if suites else set()
    log = (work / 'pytest.log').read_text(encoding='utf8')
    success = (result.returncode == 0 and before == after and collected == expected
               and counts['tests'] > 0 and counts['failures'] == counts['errors'] == 0)
    proof = {'sourceCommit': inputs['sourceCommit'], 'runId': args.run_id,
             'exitCode': result.returncode, 'verified': success, **counts,
             'modules': len(expected), 'baselineModules': len(prior),
             'addedModules': sorted(expected - prior), 'removedModules': sorted(prior - expected),
             'sourceUnchanged': before == after, 'sourceSha256': before,
             'elapsedSeconds': round(time.monotonic() - started, 2),
             'summary': log.strip().splitlines()[-1] if log.strip() else '',
             'artifacts': {p.relative_to(root).as_posix(): sha(p)
                           for p in work.iterdir() if p.is_file()},
             'runner': {'path': Path(__file__).relative_to(root).as_posix(), 'sha256': inputs['runnerSha256']},
             'excludedMarker': 'live_llm', 'scientificContentAccepted': False,
             'boundary': 'Complete current offline research regression only; not real generation, Provider cost/quality, independent scientific acceptance or full product release.'}
    if before != after:
        proof['changedInputs'] = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    with evidence.open('x', encoding='utf8') as out:
        json.dump(proof, out, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in proof.items() if k not in {'sourceSha256', 'artifacts'}}, ensure_ascii=False))
    print(log[-4000:])
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
