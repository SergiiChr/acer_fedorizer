# SPDX-License-Identifier: GPL-3.0-only
"""Shared read-only installation checks for the GTK interface and setup status."""
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .client import ControlClient, JsonDict

CHECKS=[('app','Application module'),('daemon','Daemon source files'),
        ('launcher','Desktop launcher'),('desktop','Desktop menu entry'),
        ('enabled','Daemon service enabled'),('running','Daemon service running'),
        ('socket','Control socket exists'),('ping','Daemon responds to ping'),
        ('module','Rear lightbar driver loaded'),('dkms','Rear lightbar driver installed for the running kernel')]


@dataclass(frozen=True)
class Check:
    """One installation check; ok is None when the result is unknown or informational."""
    key: str
    title: str
    ok: bool | None
    detail: str


@dataclass(frozen=True)
class Report:
    model: str
    kernel: str
    checks: list[Check]
    healthy: bool
    installed: bool


type Runner = Callable[..., subprocess.CompletedProcess[str]]


def collect_status(root: str | Path=Path('/'), run: Runner=subprocess.run) -> Report:
    base=Path(root)
    def path(value: str) -> Path: return base/value.lstrip('/')
    checks: list[Check]=[]
    def add(key: str, ok: bool | None, detail: str) -> None:
        checks.append(Check(key,dict(CHECKS)[key],ok,detail))
    def command(args: list[str]) -> tuple[bool | None, str]:
        try:
            result=run(args,capture_output=True,text=True,timeout=5,check=False)
            return result.returncode==0,(result.stdout.strip() or result.stderr.strip())
        except (OSError,subprocess.TimeoutExpired) as error: return None,str(error)
    try: model=path('/sys/class/dmi/id/product_name').read_text().strip()
    except OSError: model='Unknown'
    _,kernel=command(['uname','-r'])
    files=[('app','/opt/acer-fedorizer/control_center/__main__.py',False),
           ('daemon','/opt/acer-fedorizer/hardware/daemon.py',False),
           ('launcher','/usr/local/bin/acer-fedorizer',True),
           ('desktop','/usr/share/applications/io.github.SergiiChr.AcerFedorizer.desktop',False)]
    for key,filename,executable in files:
        item=path(filename)
        try: present=item.is_file() and (not executable or os.access(item,os.X_OK))
        except OSError as error: add(key,None,str(error)); continue
        add(key,present,'Installed.' if present else 'Missing or inaccessible.')
    for key,action,success in [('enabled','is-enabled','Enabled.'),('running','is-active','Running.')]:
        ok,detail=command(['systemctl',action,'fedorizer-daemon.service'])
        add(key,ok,success if ok else detail[:500] or 'Unavailable.')
    socket_path=path('/run/acer-fedorizer.sock')
    try: exists=socket_path.is_socket()
    except OSError: exists=False
    add('socket',exists,'Available.' if exists else 'The service socket is missing.')
    if exists:
        client=ControlClient(str(socket_path),timeout=3)
        try:
            client.command('ping'); add('ping',True,'Responding.')
        except (OSError,ValueError,RuntimeError) as error: add('ping',False,str(error)[:500])
        finally: client.close()
    else: add('ping',False,'Cannot connect without the service socket.')
    if model=='Predator PH16-72':
        loaded=path('/sys/module/laptop_lightbar').is_dir()
        add('module',loaded,'Loaded.' if loaded else 'Not loaded.')
        ok,detail=command(['dkms','status','-m','laptop-lightbar','-v','0.2.0','-k',kernel])
        if ok:
            installed=any(re.fullmatch(r'laptop-lightbar/0\.2\.0,\s*'+re.escape(kernel)+r',\s*[^:]+:\s*installed',line.strip()) for line in detail.splitlines())
            add('dkms',installed,'Installed for '+kernel+'.' if installed else 'Not installed for '+kernel+'.')
        else: add('dkms',None,'Could not read DKMS status: '+(detail[:500] or 'command failed'))
    else: add('module',None,'Not required for this model.')
    relevant=[c for c in checks if not (c.key=='module' and model!='Predator PH16-72')]
    return Report(model,kernel,checks,all(c.ok is True for c in relevant),path('/opt/acer-fedorizer').exists())


def main() -> int:
    report=collect_status()
    print('Acer Fedorizer installation status')
    print('Model: '+report.model+'\nKernel: '+report.kernel)
    if not report.installed: print('Not installed. Run ./setup.sh install.')
    for check in report.checks:
        print(('OK' if check.ok is True else 'FAIL' if check.ok is False else 'INFO')+': '+check.title)
        if check.ok is not True: print('  '+check.detail)
    if report.healthy: print('Installation is healthy.')
    else:
        print('Repair: run ./setup.sh install.')
        print('Service logs: journalctl -u fedorizer-daemon.service -b --no-pager -n 30')
    return 0 if report.healthy else 1


if __name__=='__main__': raise SystemExit(main())
