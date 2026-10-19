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
        self.temp = tempfile.TemporaryDirectory(prefix='fedorizer-setup-test-')
        self.base = Path(self.temp.name)
        self.root = self.base / 'checkout'
        (self.root / 'scripts').mkdir(parents=True)
        for path in [ROOT / 'setup.sh', *ROOT.glob('scripts/*.sh')]:
            target = self.root / path.relative_to(ROOT)
            text = path.read_text()
            # Change only copies of fixed system paths; production has no root overrides.
            for prefix in ('/opt/', '/var/lib/', '/usr/src', '/lib/modules', '/run',
                           '/etc/systemd/system', '/etc/os-release', '/usr/local/bin/', '/usr/share/',
                           '/sys/class/dmi/id/product_name', '/sys/module/laptop_lightbar', '/sys/module/damx_lightbar',
                           '/tmp/CoreFxPipe_damx-', '/tmp/damx-*.lock'):
                text = text.replace(prefix, str(self.base) + prefix)
            text = text.replace('if [[ $EUID -ne 0 ]]; then\n    exec sudo -- "$0" "$MODE"\nfi', '')
            text = text.replace('if [[ $EUID -ne 0 ]]; then exec sudo -- "$0"; fi', '')
            self.executable(target, text)
        self.app = self.base / 'opt/acer-fedorizer'
        self.dkms = self.base / 'var/lib/dkms/laptop-lightbar'
        self.sources = self.base / 'usr/src'
        self.module = self.base / 'sys/module/laptop_lightbar'
        for directory in ('opt','usr/src','lib/modules/test-kernel/build','sys/class/dmi/id', 'run'):
            (self.base / directory).mkdir(parents=True,exist_ok=True)
        (self.base / 'sys/class/dmi/id/product_name').write_text('Other model')
        tools = self.base / 'tools'
        tools.mkdir()
        fake = (ROOT / 'tests/fixtures/setup-tools.py').read_text()
        for tool in ('uname','getent','groupadd','groupdel','usermod','pkill','systemctl',
                     'modprobe','depmod','dkms','update-desktop-database','sudo','dnf','apt-get','wget','dpkg'):
            self.executable(tools / tool, fake)
        self.env = dict(os.environ, PATH=str(tools)+':'+os.environ['PATH'], CONTROL_TEST_BASE=str(self.base))
        self.env.pop('SUDO_USER', None)
        self.env.pop('PKEXEC_UID', None)
        self.executable(self.root / 'scripts/install-dependencies.sh',
                        '#!/bin/sh\nprintf \'["dependencies"]\\n\' >> "$CONTROL_TEST_BASE/calls"\n')
        for file in ('LICENSE','NOTICE.md','LICENSES/GPL-2.0.txt',
                     'hardware/__init__.py','hardware/hid.py','hardware/controls.py',
                     'hardware/hotkey.py','hardware/daemon.py','control_center/__init__.py',
                     'control_center/__main__.py','assets/acer-fedorizer.svg',
                     'native-lightbar/laptop_lightbar.c','native-lightbar/Makefile','native-lightbar/dkms.conf'):
            path=self.root/file
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('pass\n' if path.suffix=='.py' else 'fixture\n')
        # Share production checks, with only their fixed filesystem root redirected.
        status=(ROOT/'control_center/installation.py').read_text()
        status=status.replace("root=Path('/')", "root=Path("+repr(str(self.base))+")")
        (self.root/'control_center/installation.py').write_text(status)
        shutil.copyfile(ROOT/'control_center/client.py',self.root/'control_center/client.py')


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
        source=self.sources/f'laptop-lightbar-{version}'
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
        self.assertEqual(self.app.stat().st_mode & 0o777,0o755)
        self.assertTrue((self.app/'hardware/controls.py').is_file())
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
        for folder in ('opt/acer-fedorizer','opt/acer-fedorizer.previous','opt/acer-fedorizer.backup.old','var/lib/acer-fedorizer'):
            path=self.base/folder
            path.mkdir(parents=True)
            (path/'stale').touch()
        result=self.run_setup('install',answer='y\n')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.app/'stale').exists())
        self.assertFalse((self.base/'var/lib/acer-fedorizer/stale').exists())
        self.assertFalse((self.base/'opt/acer-fedorizer.previous').exists())
        self.assertFalse((self.base/'opt/acer-fedorizer.backup.old').exists())

    def test_dependency_failure_preserves_existing_install(self):
        self.app.mkdir()
        (self.app/'keep').touch()
        self.executable(self.root/'scripts/install-dependencies.sh','#!/bin/sh\nexit 7\n')
        result=self.run_setup('install',answer='y\n')
        self.assertEqual(result.returncode,7)
        self.assertTrue((self.app/'keep').exists())
        self.assertNotIn(['systemctl','disable','--now','fedorizer-daemon.service'],self.calls())


    def test_stock_driver_preflight_failure_preserves_existing_install(self):
        self.app.mkdir()
        (self.app/'keep').touch()
        self.env['CONTROL_TEST_ACER_FAIL']='1'
        result=self.run_setup('install',answer='y\n')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((self.app/'keep').exists())
        self.assertEqual(list((self.base/'opt').glob('.fedorizer-install-*')),[])

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
        self.env['CONTROL_TEST_UNLOAD_FAIL']='1'
        result=self.run_setup('uninstall')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('completely removed',result.stdout)
        self.assertTrue((self.app/'keep').exists())


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
        orphan=self.base/'lib/modules/old-kernel/extra/laptop_lightbar.ko.zst'
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
        self.env['CONTROL_TEST_REMOVE_FAIL']='1'
        result=self.run_lightbar()
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((self.dkms/'0.2.0').exists())
        self.assertFalse(any(c[:2]==['dkms','add'] for c in self.calls()))

    def test_full_uninstall_is_repeatable_and_preserves_shared_files(self):
        self.supported()
        self.assertEqual(self.run_setup('install').returncode,0)
        self.registered('0.1.0')
        for name in ('opt/acer-fedorizer.previous','opt/acer-fedorizer.backup.old'):
            (self.base/name).mkdir()
        (self.base/'var/lib/acer-fedorizer/lighting.json').write_text('{}')
        unrelated=self.sources/'other-driver'
        unrelated.mkdir()
        for _ in range(2):
            result=self.run_setup('uninstall')
            self.assertEqual(result.returncode,0,result.stderr)
        for path in (self.app,self.dkms,self.module,self.base/'group',self.base/'var/lib/acer-fedorizer',
                     self.base/'opt/acer-fedorizer.previous',self.base/'opt/acer-fedorizer.backup.old',
                     self.base/'usr/local/bin/acer-fedorizer',self.base/'etc/systemd/system/fedorizer-daemon.service'):
            self.assertFalse(path.exists(),str(path))
        self.assertEqual(list(self.sources.glob('laptop-lightbar-*')),[])
        self.assertTrue(unrelated.exists())

    def test_uninstall_cleans_owned_module_files_if_dkms_was_already_removed(self):
        self.registered()
        orphan=self.base/'lib/modules/test-kernel/extra/laptop_lightbar.ko'
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
        path=self.base/'run/acer-fedorizer.sock'
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

    def real_dependencies(self, distro, version):
        copied = self.root/'scripts/install-dependencies.sh'
        text = (ROOT/'scripts/install-dependencies.sh').read_text()
        copied.write_text(text.replace('/etc/os-release', str(self.base/'etc/os-release')))
        release=self.base/'etc/os-release'
        release.parent.mkdir(exist_ok=True)
        release.write_text(f'ID={distro}\nVERSION_ID={version}\n')
        return subprocess.run(['bash',str(copied)],env=self.env,text=True,capture_output=True,timeout=20)

    def test_fedora_dependencies_include_native_widgets_and_headers(self):
        self.supported()
        result=self.real_dependencies('fedora','44')
        self.assertEqual(result.returncode,0,result.stderr)
        call=next(c for c in self.calls() if c[0]=='dnf')
        for package in ('dkms','gcc','make','kernel-devel-test-kernel','python3-gobject','libadwaita','procps-ng'):
            self.assertIn(package,call)
        self.assertNotIn('dotnet-sdk-8.0',call)




    def test_unsupported_distribution_stops_before_package_changes(self):
        result=self.real_dependencies('unknown','1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c[0] in ('dnf','apt-get','dpkg') for c in self.calls()))

    def seed_build_leftovers(self):
        paths = ('hardware/__pycache__/backend.pyc','control_center/__pycache__/app.pyc',
                 'scripts/__pycache__/tool.pyc','native-lightbar/laptop_lightbar.ko',
                 'native-lightbar/.build.cmd','native-lightbar/.module-common.o')
        for name in paths:
            path=self.root/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.touch()
        return [self.root/name for name in paths]

    def test_setup_cleans_caches_but_keeps_application_sources(self):
        leftovers=self.seed_build_leftovers()
        result=self.run_setup('install')
        self.assertEqual(result.returncode,0,result.stderr)
        for path in leftovers: self.assertFalse(path.exists(),str(path))
        self.assertTrue((self.root/'control_center/__main__.py').exists())
        self.assertTrue((self.root/'native-lightbar/laptop_lightbar.c').exists())
        self.assertTrue((self.root/'LICENSES/GPL-2.0.txt').exists())


    def test_cancelled_install_does_not_clean_or_change_checkout(self):
        self.app.mkdir()
        leftovers=self.seed_build_leftovers()
        result=self.run_setup('install',answer='n\n')
        self.assertEqual(result.returncode,0,result.stderr)
        for path in leftovers: self.assertTrue(path.exists(),str(path))



    def test_debian_dependencies_need_no_external_feed_or_sdk(self):
        self.supported()
        result=self.real_dependencies('debian','13')
        self.assertEqual(result.returncode,0,result.stderr)
        call=next(c for c in self.calls() if c[:3]==['apt-get','install','-y'])
        for package in ('python3-gi-cairo','gir1.2-gtk-4.0','gir1.2-adw-1','dkms'):
            self.assertIn(package,call)
        self.assertFalse(any(c[0] in ('dpkg','wget') for c in self.calls()))

    def test_python_syntax_error_does_not_remove_existing_install(self):
        self.app.mkdir()
        (self.app/'keep').touch()
        (self.root/'control_center/__main__.py').write_text('this is invalid python !')
        result=self.run_setup('install',answer='y\n')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((self.app/'keep').exists())

    def test_gtk_upgrade_removes_legacy_identifiers_and_module_registration(self):
        # These names are intentionally used to test compatibility cleanup.
        old_app=self.base/'opt/damx'
        old_app.mkdir(); (old_app/'old-gui').touch()
        old_state=self.base/'var/lib/damx'; old_state.mkdir(parents=True)
        (self.base/'legacy-group').touch()
        old_module=self.base/'sys/module/damx_lightbar'; old_module.mkdir(parents=True)
        old_source=self.sources/'damx-lightbar-0.2.0'; old_source.mkdir()
        old_entry=self.base/'var/lib/dkms/damx-lightbar/0.2.0'; old_entry.mkdir(parents=True)
        (old_entry/'source').symlink_to(old_source)
        old_unit=self.base/'etc/systemd/system/damx-daemon.service'; old_unit.parent.mkdir(parents=True); old_unit.touch()
        result=self.run_setup('install',answer='y\n')
        self.assertEqual(result.returncode,0,result.stderr)
        for path in (old_app,old_state,old_module,old_source,old_unit,old_entry,self.base/'legacy-group'):
            self.assertFalse(path.exists(),str(path))
        self.assertTrue((self.app/'control_center/__main__.py').is_file())
        self.assertTrue((self.base/'etc/systemd/system/fedorizer-daemon.service').is_file())
        self.assertIn(['dkms','remove','-m','damx-lightbar','-v','0.2.0','--all'],self.calls())

    def test_debian_12_stops_before_installing_an_incompatible_ui(self):
        result=self.real_dependencies('debian','12')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('libadwaita 1.4+',result.stderr)
        self.assertFalse(any(c[0]=='apt-get' for c in self.calls()))
