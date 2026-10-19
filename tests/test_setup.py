"""Lifecycle tests use a private filesystem and fake tools, never the live system."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='damx-setup-test-')
        self.base = Path(self.temp.name)
        self.root = self.base / 'checkout'
        (self.root / 'scripts').mkdir(parents=True)
        for path in [ROOT / 'setup.sh', *ROOT.glob('scripts/*.sh')]:
            target = self.root / path.relative_to(ROOT)
            text = path.read_text()
            # Change only copies of fixed system paths; production has no root overrides.
            for prefix in ('/opt/', '/var/lib/', '/usr/src', '/lib/modules', '/run',
                           '/etc/systemd/system', '/etc/os-release', '/usr/local/bin/', '/usr/share/',
                           '/sys/class/dmi/id/product_name', '/sys/module/damx_lightbar',
                           '/tmp/CoreFxPipe_damx-', '/tmp/damx-*.lock'):
                text = text.replace(prefix, str(self.base) + prefix)
            text = text.replace('if [[ $EUID -ne 0 ]]; then\n    exec sudo -- "$0" "$MODE"\nfi', '')
            text = text.replace('if [[ $EUID -ne 0 ]]; then exec sudo -- "$0"; fi', '')
            self.executable(target, text)
        self.app = self.base / 'opt/damx'
        self.dkms = self.base / 'var/lib/dkms/damx-lightbar'
        self.sources = self.base / 'usr/src'
        self.module = self.base / 'sys/module/damx_lightbar'
        for directory in ('opt','usr/src','lib/modules/test-kernel/build','sys/class/dmi/id', 'run'):
            (self.base / directory).mkdir(parents=True,exist_ok=True)
        (self.base / 'sys/class/dmi/id/product_name').write_text('Other model')
        tools = self.base / 'tools'
        tools.mkdir()
        fake = (ROOT / 'tests/fixtures/setup-tools.py').read_text()
        for tool in ('uname','getent','groupadd','groupdel','usermod','pkill','systemctl',
                     'modprobe','depmod','dkms','update-desktop-database','sudo','dnf','apt-get','wget','dpkg'):
            self.executable(tools / tool, fake)
        self.env = dict(os.environ, PATH=str(tools)+':'+os.environ['PATH'], DAMX_TEST_BASE=str(self.base))
        self.env.pop('SUDO_USER', None)
        self.env.pop('PKEXEC_UID', None)
        self.executable(self.root / 'scripts/install-dependencies.sh',
                        '#!/bin/sh\nprintf \'["dependencies"]\\n\' >> "$DAMX_TEST_BASE/calls"\n')
        for file in ('LICENSE','NOTICE.md','THIRD-PARTY-NOTICES.md','LICENSES/GPL-2.0.txt',
                     'DAMM-Daemon/acer_hid.py','DAMM-Daemon/native_controls.py',
                     'DAMM-Daemon/predator_button.py','DAMM-Daemon/DAMX-Daemon.py',
                     'DivAcerManagerMax/icon.png','native-lightbar/damx_lightbar.c',
                     'native-lightbar/Makefile','native-lightbar/dkms.conf'):
            path=self.root/file
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('test fixture\n')
        self.executable(self.root/'publish/native/DivAcerManagerMax', '#!/bin/sh\nexit 0\n')

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def executable(path, content):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(content)
        path.chmod(0o755)

    def calls(self):
        path=self.base/'calls'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def run_setup(self, *args, answer=''):
        return subprocess.run(['bash', str(self.root/'setup.sh'), *args], env=self.env,
                              input=answer, text=True, capture_output=True, timeout=20)

    def run_lightbar(self):
        return subprocess.run(['bash', str(self.root/'scripts/install-lightbar.sh')],
                              env=self.env, text=True, capture_output=True, timeout=20)

    def supported(self):
        (self.base/'sys/class/dmi/id/product_name').write_text('Predator PH16-72')

    def registered(self, version='0.2.0', broken=False):
        entry=self.dkms/version
        entry.mkdir(parents=True,exist_ok=True)
        source=self.sources/f'damx-lightbar-{version}'
        if not broken: source.mkdir(parents=True,exist_ok=True)
        (entry/'source').symlink_to(source)

    def test_help_and_no_command_do_not_touch_system(self):
        for args in ((), ('help',)):
            result=self.run_setup(*args)
            self.assertEqual(result.returncode,0,result.stderr)
            for name in ('install','uninstall','status','help'): self.assertIn(name,result.stdout)
        self.assertEqual(self.calls(),[])

    def test_old_options_and_extra_arguments_fail_before_changes(self):
        for args in (('--install',), ('--build','--no-deps'), ('install','uninstall'), ('typo',)):
            self.assertEqual(self.run_setup(*args).returncode,2)
        self.assertEqual(self.calls(),[])

    def test_first_install_dependencies_and_binary_permissions(self):
        result=self.run_setup('install')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('Proceed?',result.stdout)
        self.assertIn(['dependencies'],self.calls())
        self.assertEqual((self.app/'gui').stat().st_mode & 0o777,0o755)
        self.assertTrue((self.app/'daemon/native_controls.py').is_file())
        self.assertTrue((self.base/'group').exists())

    def test_overwrite_decline_or_eof_preserves_everything(self):
        self.app.mkdir()
        sentinel=self.app/'existing'
        sentinel.write_text('keep')
        for answer in ('n\n','yes\n',''):
            result=self.run_setup('install',answer=answer)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('This will completely overwrite your installation. Proceed?',result.stdout)
            self.assertEqual(sentinel.read_text(),'keep')
        self.assertNotIn(['dependencies'],self.calls())

    def test_confirmed_overwrite_removes_stale_code_state_and_backups(self):
        for folder in ('opt/damx','opt/damx.previous','opt/damx.backup.old','var/lib/damx'):
            path=self.base/folder
            path.mkdir(parents=True)
            (path/'stale').touch()
        result=self.run_setup('install',answer='y\n')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.app/'stale').exists())
        self.assertFalse((self.base/'var/lib/damx/stale').exists())
        self.assertFalse((self.base/'opt/damx.previous').exists())
        self.assertFalse((self.base/'opt/damx.backup.old').exists())

    def test_dependency_failure_preserves_existing_install(self):
        self.app.mkdir()
        (self.app/'keep').touch()
        self.executable(self.root/'scripts/install-dependencies.sh','#!/bin/sh\nexit 7\n')
        result=self.run_setup('install',answer='y\n')
        self.assertEqual(result.returncode,7)
        self.assertTrue((self.app/'keep').exists())
        self.assertNotIn(['systemctl','disable','--now','damx-daemon.service'],self.calls())

    def test_build_failure_preserves_existing_install(self):
        self.app.mkdir()
        (self.app/'keep').touch()
        (self.root/'DivAcerManagerMax/DivAcerManagerMax.csproj').touch()
        self.executable(self.root/'scripts/local-setup.sh', '#!/bin/sh\nexit 8\n')
        result=self.run_setup('install',answer='y\n')
        self.assertEqual(result.returncode,8)
        self.assertTrue((self.app/'keep').exists())

    def test_stock_driver_preflight_failure_preserves_existing_install(self):
        self.app.mkdir()
        (self.app/'keep').touch()
        self.env['DAMX_TEST_ACER_FAIL']='1'
        result=self.run_setup('install',answer='y\n')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((self.app/'keep').exists())
        self.assertEqual(list((self.base/'opt').glob('.damx-install-*')),[])

    def test_stale_dkms_registration_alone_requires_overwrite_confirmation(self):
        self.registered(broken=True)
        result=self.run_setup('install',answer='n\n')
        self.assertEqual(result.returncode,0)
        self.assertIn('Proceed?',result.stdout)
        self.assertTrue((self.dkms/'0.2.0').exists())
        self.assertNotIn(['dependencies'],self.calls())

    def test_failed_unload_cannot_report_successful_uninstall(self):
        self.app.mkdir()
        (self.app/'keep').touch()
        self.module.mkdir(parents=True)
        self.env['DAMX_TEST_UNLOAD_FAIL']='1'
        result=self.run_setup('uninstall')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('completely removed',result.stdout)
        self.assertTrue((self.app/'keep').exists())

    def test_source_checkout_always_builds_even_with_bundled_gui(self):
        project=self.root/'DivAcerManagerMax/DivAcerManagerMax.csproj'
        project.touch()
        self.executable(self.root/'scripts/local-setup.sh',
                        '#!/bin/sh\nprintf \'["helper", "%s"]\\n\' "$1" >> "$DAMX_TEST_BASE/calls"\n')
        result=self.run_setup('install')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([c for c in self.calls() if c[0] in ('helper','dependencies')],
                         [['dependencies'],['helper','--build'],['helper','--install']])

    def test_repeated_lightbar_install_replaces_all_versions_without_duplicate_add(self):
        self.supported()
        self.registered('0.1.0')
        self.registered()
        for _ in range(2):
            result=self.run_lightbar()
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.dkms/'0.1.0').exists())
        self.assertEqual(len([c for c in self.calls() if c[:2]==['dkms','add']]),2)
        self.assertFalse(any(c[:2]==['dkms','status'] for c in self.calls()))

    def test_broken_registration_and_orphan_module_are_repaired(self):
        self.supported()
        self.registered(broken=True)
        orphan=self.base/'lib/modules/old-kernel/extra/damx_lightbar.ko.zst'
        orphan.parent.mkdir(parents=True)
        orphan.touch()
        unrelated=orphan.with_name('other_driver.ko')
        unrelated.touch()
        result=self.run_lightbar()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(orphan.exists())
        self.assertTrue(unrelated.exists())
        self.assertIn(['depmod','-a','old-kernel'],self.calls())

    def test_dkms_remove_failure_does_not_attempt_duplicate_add(self):
        self.supported()
        self.registered()
        self.env['DAMX_TEST_REMOVE_FAIL']='1'
        result=self.run_lightbar()
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((self.dkms/'0.2.0').exists())
        self.assertFalse(any(c[:2]==['dkms','add'] for c in self.calls()))

    def test_full_uninstall_is_repeatable_and_preserves_shared_files(self):
        self.supported()
        self.assertEqual(self.run_setup('install').returncode,0)
        self.registered('0.1.0')
        for name in ('opt/damx.previous','opt/damx.backup.old'):
            (self.base/name).mkdir()
        (self.base/'var/lib/damx/lighting.json').write_text('{}')
        unrelated=self.sources/'other-driver'
        unrelated.mkdir()
        for _ in range(2):
            result=self.run_setup('uninstall')
            self.assertEqual(result.returncode,0,result.stderr)
        for path in (self.app,self.dkms,self.module,self.base/'group',self.base/'var/lib/damx',
                     self.base/'opt/damx.previous',self.base/'opt/damx.backup.old',
                     self.base/'usr/local/bin/DAMX',self.base/'etc/systemd/system/damx-daemon.service'):
            self.assertFalse(path.exists(),str(path))
        self.assertEqual(list(self.sources.glob('damx-lightbar-*')),[])
        self.assertTrue(unrelated.exists())

    def test_uninstall_cleans_owned_module_files_if_dkms_was_already_removed(self):
        self.registered()
        orphan=self.base/'lib/modules/test-kernel/extra/damx_lightbar.ko'
        orphan.parent.mkdir(parents=True)
        orphan.touch()
        common=self.root/'scripts/setup-common.sh'
        common.write_text(common.read_text().replace('command -v dkms >/dev/null', 'false'))
        result=self.run_setup('uninstall')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(self.dkms.exists())
        self.assertFalse(orphan.exists())
        self.assertFalse(any(c[0]=='dkms' for c in self.calls()))

    def test_status_missing_install_is_read_only(self):
        result=self.run_setup('status')
        self.assertEqual(result.returncode,1)
        self.assertIn('Not installed',result.stdout)
        self.assertFalse(any(c[0] in ('dependencies','modprobe','groupdel') for c in self.calls()))

    def test_status_detects_missing_service_and_socket(self):
        self.app.mkdir()
        result=self.run_setup('status')
        self.assertEqual(result.returncode,1)
        self.assertIn('FAIL: Control socket exists',result.stdout)
        self.assertIn('Repair: run ./setup.sh install',result.stdout)

    def test_status_healthy_with_large_dkms_output_and_socket_ping(self):
        self.supported()
        result=self.run_setup('install')
        self.assertEqual(result.returncode,0,result.stderr)
        path=self.base/'run/DAMX.sock'
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(path))
            server.listen()
            def respond():
                client,_=server.accept()
                with client:
                    client.recv(4096)
                    client.sendall(b'{"success":true,"data":{"version":"test"}}\n')
            worker=threading.Thread(target=respond,daemon=True)
            worker.start()
            result=self.run_setup('status')
            worker.join(timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Installation is healthy',result.stdout)
        self.assertIn('OK: Daemon responds to ping',result.stdout)

    def real_dependencies(self, distro, version, sdk=False, source=False):
        copied = self.root/'scripts/install-dependencies.sh'
        text = (ROOT/'scripts/install-dependencies.sh').read_text()
        copied.write_text(text.replace('/etc/os-release', str(self.base/'etc/os-release')))
        release=self.base/'etc/os-release'
        release.parent.mkdir(exist_ok=True)
        release.write_text(f'ID={distro}\nVERSION_ID={version}\n')
        self.executable(self.root/'sdk', '#!/bin/sh\n' + ('echo "8.0.425 [/sdk]"\n' if sdk else 'exit 1\n'))
        self.env['DAMX_DOTNET']=str(self.root/'sdk')
        if source: (self.root/'DivAcerManagerMax/DivAcerManagerMax.csproj').touch()
        return subprocess.run(['bash',str(copied)],env=self.env,text=True,capture_output=True,timeout=20)

    def test_fedora_binary_dependencies_include_headers_without_sdk(self):
        self.supported()
        result=self.real_dependencies('fedora','44')
        self.assertEqual(result.returncode,0,result.stderr)
        call=next(c for c in self.calls() if c[0]=='dnf')
        for package in ('dkms','gcc','make','kernel-devel-test-kernel','python3-gobject','procps-ng'):
            self.assertIn(package,call)
        self.assertNotIn('dotnet-sdk-8.0',call)

    def test_fedora_source_installs_missing_sdk_even_with_old_binary(self):
        result=self.real_dependencies('fedora','44',source=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('dotnet-sdk-8.0',next(c for c in self.calls() if c[0]=='dnf'))

    def test_existing_sdk_does_not_add_another(self):
        result=self.real_dependencies('fedora','44',source=True,sdk=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('dotnet-sdk-8.0',next(c for c in self.calls() if c[0]=='dnf'))

    def test_debian_source_configures_feed_and_all_required_packages(self):
        self.supported()
        result=self.real_dependencies('debian','13',source=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(any(c[0]=='dpkg' for c in self.calls()))
        install=next(c for c in self.calls() if c[0]=='apt-get' and 'dotnet-sdk-8.0' in c)
        for package in ('libicu76','libssl3t64','dkms','linux-headers-test-kernel'):
            self.assertIn(package,install)

    def test_unsupported_distribution_stops_before_package_changes(self):
        result=self.real_dependencies('unknown','1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c[0] in ('dnf','apt-get','dpkg') for c in self.calls()))

    def seed_build_leftovers(self):
        paths = ('DivAcerManagerMax/bin/output.dll', 'DivAcerManagerMax/obj/project.assets.json',
                 'tests/client-tests/bin/test.dll', 'tests/client-tests/obj/cache',
                 'DAMM-Daemon/__pycache__/backend.pyc', 'scripts/__pycache__/tool.pyc',
                 'native-lightbar/damx_lightbar.ko', 'native-lightbar/.build.cmd')
        for name in paths:
            path=self.root/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.touch()
        return [self.root/name for name in paths]

    def test_setup_cleans_intermediates_but_keeps_binary_payload_and_sources(self):
        leftovers=self.seed_build_leftovers()
        result=self.run_setup('install')
        self.assertEqual(result.returncode,0,result.stderr)
        for path in leftovers: self.assertFalse(path.exists(),str(path))
        self.assertTrue((self.root/'publish/native/DivAcerManagerMax').exists())
        self.assertTrue((self.root/'native-lightbar/damx_lightbar.c').exists())
        self.assertTrue((self.root/'LICENSES/GPL-2.0.txt').exists())

    def test_failed_source_setup_cleans_build_output_preserving_failure_code(self):
        leftovers=self.seed_build_leftovers()
        (self.root/'DivAcerManagerMax/DivAcerManagerMax.csproj').touch()
        self.executable(self.root/'scripts/local-setup.sh', '#!/bin/sh\nexit 8\n')
        result=self.run_setup('install')
        self.assertEqual(result.returncode,8)
        for path in leftovers: self.assertFalse(path.exists(),str(path))
        self.assertFalse((self.root/'publish/native').exists())

    def test_cancelled_install_does_not_clean_or_change_checkout(self):
        self.app.mkdir()
        leftovers=self.seed_build_leftovers()
        result=self.run_setup('install',answer='n\n')
        self.assertEqual(result.returncode,0,result.stderr)
        for path in leftovers: self.assertTrue(path.exists(),str(path))

    def test_developer_build_cleans_intermediates_retaining_published_gui(self):
        leftovers=self.seed_build_leftovers()
        self.executable(self.root/'sdk', '''#!/bin/bash
mkdir -p "$(dirname "$0")/DivAcerManagerMax/obj"
touch "$(dirname "$0")/DivAcerManagerMax/obj/build-cache"
while [[ $# -gt 0 ]]; do
    if [[ "$1" == -o ]]; then shift; mkdir -p "$1/licenses/LICENSES"; touch "$1/DivAcerManagerMax"; fi
    shift
done
''')
        self.env['DAMX_DOTNET']=str(self.root/'sdk')
        (self.root/'scripts/collect-licenses.py').write_text('pass\n')
        result=subprocess.run(['bash',str(self.root/'scripts/local-setup.sh'),'--build'],
                              env=self.env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((self.root/'publish/native/DivAcerManagerMax').exists())
        self.assertFalse((self.root/'DivAcerManagerMax/obj').exists())
        for path in leftovers: self.assertFalse(path.exists(),str(path))

    def test_license_failure_preserves_previous_build_and_cleans_stage(self):
        self.executable(self.root/'sdk','''#!/bin/bash
while [[ $# -gt 0 ]]; do
    if [[ "$1" == -o ]]; then shift; mkdir -p "$1/licenses"; touch "$1/new-build"; fi
    shift
done
''')
        self.env['DAMX_DOTNET']=str(self.root/'sdk')
        (self.root/'scripts/collect-licenses.py').write_text('raise SystemExit(1)\n')
        old=self.root/'publish/native/DivAcerManagerMax'
        previous=old.read_bytes()
        leftovers=self.seed_build_leftovers()
        result=subprocess.run(['bash',str(self.root/'scripts/local-setup.sh'),'--build'],
                              env=self.env,text=True,capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(old.read_bytes(),previous)
        for path in leftovers: self.assertFalse(path.exists(),str(path))
        self.assertEqual(list((self.root/'publish').glob('.build-*')),[])
