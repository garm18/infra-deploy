import importlib.util
import tempfile
import unittest
from pathlib import Path


class CoverageToolTests(unittest.TestCase):
    def test_unexecuted_files_remain_in_denominator(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/measure_coverage.py'
        spec = importlib.util.spec_from_file_location('coverage_tool', path)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / 'first.py'
            second = root / 'second.py'
            first.write_text('x = 1\ny = 2\n')
            second.write_text('z = 3\n')
            report = tool.summarize([first, second], {(str(first), 1): 1}, root)
            self.assertEqual(report['executable_lines'], 3)
            self.assertEqual(report['covered_lines'], 1)
            self.assertEqual(report['files']['second.py']['uncovered_lines'], [1])
