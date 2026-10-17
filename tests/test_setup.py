"""Installer routing and build failure recovery without privileged operations."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'scripts').mkdir()
        shutil.copy(ROOT / 'setup.sh', self.root / 'setup.sh')
        self.calls = self.root / 'calls'
        self.env = dict(os.environ, DAMX_CALLS=str(self.calls))
        self.sdk = self.root / 'dotnet'
        self.executable(self.sdk, '#!/bin/sh\necho "8.0.425 [/fake/sdk]"\n')
        self.env['DAMX_DOTNET'] = str(self.sdk)
        for name in ('local-setup.sh', 'install-lightbar.sh'):
            self.executable(self.root / 'scripts' / name,
                            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$DAMX_CALLS"\n')

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def executable(path, content):
        path.write_text(content)
        path.chmod(0o755)

    def run_setup(self, *args):
        return subprocess.run(['bash', str(self.root / 'setup.sh'), *args],
                              env=self.env, text=True, capture_output=True)

    def test_unknown_option_makes_no_changes(self):
        result = self.run_setup('--typo')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.calls.exists())

    def test_conflicting_modes_cannot_accidentally_install(self):
        result = self.run_setup('--build', '--install', '--no-deps')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.calls.exists())

    def test_build_only_never_installs_app_or_bridge(self):
        result = self.run_setup('--build', '--no-deps')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls.read_text(), '--build\n')

    def test_binary_install_does_not_require_sdk(self):
        gui = self.root / 'publish/native/DivAcerManagerMax'
        gui.parent.mkdir(parents=True)
        self.executable(gui, '#!/bin/sh\nexit 0\n')
        self.env['DAMX_DOTNET'] = '/no/such/sdk'
        result = self.run_setup('--install', '--no-deps', '--without-lightbar')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls.read_text(), '--install\n')

    def test_source_install_builds_before_install(self):
        result = self.run_setup('--install', '--no-deps', '--without-lightbar')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls.read_text(), '--build\n--install\n')

    def test_missing_sdk_fails_before_install(self):
        self.env['DAMX_DOTNET'] = '/no/such/sdk'
        result = self.run_setup('--install', '--no-deps', '--without-lightbar')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('.NET 8 SDK', result.stderr)
        self.assertFalse(self.calls.exists())

    def test_uninstall_needs_neither_sdk_nor_dependency_install(self):
        self.env['DAMX_DOTNET'] = '/no/such/sdk'
        result = self.run_setup('--uninstall')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls.read_text(), '--uninstall\n')

    def test_failed_build_does_not_install(self):
        self.executable(self.root / 'scripts/local-setup.sh', '#!/bin/sh\nexit 7\n')
        result = self.run_setup('--install', '--no-deps', '--without-lightbar')
        self.assertEqual(result.returncode, 7)
        self.assertFalse(self.calls.exists())

    def test_published_directory_is_accessible_after_staging(self):
        shutil.copy(ROOT / 'scripts/local-setup.sh', self.root / 'scripts/local-setup.sh')
        (self.root / 'scripts/collect-licenses.py').write_text('pass\n')
        (self.root / 'THIRD-PARTY-NOTICES.md').write_text('test notices\n')
        (self.root / 'LICENSES').mkdir()
        (self.root / 'LICENSES/license.txt').write_text('test license\n')
        self.executable(self.sdk, """#!/bin/bash
while [[ $# -gt 0 ]]; do
    if [[ "$1" == -o ]]; then shift; mkdir -p "$1/licenses/LICENSES"; touch "$1/DivAcerManagerMax"; fi
    shift
done
""")
        result = subprocess.run(['bash', str(self.root / 'scripts/local-setup.sh'), '--build'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        gui = self.root / 'publish/native'
        self.assertEqual(gui.stat().st_mode & 0o777, 0o755)
        self.assertTrue((gui / 'licenses/LICENSES/license.txt').is_file())

    def test_license_failure_preserves_previous_build_and_cleans_stage(self):
        shutil.copy(ROOT / 'scripts/local-setup.sh', self.root / 'scripts/local-setup.sh')
        (self.root / 'scripts/collect-licenses.py').write_text('raise SystemExit(1)\n')
        old = self.root / 'publish/native/DivAcerManagerMax'
        old.parent.mkdir(parents=True)
        self.executable(old, 'previous working build\n')
        # Simulate successful publish, then fail specifically at license collection.
        self.executable(self.sdk, '''#!/bin/bash
while [[ $# -gt 0 ]]; do
    if [[ "$1" == -o ]]; then shift; mkdir -p "$1/licenses"; touch "$1/new-build"; fi
    shift
done
''')
        result = subprocess.run(['bash', str(self.root / 'scripts/local-setup.sh'), '--build'],
                                env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(old.read_text(), 'previous working build\n')
        self.assertEqual(list((self.root / 'publish').glob('.build-*')), [])
        self.assertFalse((self.root / 'publish/.previous-build').exists())
