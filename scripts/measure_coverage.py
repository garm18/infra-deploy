#!/usr/bin/env python3
"""Standard-library executable-line coverage, not branch or runtime qualification."""
import argparse
import json
from pathlib import Path
import sys
import trace
import unittest


def summarize(paths, counts, root):
    paths = sorted(paths)
    wanted = {str(path.resolve()) for path in paths}
    normalized = {(path, line): hits for (path, line), hits in counts.items() if path in wanted}
    files = {}
    for path in paths:
        executable = {line for line in trace._find_executable_linenos(str(path))
                      if isinstance(line, int) and line > 0}
        covered = {line for line in executable if normalized.get((str(path.resolve()), line), 0)}
        files[str(path.relative_to(root))] = {
            'executable_lines': len(executable), 'covered_lines': len(covered),
            'uncovered_lines': sorted(executable - covered)}
    total = sum(item['executable_lines'] for item in files.values())
    hit = sum(item['covered_lines'] for item in files.values())
    return {'executable_lines': total, 'covered_lines': hit,
            'percent': round(100 * hit / total, 2) if total else 0.0, 'files': files}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minimum', type=float, default=80)
    args = parser.parse_args(argv)
    if not 0 <= args.minimum <= 100:
        parser.error('--minimum must be between 0 and 100')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'src'))
    tracer = trace.Trace(count=True, trace=False)
    suites = []
    missing = []
    for relative in ['tests', 'ansible/tests']:
        directory = root / relative
        if not directory.exists():
            missing.append(relative)
            continue
        suite = tracer.runfunc(unittest.TestLoader().discover, str(directory))
        if not suite.countTestCases():
            missing.append(relative)
        suites.append(suite)
    result = tracer.runfunc(unittest.TextTestRunner(verbosity=1).run, unittest.TestSuite(suites))
    counts = tracer.results().counts
    report = {'measurement': 'stdlib trace executable-line coverage; not branch coverage',
              'tests_run': result.testsRun, 'tests_passed': result.wasSuccessful(),
              'missing_test_suites': missing,
              'runtime_qualification': 'NOT MEASURED: Docker/network/restore integration requires real hosts',
              'src': summarize((root / 'src').rglob('*.py'), counts, root),
              'ansible_helpers': summarize((root / 'ansible/files').rglob('*.py'), counts, root)}
    destination = root / '.reports/coverage.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(f"src coverage: {report['src']['percent']}%; ansible helpers: {report['ansible_helpers']['percent']}%")
    print(f'Report: {destination}')
    passed = (result.wasSuccessful() and not missing and result.testsRun > 0 and
              report['src']['executable_lines'] > 0 and
              report['src']['covered_lines'] * 100 >= args.minimum * report['src']['executable_lines'])
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
