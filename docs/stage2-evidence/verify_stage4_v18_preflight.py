"""Pending single critique is unauthorized; comparison is outside the plan."""
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

runner = Path(__file__).with_name('verify_stage4_v12.py')
for case, reason in [('critique', 'Explicit new authorization required'),
                     ('compare', 'Case outside fixed plan')]:
    with (patch.object(sys, 'argv', [str(runner), case, 'start', 'v18']),
          patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden')) as network):
        try:
            runpy.run_path(str(runner), run_name='__main__')
        except AssertionError as error:
            assert str(error) == reason
        else:
            raise AssertionError('Disallowed start accepted')
        assert network.call_count == 0
print('Pending critique and out-of-plan comparison refused before network; requests=0, submissions=0')
