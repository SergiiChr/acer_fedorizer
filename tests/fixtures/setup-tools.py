#!/usr/bin/python3
"""Fake external commands for isolated installer tests."""
import json
import os
import shutil
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
base = Path(os.environ['CONTROL_TEST_BASE'])
with (base / 'calls').open('a') as stream:
    stream.write(json.dumps([name, *args]) + '\n')
group = base / 'group'
module = base / 'sys/module/laptop_lightbar'
unit = base / 'etc/systemd/system/fedorizer-daemon.service'
if name == 'wait-daemon.py':
    sys.exit(7 if os.environ.get('CONTROL_TEST_PING_FAIL') or not (base/'service-running').exists() else 0)
elif name == 'uname':
    print({'-s':'Linux','-m':'x86_64','-r':'test-kernel'}[args[0]])
elif name == 'sudo':
    if args and args[0] == '--': args.pop(0)
    os.execvp(args[0], args)
elif name == 'wget':
    Path(args[args.index('-O')+1]).touch()
elif name == 'getent':
    if args and args[0]=='group':
        selected=base/'legacy-group' if args[1]=='damx' else group
        if not selected.exists(): sys.exit(2)
        record=selected.with_suffix('.record')
        print(record.read_text().strip() if record.exists() else args[1]+':x:901:test')
        sys.exit(0)
    if args[0] == 'passwd':
        print('test:x:1000:1000::/home/test:/bin/bash')
    else: sys.exit(2)
elif name == 'groupadd':
    selected=base/'legacy-group' if args[-1]=='damx' else group
    selected.touch()
    gid=args[args.index('--gid')+1] if '--gid' in args else '902'
    selected.with_suffix('.record').write_text(args[-1]+':x:'+gid+':')
elif name == 'groupdel':
    selected=base/'legacy-group' if args[-1]=='damx' else group
    selected.unlink(missing_ok=True); selected.with_suffix('.record').unlink(missing_ok=True)
elif name == 'gpasswd':
    selected=base/'legacy-group' if args[-1]=='damx' else group
    record=selected.with_suffix('.record')
    fields=record.read_text().split(':'); fields[3]=args[args.index('--members')+1]
    record.write_text(':'.join(fields))
elif name == 'pkill':
    sys.exit(1)
elif name == 'systemctl':
    legacy=any(arg=='damx-daemon.service' for arg in args)
    prefix='legacy-service' if legacy else 'service'
    running=base/(prefix+'-running'); enabled=base/(prefix+'-enabled'); disabled=base/(prefix+'-disabled')
    unhealthy=base/(prefix+'-unhealthy')
    if args[0] == 'cat':
        target=unit.with_name('damx-daemon.service') if legacy else unit
        sys.exit(0 if target.exists() else 1)
    if args[0]=='is-active': sys.exit(0 if running.exists() and not unhealthy.exists() else 1)
    if args[0]=='is-enabled': sys.exit(0 if enabled.exists() or (running.exists() and not disabled.exists()) else 1)
    if args[0]=='enable':
        enabled.touch(); disabled.unlink(missing_ok=True)
        if '--now' in args:
            running.touch()
            if not legacy and os.environ.get('CONTROL_TEST_SERVICE_UNHEALTHY'): unhealthy.touch()
            if not legacy and os.environ.get('CONTROL_TEST_SERVICE_FAIL'): sys.exit(7)
    if args[0]=='disable':
        enabled.unlink(missing_ok=True); disabled.touch()
        if '--now' in args: running.unlink(missing_ok=True); unhealthy.unlink(missing_ok=True)
    if args[0]=='stop': running.unlink(missing_ok=True); unhealthy.unlink(missing_ok=True)
    if args[0]=='start':
        if os.environ.get('CONTROL_TEST_RESTORE_FAIL'): sys.exit(8)
        running.touch(); unhealthy.unlink(missing_ok=True)
elif name == 'modprobe':
    if len(args)==2 and args[0]=='-r' and args[1] in ('laptop_lightbar','damx_lightbar'):
        module=base/'sys/module'/args[1]
        if os.environ.get('CONTROL_TEST_UNLOAD_FAIL'):
            sys.exit(1)
        if module.exists(): shutil.rmtree(module)
    elif args == ['acer_wmi'] and os.environ.get('CONTROL_TEST_ACER_FAIL'):
        sys.exit(1)
    elif args in (['laptop_lightbar'],['damx_lightbar']):
        marker=base/'new-load-failed'
        if args==['laptop_lightbar'] and os.environ.get('CONTROL_TEST_LOAD_FAIL') and not marker.exists():
            marker.touch(); sys.exit(9)
        (base/'sys/module'/args[0]).mkdir(parents=True,exist_ok=True)
elif name == 'dkms':
    action=args[0]
    version=args[args.index('-v')+1] if '-v' in args else '0.2.0'
    module_name=args[args.index('-m')+1] if '-m' in args else 'laptop-lightbar'
    tree=Path(args[args.index('--dkmstree')+1]) if '--dkmstree' in args else base/'var/lib/dkms'
    sources=Path(args[args.index('--sourcetree')+1]) if '--sourcetree' in args else base/'usr/src'
    entry=tree/module_name/version
    if action == 'status':
        if entry.exists():
            # More than a pipe buffer: the former grep -q approach caused SIGPIPE.
            for _ in range(2000):
                print(f'laptop-lightbar/{version}, test-kernel, x86_64: installed')
    elif action == 'remove':
        if os.environ.get('CONTROL_TEST_REMOVE_FAIL'): sys.exit(9)
        if entry.exists(): shutil.rmtree(entry)
    elif action == 'add':
        if entry.exists():
            print('DKMS tree already contains this module/version',file=sys.stderr)
            sys.exit(3)
        entry.mkdir(parents=True)
        (entry/'source').symlink_to(sources/f'{module_name}-{version}')
    elif action == 'build':
        if '--installtree' in args and not (Path(args[args.index('--installtree')+1])/'test-kernel/build').is_dir():
            print('DKMS cannot find matching headers through installtree',file=sys.stderr); sys.exit(21)
        if os.environ.get('CONTROL_TEST_BUILD_FAIL'): sys.exit(6)
    elif action == 'install':
        if os.environ.get('CONTROL_TEST_INSTALL_FAIL'): sys.exit(7)
        (base/'lib/modules/test-kernel/extra').mkdir(parents=True,exist_ok=True)
        (base/'lib/modules/test-kernel/extra/laptop_lightbar.ko').touch()
