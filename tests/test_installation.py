# SPDX-License-Identifier: GPL-3.0-only
import subprocess
import tempfile
import unittest
from pathlib import Path
from control_center.installation import collect_status


class InstallationTests(unittest.TestCase):
    def test_timeout_is_reported_as_unknown_without_privilege_escalation(self):
        calls=[]
        def run(args,**kwargs):
            calls.append(args)
            if args[0]=='uname': return subprocess.CompletedProcess(args,0,'test-kernel\n','')
            raise subprocess.TimeoutExpired(args,5)
        with tempfile.TemporaryDirectory() as folder:
            report=collect_status(folder,run)
        checks={c['key']:c for c in report['checks']}
        self.assertIsNone(checks['running']['ok'])
        self.assertIn('timed out',checks['running']['detail'])
        self.assertFalse(checks['ping']['ok'])
        self.assertFalse(report['healthy'])
        self.assertTrue(all(args[0] in ('uname','systemctl') for args in calls))

    def test_dkms_other_kernel_does_not_pass_current_kernel_check(self):
        calls=[]
        def run(args,**kwargs):
            calls.append(args)
            output='test-kernel\n' if args[0]=='uname' else 'laptop-lightbar/0.2.0, old-kernel, x86_64: installed\n' if args[0]=='dkms' else 'active\n'
            return subprocess.CompletedProcess(args,0,output,'')
        with tempfile.TemporaryDirectory() as folder:
            product=Path(folder)/'sys/class/dmi/id/product_name'
            product.parent.mkdir(parents=True); product.write_text('Predator PH16-72')
            report=collect_status(folder,run)
        check=next(c for c in report['checks'] if c['key']=='dkms')
        self.assertFalse(check['ok'])
        self.assertIn('test-kernel',check['detail'])
        self.assertEqual(calls[-1],['dkms','status','-m','laptop-lightbar','-v','0.2.0','-k','test-kernel'])

    def test_missing_dkms_reports_unknown_and_keeps_other_results(self):
        def run(args,**kwargs):
            if args[0]=='dkms': raise FileNotFoundError('DKMS is missing')
            return subprocess.CompletedProcess(args,0,'test-kernel' if args[0]=='uname' else 'active','')
        with tempfile.TemporaryDirectory() as folder:
            product=Path(folder)/'sys/class/dmi/id/product_name'
            product.parent.mkdir(parents=True); product.write_text('Predator PH16-72')
            report=collect_status(folder,run)
        checks={c['key']:c for c in report['checks']}
        self.assertIsNone(checks['dkms']['ok'])
        self.assertIn('DKMS is missing',checks['dkms']['detail'])
        self.assertTrue(checks['running']['ok'])
