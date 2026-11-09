# SPDX-License-Identifier: GPL-3.0-only
import io
import json
import socket
import tempfile
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock, patch

from control_center.client import JSON, ControlClient
from control_center.models import (
    ZONE_MODE,
    CoreKind,
    Fan,
    FanMode,
    Fans,
    Lamp,
    LightingDraft,
    PerKey,
    Settings,
    full_key_map,
    mapping,
)
from control_center.telemetry import Core, PowerReading, Telemetry, gpu_fields

type Handler = Callable[[socket.socket,io.BufferedReader],object]


def reply(response: bytes) -> Handler:
    """A server handler that reads one request line and sends response."""
    def handler(client: socket.socket,stream: io.BufferedReader) -> None:
        stream.readline(); client.sendall(response)
    return handler


class ClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp=tempfile.TemporaryDirectory(prefix='control-client-')
        self.path=str(Path(self.tmp.name)/'socket')
        self.server=socket.socket(socket.AF_UNIX)
        self.server.bind(self.path); self.server.listen()
    def tearDown(self) -> None:
        self.server.close(); self.tmp.cleanup()
    def serve(self,handler: Handler) -> threading.Thread:
        def work() -> None:
            client,_=self.server.accept()
            with client,client.makefile('rb') as stream: handler(client,stream)
        thread=threading.Thread(target=work,daemon=True); thread.start(); return thread
    def test_large_fragmented_responses_and_serialized_concurrent_calls(self) -> None:
        def handler(client: socket.socket,stream: io.BufferedReader) -> None:
            for _ in range(4):
                request=json.loads(stream.readline())
                response=json.dumps({'success': True,'data': {'command':request['command'],'value':'x'*12000}}).encode()+b'\n'
                for i in range(0,len(response),79): client.sendall(response[i:i+79])
        server=self.serve(handler)
        client=ControlClient(self.path)
        replies: list[JSON]=[]
        workers=[threading.Thread(target=lambda i=i:replies.append(client.command(str(i)))) for i in range(4)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(5)
        client.close(); server.join(5)
        self.assertEqual({mapping(r)['command'] for r in replies},{'0','1','2','3'})
        self.assertTrue(all(mapping(r)['value']=='x'*12000 for r in replies))
    def test_rejected_command_reconnects_but_closed_client_cannot(self) -> None:
        worker=self.serve(reply(b'{"success":false,"error":"rejected"}\n'))
        client=ControlClient(self.path)
        with self.assertRaisesRegex(RuntimeError,'rejected'): client.command('first')
        worker.join(3)
        worker=self.serve(reply(b'{"success":true,"data":{"ok":true}}\n'))
        self.assertTrue(mapping(client.command('second'))['ok']); worker.join(3)
        client.close()
        with self.assertRaisesRegex(RuntimeError,'closed'): client.command('third')
    def test_malformed_and_oversized_responses_are_rejected(self) -> None:
        for response in (b'{"data":{}}\n', b'x'*262145+b'\n'):
            worker=self.serve(reply(response))
            client=ControlClient(self.path)
            with self.assertRaises(ValueError): client.command('read')
            client.close(); worker.join(3)
    def test_stale_connection_retries_reads_but_never_writes(self) -> None:
        def drop_after_first(client: socket.socket,stream: io.BufferedReader) -> None:
            stream.readline(); client.sendall(b'{"success":true,"data":{"n":1}}\n')
        def answer(client: socket.socket,stream: io.BufferedReader) -> None:
            stream.readline(); client.sendall(b'{"success":true,"data":{"n":2}}\n')
        for command,retried in (('get_all_settings',True),('set_fan_speed',False)):
            client=ControlClient(self.path)
            worker=self.serve(drop_after_first)
            client.command(command)
            worker.join(3)  # The server side of this connection is now closed.
            worker=self.serve(answer)
            if retried: self.assertEqual(client.command(command),{'n':2})
            else:
                with self.assertRaises(ConnectionError): client.command(command)
                self.assertEqual(client.command(command),{'n':2})
            worker.join(3); client.close()
    def test_request_bound_checked_before_connection(self) -> None:
        client=ControlClient('/no/such/socket')
        with self.assertRaisesRegex(ValueError,'framing'): client.command('write',{'color':'x'*65536})


class ModelTests(unittest.TestCase):
    def test_zone_drafts_load_saved_colors_and_send_no_brightness(self) -> None:
        modes=[0,1,ZONE_MODE]
        draft=LightingDraft.from_state({'kind':'zones','colors':['ff0000','00ff00','0000ff','FFFFFF']},modes)
        self.assertEqual(draft.mode,ZONE_MODE)
        self.assertEqual(draft.request('keyboard'),('set_per_zone_mode',{'zone1':'ff0000','zone2':'00ff00','zone3':'0000ff','zone4':'ffffff'}))
        self.assertEqual(LightingDraft.from_state({'kind':'zones','colors':['ff0000']*4},[0,1]).mode,0)
        command,params=LightingDraft().request('logo')
        self.assertEqual(command,'set_lighting'); self.assertNotIn('zones',params)
    def test_drafts_reject_invalid_colors_and_do_not_share_state(self) -> None:
        a=LightingDraft.from_state({'mode':3,'speed':999,'brightness':-5,'direction':7,'color':'invalid'},[0,1])
        b=LightingDraft.from_state({},[0,1])
        self.assertEqual((a.mode,a.speed,a.brightness,a.direction),(0,9,0,1))
        a.color='ff0000'
        self.assertNotEqual(a.color,b.color)
        a.color='bad'
        with self.assertRaises(ValueError): a.request('keyboard')
    def test_key_maps_include_only_programmable_lamps(self) -> None:
        lamps=[Lamp(0,0,0,0,True),Lamp(1,0,0,0,False),Lamp(2,0,0,0,True)]
        self.assertEqual(full_key_map(lamps,{'0':'#FF0000'}),{'0':'ff0000','2':'5bbfbd'})
    def test_settings_parse_contract_and_keep_defaults_for_missing_keys(self) -> None:
        settings=Settings.parse({'available_features':['fan_speed'],'fans':{'cpu':{'mode':'manual','percent':40},'gpu':{'mode':'max','percent':100}},
                                 'battery_limiter':True,'lcd_override':False,'usb_charging':20,'fan_rpm':{'cpu':2100,'gpu':None},'fan_percent':{'cpu':37,'gpu':None},
                                 'lighting_modes':{'keyboard':[0,1,True]},
                                 'lighting_state':{'per_key':{'colors':{'0':'ff0000'},'brightness':250},'keyboard':{'mode':1}}})
        self.assertEqual(settings.fans,Fans(Fan(FanMode.MANUAL,40),Fan(FanMode.MAX,100)))
        self.assertEqual((settings.switches['battery_limiter'],settings.switches['lcd_override'],settings.usb_charging),(True,False,20))
        self.assertEqual(settings.fan_rpm,{'cpu':2100})
        self.assertEqual(settings.fan_percent,{'cpu':37})
        self.assertEqual(settings.per_key,PerKey({'0':'ff0000'},100))
        self.assertEqual(settings.lighting_modes,{'keyboard':[0,1]})
        self.assertEqual(settings.lighting['keyboard'].mode,1)
        empty=Settings.parse({})
        self.assertEqual((empty.fans,empty.laptop_type,empty.per_key.brightness,empty.usb_charging),(None,'Unknown',80,0))
        self.assertIsNone(Settings.parse({'fans':{'cpu':{'mode':'turbo','percent':1}}}).fans)
        with self.assertRaises(ValueError): Settings.parse([])
    def test_gpu_power_reads_driver_power_draw_and_rejects_values_above_the_limit(self) -> None:
        self.assertEqual(gpu_fields('40,2,100,12000,102.5,175').power,102.5)
        self.assertIs(gpu_fields('40,2,100,12000,588,175').power,PowerReading.ABOVE_LIMIT)
        self.assertIsNone(gpu_fields('40,2,100,12000,N/A,175').power)
        self.assertEqual(gpu_fields('40,2,100,12000,0,175').power,0)
        self.assertIsNone(gpu_fields('40,2,100,12000,nan,175').power)
    def test_paused_telemetry_never_starts_nvidia_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp,patch('control_center.telemetry.subprocess.run',side_effect=AssertionError('GPU was queried')):
            self.assertIsNone(Telemetry(tmp,tmp).sample(False).gpu)
    def test_gpu_sample_is_one_nvidia_query_for_power_draw_not_its_average(self) -> None:
        # Driver 620.70 reports a placeholder 1.00 W average about one sample in four under load; power.draw stays right.
        with tempfile.TemporaryDirectory() as tmp,patch('control_center.telemetry.subprocess.run',return_value=Mock(returncode=0,stdout='86,100,1100,12282,101.8,175\n')) as process:
            gpu=Telemetry(tmp,tmp).gpu()
        self.assertEqual((gpu.temperature,gpu.power) if gpu else None,(86,101.8))
        self.assertEqual(process.call_count,1)
        fields=process.call_args.args[0][1].removeprefix('--query-gpu=').split(',')
        self.assertIn('power.draw',fields); self.assertNotIn('power.draw.average',fields)
    def test_cpu_usage_ignores_samples_across_a_long_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stat=Path(tmp)/'stat'
            telemetry=Telemetry(tmp,tmp)
            with patch('control_center.telemetry.time.monotonic',side_effect=[0,2,10]):
                for line in ('cpu 10 0 10 80 0 0 0 0','cpu 20 0 20 160 0 0 0 0','cpu 30 0 30 240 0 0 0 0'):
                    stat.write_text(line+'\n')
                    usage=telemetry.sample().cpu_usage
                    if line.startswith('cpu 20'): self.assertAlmostEqual(usage or 0,20)
            self.assertIsNone(usage)
    def test_core_frequency_averages_each_physical_core_and_tags_its_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for kind,cpus in (('cpu_core','0-3'),('cpu_atom','4-5')):
                (root/'devices'/kind).mkdir(parents=True); (root/'devices'/kind/'cpus').write_text(cpus+'\n')
            # Two hyper-threaded performance cores, then two efficiency cores listed before them in sysfs order.
            for cpu,core_id,khz in ((4,8,'1200000'),(5,9,'1400000'),(0,0,'2000000'),(1,0,'3000000'),(2,4,'4000000'),(3,4,'4000000')):
                cpufreq=root/f'devices/system/cpu/cpu{cpu}'
                (cpufreq/'topology').mkdir(parents=True); (cpufreq/'cpufreq').mkdir()
                (cpufreq/'topology/physical_package_id').write_text('0'); (cpufreq/'topology/core_id').write_text(str(core_id))
                (cpufreq/'cpufreq/scaling_cur_freq').write_text(khz)
            self.assertEqual([Core(CoreKind.PERFORMANCE,2.5),Core(CoreKind.PERFORMANCE,4.0),
                              Core(CoreKind.EFFICIENCY,1.2),Core(CoreKind.EFFICIENCY,1.4)],Telemetry(tmp,tmp).cores())
    def test_battery_estimate_uses_consistent_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            battery=Path(tmp)/'class/power_supply/BAT0'; battery.mkdir(parents=True)
            for name,value in {'type':'Battery','status':'Discharging','capacity':'50','energy_now':'30000000','energy_full':'60000000','energy_full_design':'65000000','power_now':'10000000'}.items():
                (battery/name).write_text(value)
            sample=Telemetry(tmp,tmp).battery()
            assert sample is not None and sample.health is not None
            self.assertEqual(sample.hours,3)
            self.assertAlmostEqual(sample.health,600/6.5)
