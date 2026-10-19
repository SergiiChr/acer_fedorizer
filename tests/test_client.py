# SPDX-License-Identifier: GPL-3.0-only
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from control_center.client import ControlClient
from control_center.models import LightingDraft, full_key_map
from control_center.telemetry import gpu_fields, Telemetry
from unittest.mock import patch


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='control-client-')
        self.path=str(Path(self.tmp.name)/'socket')
        self.server=socket.socket(socket.AF_UNIX)
        self.server.bind(self.path); self.server.listen()
    def tearDown(self):
        self.server.close(); self.tmp.cleanup()
    def serve(self,handler):
        def work():
            client,_=self.server.accept()
            with client,client.makefile('rb') as stream: handler(client,stream)
        thread=threading.Thread(target=work,daemon=True); thread.start(); return thread
    def test_large_fragmented_responses_and_serialized_concurrent_calls(self):
        def handler(client,stream):
            for _ in range(4):
                request=json.loads(stream.readline())
                response=json.dumps(dict(success=True,data={'command':request['command'],'value':'x'*12000})).encode()+b'\n'
                for i in range(0,len(response),79): client.sendall(response[i:i+79])
        server=self.serve(handler)
        client=ControlClient(self.path)
        replies=[]
        workers=[threading.Thread(target=lambda i=i:replies.append(client.command(str(i)))) for i in range(4)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(5)
        client.close(); server.join(5)
        self.assertEqual({r['command'] for r in replies},{'0','1','2','3'})
        self.assertTrue(all(len(r['value'])==12000 for r in replies))
    def test_rejected_command_reconnects_but_closed_client_cannot(self):
        worker=self.serve(lambda c,s:(s.readline(),c.sendall(b'{"success":false,"error":"rejected"}\n')))
        client=ControlClient(self.path)
        with self.assertRaisesRegex(RuntimeError,'rejected'): client.command('first')
        worker.join(3)
        worker=self.serve(lambda c,s:(s.readline(),c.sendall(b'{"success":true,"data":{"ok":true}}\n')))
        self.assertTrue(client.command('second')['ok']); worker.join(3)
        client.close()
        with self.assertRaisesRegex(RuntimeError,'closed'): client.command('third')
    def test_malformed_and_oversized_responses_are_rejected(self):
        for response in (b'{"data":{}}\n', b'x'*262145+b'\n'):
            worker=self.serve(lambda c,s:(s.readline(),c.sendall(response)))
            client=ControlClient(self.path)
            with self.assertRaises(ValueError): client.command('read')
            client.close(); worker.join(3)
    def test_request_bound_checked_before_connection(self):
        client=ControlClient('/no/such/socket')
        with self.assertRaisesRegex(ValueError,'framing'): client.command('write',{'color':'x'*65536})


class ModelTests(unittest.TestCase):
    def test_drafts_reject_invalid_colors_and_do_not_share_state(self):
        a=LightingDraft.from_state({'mode':3,'speed':999,'brightness':-5,'direction':7,'color':'invalid'},[0,1])
        b=LightingDraft.from_state({},[0,1])
        self.assertEqual((a.mode,a.speed,a.brightness,a.direction),(0,9,0,1))
        a.color='ff0000'
        self.assertNotEqual(a.color,b.color)
        a.color='bad'
        with self.assertRaises(ValueError): a.params('keyboard')
    def test_key_maps_include_only_programmable_lamps(self):
        lamps=[dict(id=0,programmable=True),dict(id=1,programmable=False),dict(id=2,programmable=True)]
        self.assertEqual(full_key_map(lamps,{'0':'#FF0000'}),{'0':'ff0000','2':'5bbfbd'})
    def test_gpu_prefers_average_and_rejects_observed_invalid_power(self):
        self.assertEqual(gpu_fields('40,2,100,12000,5,588,175,200,405')['power'],5)
        self.assertIsNone(gpu_fields('40,2,100,12000,N/A,588,175,200,405')['power'])
        self.assertEqual(gpu_fields('40,2,100,12000,N/A,0,175,200,405')['power'],0)
        self.assertIsNone(gpu_fields('40,2,100,12000,nan,inf,175,200,405')['power'])
    def test_paused_telemetry_never_starts_nvidia_process(self):
        with tempfile.TemporaryDirectory() as tmp,patch('control_center.telemetry.subprocess.run',side_effect=AssertionError('GPU was queried')):
            self.assertIsNone(Telemetry(tmp,tmp).sample(False)['gpu'])
    def test_battery_estimate_uses_consistent_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            battery=Path(tmp)/'class/power_supply/BAT0'; battery.mkdir(parents=True)
            for name,value in {'type':'Battery','status':'Discharging','capacity':'50','energy_now':'30000000','energy_full':'60000000','energy_full_design':'65000000','power_now':'10000000'}.items():
                (battery/name).write_text(value)
            sample=Telemetry(tmp,tmp).battery()
            self.assertEqual(sample['hours'],3)
            self.assertAlmostEqual(sample['health'],600/6.5)
