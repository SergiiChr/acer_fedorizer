#!/usr/bin/env python3
"""Inspect or exercise the native backend without installing a daemon.

Run: python3 scripts/native-selftest.py
     sudo python3 scripts/native-selftest.py --exercise
Exercise reapplies the current profile, enables automatic fans, and sets blue
breathing keyboard lighting and a blue lid logo. Visual confirmation is required.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'DAMM-Daemon'))
from native_controls import NativeControls


def inspect_and_exercise(args, state_file):
    controls = NativeControls(state_file=state_file)
    print(json.dumps(controls.settings(), indent=2))
    if not args.exercise:
        return
    commands = [('set_thermal_profile', {'profile': controls.settings()['thermal_profile']['current']}),
                ('set_fan_speed', {'cpu': 0, 'gpu': 0}),
                ('set_four_zone_mode', {'mode': 1, 'speed': 5, 'brightness': 80,
                                       'direction': 1, 'red': 0, 'green': 80, 'blue': 255}),
                ('set_logo_color', {'red': 0, 'green': 80, 'blue': 255, 'brightness': 80})]
    if 'lightbar' in controls.features:
        commands.append(('set_light_color', {'target': 'lightbar', 'red': 0, 'green': 80, 'blue': 255, 'brightness': 80}))
    failed = False
    for name, params in commands:
        try:
            controls.command(name, params)
            print('ACCEPTED:', name, flush=True)
        except Exception as e:
            failed = True
            print('FAILED:', name, str(e), flush=True)
    print('Light bar:', controls.settings()['lightbar_status'])
    if failed:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercise', action='store_true')
    args = parser.parse_args()
    # Root exercises must not follow a predictable /tmp state-file symlink.
    with tempfile.TemporaryDirectory(prefix='damx-selftest-') as directory:
        inspect_and_exercise(args, str(Path(directory) / 'lighting.json'))


if __name__ == '__main__':
    main()
