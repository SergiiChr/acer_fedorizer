"""Lifecycle tests use a private filesystem and fake tools, never the live system."""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH_PREFIXES = ('/opt/', '/var/lib/', '/usr/src', '/lib/modules', '/run',
                 '/etc/systemd/system', '/etc/os-release', '/usr/local/bin/', '/usr/share/',
                 '/sys/class/dmi/id/product_name', '/sys/module/laptop_lightbar', '/sys/module/damx_lightbar',
                 '/tmp/CoreFxPipe_damx-', '/tmp/damx-*.lock')


def patched(text: str, old: str, new: str) -> str:
    """Replace old with new, failing when old is missing so a stale patch cannot leave a copy using the live system."""
    if old not in text:
        raise AssertionError(f'Patch target not found: {old!r}')
    return text.replace(old, new)


class SetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix='fedorizer-setup-test-')
        self.base = Path(self.temp.name)
        self.root = self.base / 'checkout'
        (self.root / 'scripts').mkdir(parents=True)
        redirected=set()
        for path in [ROOT / 'setup.sh', *ROOT.glob('scripts/*.sh')]:
            target = self.root / path.relative_to(ROOT)
            text = path.read_text()
            # Change only copies of fixed system paths; production has no root overrides.
            for prefix in PATH_PREFIXES:
                if prefix in text:
                    redirected.add(prefix)
                    text = text.replace(prefix, str(self.base) + prefix)
            text = text.replace('if [[ $EUID -ne 0 ]]; then\n    exec sudo -- "$0" "$MODE"\nfi', '')
            text = text.replace('if [[ $EUID -ne 0 ]]; then exec sudo -- "$0"; fi', '')
            self.assertNotIn('exec sudo', text, f'Unpatched sudo re-exec in {target.name}')
            self.executable(target, text)
        self.assertEqual(set(PATH_PREFIXES) - redirected, set(), 'Path prefixes no longer used by any script')
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
                     'gpasswd','modprobe','depmod','dkms','update-desktop-database','sudo','dnf','apt-get','wget','dpkg'):
            self.executable(tools / tool, fake)
        self.executable(self.root/'scripts/wait-daemon.py',fake)
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
        status=patched(status,"Path('/')", "Path("+repr(str(self.base))+")")
        (self.root/'control_center/installation.py').write_text(status)
        shutil.copyfile(ROOT/'control_center/client.py',self.root/'control_center/client.py')


    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def executable(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(content)
        path.chmod(0o755)

    def calls(self) -> list[list[str]]:
        path=self.base/'calls'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def run_setup(self, *args: str, answer: str = '') -> subprocess.CompletedProcess[str]:
        return subprocess.run(['bash', str(self.root/'setup.sh'), *args], env=self.env,
                              input=answer, text=True, capture_output=True, timeout=20, check=False)

    def run_lightbar(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(['bash', str(self.root/'scripts/install-lightbar.sh')],
                              env=self.env, text=True, capture_output=True, timeout=20, check=False)

    def supported(self) -> None:
        (self.base/'sys/class/dmi/id/product_name').write_text('Predator PH16-72')

    def registered(self, version: str = '0.2.0', broken: bool = False) -> None:
        entry=self.dkms/version
        entry.mkdir(parents=True,exist_ok=True)
        source=self.sources/f'laptop-lightbar-{version}'
        if not broken: source.mkdir(parents=True,exist_ok=True)
        (entry/'source').symlink_to(source)

    def test_help_and_no_command_do_not_touch_system(self) -> None:
        for args in ((), ('help',)):
            result=self.run_setup(*args)
            self.assertEqual(result.returncode,0,result.stderr)
            for name in ('install','uninstall','status','help'): self.assertIn(name,result.stdout)
        self.assertEqual(self.calls(),[])

    def test_old_options_and_extra_arguments_fail_before_changes(self) -> None:
        for args in (('--install',), ('--build','--no-deps'), ('install','uninstall'), ('typo',)):
            self.assertEqual(self.run_setup(*args).returncode,2)
        self.assertEqual(self.calls(),[])

    def test_first_install_dependencies_and_binary_permissions(self) -> None:
        result=self.run_setup('install')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('Proceed?',result.stdout)
        self.assertIn(['dependencies'],self.calls())
        self.assertEqual(self.app.stat().st_mode & 0o777,0o755)
        self.assertTrue((self.app/'hardware/controls.py').is_file())
        self.assertTrue((self.base/'group').exists())

    def test_service_is_sandboxed_and_lighting_is_restored_after_sleep(self) -> None:
        result=self.run_setup('install')
        self.assertEqual(result.returncode,0,result.stderr)
        units=self.base/'etc/systemd/system'
        service=(units/'fedorizer-daemon.service').read_text()
        for line in ('ExecStopPost=/usr/bin/python3 -m hardware.daemon --auto-fans','ExecReload=/usr/bin/kill -USR1 $MAINPID',
                     'CapabilityBoundingSet=CAP_CHOWN CAP_SETUID CAP_SETGID','ProtectSystem=strict','ProtectHome=read-only',
                     'DevicePolicy=closed','DeviceAllow=char-hidraw rw','DeviceAllow=char-input r','NoNewPrivileges=yes'):
            self.assertIn(line+'\n',service)
        self.assertNotIn('ProtectKernelTunables=',service)
        resume=(units/'fedorizer-resume.service').read_text()
        self.assertIn('ExecStart=-/usr/bin/systemctl --no-block reload fedorizer-daemon.service',resume)
        self.assertIn('WantedBy=suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target',resume)
        self.assertIn(['systemctl','enable','fedorizer-resume.service'],self.calls())
        wants=units/'suspend.target.wants/fedorizer-resume.service'
        wants.parent.mkdir(); wants.symlink_to(units/'fedorizer-resume.service')
        result=self.run_setup('uninstall')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(['systemctl','disable','fedorizer-resume.service'],self.calls())
        self.assertFalse((units/'fedorizer-resume.service').exists() or wants.is_symlink())

    def test_overwrite_decline_or_eof_preserves_everything(self) -> None:
        self.app.mkdir()
        sentinel=self.app/'existing'
        sentinel.write_text('keep')
        for answer in ('n\n','yes\n',''):
            result=self.run_setup('install',answer=answer)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('This will completely overwrite your installation. Proceed?',result.stdout)
            self.assertEqual(sentinel.read_text(),'keep')
        self.assertNotIn(['dependencies'],self.calls())

    def test_confirmed_overwrite_removes_stale_code_state_and_backups(self) -> None:
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

    def test_dependency_failure_preserves_existing_install(self) -> None:
        self.app.mkdir()
        (self.app/'keep').touch()
        self.executable(self.root/'scripts/install-dependencies.sh','#!/bin/sh\nexit 7\n')
        result=self.run_setup('install',answer='y\n')
        self.assertEqual(result.returncode,7)
        self.assertTrue((self.app/'keep').exists())
        self.assertNotIn(['systemctl','disable','--now','fedorizer-daemon.service'],self.calls())


    def test_stock_driver_preflight_failure_preserves_existing_install(self) -> None:
        self.app.mkdir()
        (self.app/'keep').touch()
        self.env['CONTROL_TEST_ACER_FAIL']='1'
        result=self.run_setup('install',answer='y\n')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((self.app/'keep').exists())
        self.assertEqual(list((self.base/'opt').glob('.fedorizer-install-*')),[])

    def seed_working_installation(self) -> None:
        self.supported()
        result=self.run_setup('install')
        self.assertEqual(result.returncode,0,result.stderr)
        (self.app/'original').write_text('working application')
        (self.app/'original').chmod(0o600)
        (self.base/'var/lib/acer-fedorizer/lighting.json').write_text('{"per_key":{"brightness":20}}')
        (self.sources/'laptop-lightbar-0.2.0/laptop_lightbar.c').write_text('working driver source')
        (self.base/'lib/modules/test-kernel/extra/laptop_lightbar.ko').write_bytes(b'working signed driver')
        self.original_files={path:path.read_bytes() for path in (
            self.app/'original',self.base/'var/lib/acer-fedorizer/lighting.json',
            self.sources/'laptop-lightbar-0.2.0/laptop_lightbar.c',
            self.base/'lib/modules/test-kernel/extra/laptop_lightbar.ko',
            self.base/'etc/systemd/system/fedorizer-daemon.service',
            self.base/'usr/local/bin/acer-fedorizer',self.base/'group.record')}
        for name in ('acer-fedorizer.previous','acer-fedorizer.backup.old'):
            folder=self.base/'opt'/name; folder.mkdir(); (folder/'keep').write_text('saved backup')
        self.registered('0.1.0')
        extra=self.base/'lib/modules/older-kernel/extra'; extra.mkdir(parents=True)
        (extra/'laptop_lightbar.ko.zst').write_bytes(b'older signed module')
        (extra/'unrelated.ko').write_bytes(b'unrelated module')
        (self.base/'calls').unlink()

    def assert_working_installation_restored(self,result: subprocess.CompletedProcess[str]) -> None:
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Previous installation restored.',result.stderr)
        for path,content in self.original_files.items(): self.assertEqual(path.read_bytes(),content,str(path))
        self.assertEqual((self.app/'original').stat().st_mode & 0o777,0o600)
        self.assertTrue((self.dkms/'0.2.0/source').is_symlink())
        self.assertEqual((self.dkms/'0.2.0/source').resolve(),self.sources/'laptop-lightbar-0.2.0')
        for path in ('group','service-enabled','service-running','sys/module/laptop_lightbar'):
            self.assertTrue((self.base/path).exists(),path)
        self.assertEqual(list((self.base/'opt').glob('.fedorizer-install-*')),[])
        self.assertEqual((self.base/'lib/modules/older-kernel/extra/laptop_lightbar.ko.zst').read_bytes(),b'older signed module')
        self.assertEqual((self.base/'lib/modules/older-kernel/extra/unrelated.ko').read_bytes(),b'unrelated module')
        self.assertTrue((self.dkms/'0.1.0/source').is_symlink())
        for name in ('acer-fedorizer.previous','acer-fedorizer.backup.old'):
            self.assertEqual((self.base/'opt'/name/'keep').read_text(),'saved backup')

    def test_missing_headers_before_replacement_preserves_working_install(self) -> None:
        self.seed_working_installation()
        shutil.rmtree(self.base/'lib/modules/test-kernel/build')
        result=self.run_setup('install',answer='y\n')
        self.assertNotEqual(result.returncode,0)
        for path,content in self.original_files.items(): self.assertEqual(path.read_bytes(),content)
        self.assertFalse(any(c[:2]==['systemctl','disable'] or c[:2]==['dkms','remove'] for c in self.calls()))
        self.assertEqual(list((self.base/'opt').glob('.fedorizer-install-*')),[])

    def test_compilation_or_signing_failure_leaves_working_install_untouched(self) -> None:
        self.seed_working_installation()
        self.env['CONTROL_TEST_BUILD_FAIL']='1'
        result=self.run_setup('install',answer='y\n')
        self.assertNotEqual(result.returncode,0)
        for path,content in self.original_files.items(): self.assertEqual(path.read_bytes(),content)
        self.assertTrue((self.base/'service-running').exists())
        self.assertFalse(any(c[:2]==['dkms','remove'] for c in self.calls()))
        self.assertFalse(any(c[:2]==['systemctl','disable'] for c in self.calls()))
        self.assertEqual(list((self.base/'opt').glob('.fedorizer-install-*')),[])

    def test_old_driver_removal_failure_restores_running_app(self) -> None:
        self.seed_working_installation()
        self.env['CONTROL_TEST_REMOVE_FAIL']='1'
        self.assert_working_installation_restored(self.run_setup('install',answer='y\n'))

    def test_driver_install_failure_restores_files_state_registration_and_service(self) -> None:
        self.seed_working_installation()
        self.env['CONTROL_TEST_INSTALL_FAIL']='1'
        self.assert_working_installation_restored(self.run_setup('install',answer='y\n'))

    def test_module_load_failure_restores_previous_driver_and_service(self) -> None:
        self.seed_working_installation()
        self.env['CONTROL_TEST_LOAD_FAIL']='1'
        self.assert_working_installation_restored(self.run_setup('install',answer='y\n'))

    def test_partial_service_start_failure_restores_previous_working_app(self) -> None:
        self.seed_working_installation()
        self.env['CONTROL_TEST_SERVICE_FAIL']='1'
        self.assert_working_installation_restored(self.run_setup('install',answer='y\n'))

    def test_active_service_without_a_responding_daemon_rolls_back(self) -> None:
        self.seed_working_installation()
        self.env['CONTROL_TEST_PING_FAIL']='1'
        self.assert_working_installation_restored(self.run_setup('install',answer='y\n'))

    def test_service_health_failure_restores_previous_working_app(self) -> None:
        self.seed_working_installation()
        self.env['CONTROL_TEST_SERVICE_UNHEALTHY']='1'
        self.assert_working_installation_restored(self.run_setup('install',answer='y\n'))

    def test_rollback_preserves_a_service_that_was_running_but_disabled(self) -> None:
        self.seed_working_installation()
        (self.base/'service-enabled').unlink(); (self.base/'service-disabled').touch()
        self.env['CONTROL_TEST_SERVICE_FAIL']='1'
        result=self.run_setup('install',answer='y\n')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Previous installation restored.',result.stderr)
        self.assertTrue((self.base/'service-running').exists())
        self.assertTrue((self.base/'service-disabled').exists())
        self.assertFalse((self.base/'service-enabled').exists())

    def test_first_install_failure_removes_partial_installation(self) -> None:
        self.supported()
        self.env['CONTROL_TEST_SERVICE_FAIL']='1'
        result=self.run_setup('install')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.app.exists())
        self.assertFalse(self.dkms.exists())
        self.assertFalse(self.module.exists())
        self.assertFalse((self.base/'group').exists())
        self.assertFalse((self.base/'service-running').exists())
        self.assertFalse((self.base/'etc/systemd/system/fedorizer-daemon.service').exists())
        self.assertEqual(list((self.base/'opt').glob('.fedorizer-install-*')),[])

    def test_failed_rollback_keeps_recovery_archive_and_reports_failure(self) -> None:
        self.seed_working_installation()
        self.env['CONTROL_TEST_SERVICE_FAIL']='1'; self.env['CONTROL_TEST_RESTORE_FAIL']='1'
        result=self.run_setup('install',answer='y\n')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('Previous installation restored.',result.stderr)
        self.assertIn('Recovery snapshot retained',result.stderr)
        archives=list((self.base/'opt').glob('.fedorizer-install-*/previous.tar'))
        self.assertEqual(len(archives),1)
        self.assertGreater(archives[0].stat().st_size,0)
        self.assertTrue((archives[0].parent/'groups').is_file())
        self.assertIn('fedorizer-daemon.service enabled=1 running=1',(archives[0].parent/'services').read_text())
        self.assertIn('laptop_lightbar=1',(archives[0].parent/'modules').read_text())
        self.assertEqual((self.app/'original').read_text(),'working application')

    def test_legacy_upgrade_failure_restores_original_service_group_and_driver(self) -> None:
        self.supported()
        for path in ('opt/damx','var/lib/damx','usr/src/damx-lightbar-0.2.0',
                     'var/lib/dkms/damx-lightbar/0.2.0','sys/module/damx_lightbar',
                     'lib/modules/test-kernel/extra','etc/systemd/system'):
            (self.base/path).mkdir(parents=True,exist_ok=True)
        old_app=self.base/'opt/damx/gui'; old_app.write_text('old GUI')
        old_state=self.base/'var/lib/damx/lighting.json'; old_state.write_text('old state')
        old_driver=self.base/'lib/modules/test-kernel/extra/damx_lightbar.ko'; old_driver.write_bytes(b'old driver')
        (self.base/'var/lib/dkms/damx-lightbar/0.2.0/source').symlink_to(self.sources/'damx-lightbar-0.2.0')
        old_unit=self.base/'etc/systemd/system/damx-daemon.service'; old_unit.write_text('old service')
        for path in ('legacy-group','legacy-service-enabled','legacy-service-running'): (self.base/path).touch()
        self.env['CONTROL_TEST_SERVICE_FAIL']='1'
        result=self.run_setup('install',answer='y\n')
        self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertIn('Previous installation restored.',result.stderr)
        for path,text in [(old_app,'old GUI'),(old_state,'old state'),(old_unit,'old service')]: self.assertEqual(path.read_text(),text)
        self.assertEqual(old_driver.read_bytes(),b'old driver')
        self.assertTrue((self.base/'var/lib/dkms/damx-lightbar/0.2.0/source').is_symlink())
        self.assertTrue((self.base/'sys/module/damx_lightbar').is_dir())
        self.assertTrue((self.base/'legacy-service-running').exists())
        self.assertEqual((self.base/'legacy-group.record').read_text(),'damx:x:901:test')
        self.assertFalse(self.app.exists())
        self.assertFalse((self.base/'group').exists())

    def test_stale_dkms_registration_alone_requires_overwrite_confirmation(self) -> None:
        self.registered(broken=True)
        result=self.run_setup('install',answer='n\n')
        self.assertEqual(result.returncode,0)
        self.assertIn('Proceed?',result.stdout)
        self.assertTrue((self.dkms/'0.2.0').exists())
        self.assertNotIn(['dependencies'],self.calls())

    def test_failed_unload_cannot_report_successful_uninstall(self) -> None:
        self.app.mkdir()
        (self.app/'keep').touch()
        self.module.mkdir(parents=True)
        self.env['CONTROL_TEST_UNLOAD_FAIL']='1'
        result=self.run_setup('uninstall')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('completely removed',result.stdout)
        self.assertTrue((self.app/'keep').exists())


    def test_repeated_lightbar_install_replaces_all_versions_without_duplicate_add(self) -> None:
        self.supported()
        self.registered('0.1.0')
        self.registered()
        for _ in range(2):
            result=self.run_lightbar()
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.dkms/'0.1.0').exists())
        self.assertEqual(len([c for c in self.calls() if c[:2]==['dkms','add']]),2)
        self.assertFalse(any(c[:2]==['dkms','status'] for c in self.calls()))

    def test_broken_registration_and_orphan_module_are_repaired(self) -> None:
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

    def test_dkms_remove_failure_does_not_attempt_duplicate_add(self) -> None:
        self.supported()
        self.registered()
        self.env['CONTROL_TEST_REMOVE_FAIL']='1'
        result=self.run_lightbar()
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((self.dkms/'0.2.0').exists())
        self.assertFalse(any(c[:2]==['dkms','add'] for c in self.calls()))

    def test_full_uninstall_is_repeatable_and_preserves_shared_files(self) -> None:
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

    def test_uninstall_cleans_owned_module_files_if_dkms_was_already_removed(self) -> None:
        self.registered()
        orphan=self.base/'lib/modules/test-kernel/extra/laptop_lightbar.ko'
        orphan.parent.mkdir(parents=True)
        orphan.touch()
        common=self.root/'scripts/setup-common.sh'
        common.write_text(patched(common.read_text(),'command -v dkms >/dev/null', 'false'))
        result=self.run_setup('uninstall')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(self.dkms.exists())
        self.assertFalse(orphan.exists())
        self.assertFalse(any(c[0]=='dkms' for c in self.calls()))

    def test_status_missing_install_is_read_only(self) -> None:
        result=self.run_setup('status')
        self.assertEqual(result.returncode,1)
        self.assertIn('Not installed',result.stdout)
        self.assertFalse(any(c[0] in ('dependencies','modprobe','groupdel') for c in self.calls()))

    def test_status_detects_missing_service_and_socket(self) -> None:
        self.app.mkdir()
        result=self.run_setup('status')
        self.assertEqual(result.returncode,1)
        self.assertIn('FAIL: Control socket exists',result.stdout)
        self.assertIn('Repair: run ./setup.sh install',result.stdout)

    def test_status_healthy_with_large_dkms_output_and_socket_ping(self) -> None:
        self.supported()
        result=self.run_setup('install')
        self.assertEqual(result.returncode,0,result.stderr)
        path=self.base/'run/acer-fedorizer.sock'
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(path))
            server.listen()
            def respond() -> None:
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

    def real_dependencies(self, distro: str, version: str) -> subprocess.CompletedProcess[str]:
        copied = self.root/'scripts/install-dependencies.sh'
        text = (ROOT/'scripts/install-dependencies.sh').read_text()
        copied.write_text(patched(text,'/etc/os-release', str(self.base/'etc/os-release')))
        release=self.base/'etc/os-release'
        release.parent.mkdir(exist_ok=True)
        release.write_text(f'ID={distro}\nVERSION_ID={version}\n')
        return subprocess.run(['bash',str(copied)],env=self.env,text=True,capture_output=True,timeout=20,check=False)

    def test_fedora_dependencies_include_native_widgets_and_headers(self) -> None:
        self.supported()
        result=self.real_dependencies('fedora','44')
        self.assertEqual(result.returncode,0,result.stderr)
        call=next(c for c in self.calls() if c[0]=='dnf')
        for package in ('dkms','gcc','make','kernel-devel-test-kernel','python3-gobject','libadwaita','procps-ng'):
            self.assertIn(package,call)
        self.assertNotIn('dotnet-sdk-8.0',call)




    def test_unsupported_distribution_stops_before_package_changes(self) -> None:
        result=self.real_dependencies('unknown','1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c[0] in ('dnf','apt-get','dpkg') for c in self.calls()))

    def seed_build_leftovers(self) -> list[Path]:
        paths = ('hardware/__pycache__/backend.pyc','control_center/__pycache__/app.pyc',
                 'scripts/__pycache__/tool.pyc','native-lightbar/laptop_lightbar.ko',
                 'native-lightbar/.build.cmd','native-lightbar/.module-common.o')
        for name in paths:
            path=self.root/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.touch()
        return [self.root/name for name in paths]

    def test_setup_cleans_caches_but_keeps_application_sources(self) -> None:
        leftovers=self.seed_build_leftovers()
        result=self.run_setup('install')
        self.assertEqual(result.returncode,0,result.stderr)
        for path in leftovers: self.assertFalse(path.exists(),str(path))
        self.assertTrue((self.root/'control_center/__main__.py').exists())
        self.assertTrue((self.root/'native-lightbar/laptop_lightbar.c').exists())
        self.assertTrue((self.root/'LICENSES/GPL-2.0.txt').exists())


    def test_cancelled_install_does_not_clean_or_change_checkout(self) -> None:
        self.app.mkdir()
        leftovers=self.seed_build_leftovers()
        result=self.run_setup('install',answer='n\n')
        self.assertEqual(result.returncode,0,result.stderr)
        for path in leftovers: self.assertTrue(path.exists(),str(path))



    def test_debian_dependencies_need_no_external_feed_or_sdk(self) -> None:
        self.supported()
        result=self.real_dependencies('debian','13')
        self.assertEqual(result.returncode,0,result.stderr)
        call=next(c for c in self.calls() if c[:3]==['apt-get','install','-y'])
        for package in ('python3-gi-cairo','gir1.2-gtk-4.0','gir1.2-adw-1','dkms'):
            self.assertIn(package,call)
        self.assertFalse(any(c[0] in ('dpkg','wget') for c in self.calls()))

    def test_python_syntax_error_does_not_remove_existing_install(self) -> None:
        self.app.mkdir()
        (self.app/'keep').touch()
        (self.root/'control_center/__main__.py').write_text('this is invalid python !')
        result=self.run_setup('install',answer='y\n')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((self.app/'keep').exists())

    def test_gtk_upgrade_removes_legacy_identifiers_and_module_registration(self) -> None:
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

    def test_debian_12_stops_before_installing_an_incompatible_ui(self) -> None:
        result=self.real_dependencies('debian','12')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('libadwaita 1.4+',result.stderr)
        self.assertFalse(any(c[0]=='apt-get' for c in self.calls()))
