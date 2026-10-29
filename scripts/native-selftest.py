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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardware.controls import NativeControls


def inspect_and_exercise(args: argparse.Namespace, state_file: str) -> None:
    controls = NativeControls(state_file=state_file)
    print(json.dumps(controls.settings(), indent=2))
    if not args.exercise:
        return
    commands: list[tuple[str, dict[str, object]]] = [
        ('set_thermal_profile', {'profile': controls.settings()['thermal_profile']['current']}),
        ('set_fan_speed', {'cpu': 0, 'gpu': 0}),
        ('set_lighting', {'target': 'keyboard', 'mode': 1, 'color': '0050ff', 'brightness': 80, 'link_wasd': False}),
        ('set_lighting', {'target': 'logo', 'mode': 0, 'color': '0050ff', 'brightness': 80})]
    if 'lightbar' in controls.features:
        commands.append(('set_lighting', {'target': 'lightbar', 'mode': 0, 'color': '0050ff', 'brightness': 80}))
    failed = False
    for name, params in commands:
        try:
            controls.command(name, params)
            print('ACCEPTED:', name, flush=True)
        except (OSError, ValueError, RuntimeError) as e:
            failed = True
            print('FAILED:', name, str(e), flush=True)
    print('Light bar:', 'available' if 'lightbar' in controls.features else 'no direct interface detected')
    if failed:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercise', action='store_true')
    args = parser.parse_args()
    # Root exercises must not follow a predictable /tmp state-file symlink.
    with tempfile.TemporaryDirectory(prefix='fedorizer-selftest-') as directory:
        inspect_and_exercise(args, str(Path(directory) / 'lighting.json'))


if __name__ == '__main__':
    main()
