# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock

spec=importlib.util.spec_from_file_location('daemon_ready',Path(__file__).resolve().parents[1]/'scripts/wait-daemon.py')
ready=importlib.util.module_from_spec(spec); spec.loader.exec_module(ready)


class DaemonReadyTests(unittest.TestCase):
    def test_delayed_start_retries_only_ping_then_accepts_ready_service(self):
        now=[0.0]; clients=[]
        outcomes=[FileNotFoundError('not ready'),ConnectionRefusedError('starting'),{'version':'test'}]
        def factory(path,timeout):
            client=Mock()
            outcome=outcomes.pop(0)
            if isinstance(outcome,Exception): client.command.side_effect=outcome
            else: client.command.return_value=outcome
            clients.append(client); return client
        ready.wait_for_daemon('test.sock',1,factory,lambda:now[0],lambda duration:now.__setitem__(0,now[0]+duration))
        self.assertEqual(len(clients),3)
        for client in clients:
            client.command.assert_called_once_with('ping'); client.close.assert_called_once()
        self.assertAlmostEqual(now[0],.2)

    def test_invalid_response_is_not_a_healthy_service(self):
        now=[0.0]
        client=Mock(); client.command.return_value={'unrelated':'response'}
        with self.assertRaisesRegex(RuntimeError,'Invalid daemon ping response'):
            ready.wait_for_daemon('test.sock',.2,lambda *a,**k:client,lambda:now[0],lambda duration:now.__setitem__(0,now[0]+duration))
        self.assertEqual(client.close.call_count,client.command.call_count)

    def test_connection_timeout_respects_overall_deadline(self):
        now=[0.0]; timeouts=[]
        def factory(path,timeout):
            timeouts.append(timeout)
            client=Mock()
            def command(name):
                now[0]+=timeout
                raise TimeoutError('not responding')
            client.command.side_effect=command
            return client
        with self.assertRaisesRegex(RuntimeError,'not responding'):
            ready.wait_for_daemon('test.sock',.25,factory,lambda:now[0],lambda duration:now.__setitem__(0,now[0]+duration))
        self.assertEqual(timeouts,[.25])
        self.assertAlmostEqual(now[0],.25)
