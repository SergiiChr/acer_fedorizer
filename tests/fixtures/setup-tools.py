#!/usr/bin/python3
"""Fake external commands for isolated installer tests."""
import json
import os
from pathlib import Path
import shutil
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
base = Path(os.environ['DAMX_TEST_BASE'])
with (base / 'calls').open('a') as stream:
    stream.write(json.dumps([name, *args]) + '\n')
group = base / 'group'
module = base / 'sys/module/damx_lightbar'
unit = base / 'etc/systemd/system/damx-daemon.service'
if name == 'uname':
    print({'-s':'Linux','-m':'x86_64','-r':'test-kernel'}[args[0]])
elif name == 'sudo':
    if args and args[0] == '--': args.pop(0)
    os.execvp(args[0], args)
elif name == 'wget':
    Path(args[args.index('-O')+1]).touch()
elif name == 'getent':
    if args == ['group','damx']:
        sys.exit(0 if group.exists() else 2)
    if args[0] == 'passwd':
        print('test:x:1000:1000::/home/test:/bin/bash')
    else:
        sys.exit(2)
elif name == 'groupadd':
    group.touch()
elif name == 'groupdel':
    group.unlink(missing_ok=True)
elif name == 'pkill':
    sys.exit(1)
elif name == 'systemctl':
    if args[0] == 'cat':
        sys.exit(0 if unit.exists() else 1)
    if args[0] in ('is-active','is-enabled'):
        sys.exit(0 if (base/'service-running').exists() else 1)
    if args[0] == 'enable':
        (base/'service-running').touch()
    if args[0] == 'disable':
        (base/'service-running').unlink(missing_ok=True)
elif name == 'modprobe':
    if args == ['-r','damx_lightbar']:
        if os.environ.get('DAMX_TEST_UNLOAD_FAIL'):
            sys.exit(1)
        if module.exists(): shutil.rmtree(module)
    elif args == ['acer_wmi'] and os.environ.get('DAMX_TEST_ACER_FAIL'):
        sys.exit(1)
    elif args == ['damx_lightbar']:
        module.mkdir(parents=True,exist_ok=True)
elif name == 'dkms':
    action=args[0]
    version=args[args.index('-v')+1] if '-v' in args else '0.2.0'
    entry=base/'var/lib/dkms/damx-lightbar'/version
    if action == 'status':
        if entry.exists():
            # More than a pipe buffer: the former grep -q approach caused SIGPIPE.
            for _ in range(2000):
                print(f'damx-lightbar/{version}, test-kernel, x86_64: installed')
    elif action == 'remove':
        if os.environ.get('DAMX_TEST_REMOVE_FAIL'): sys.exit(9)
        if entry.exists(): shutil.rmtree(entry)
    elif action == 'add':
        if entry.exists():
            print('DKMS tree already contains this module/version',file=sys.stderr)
            sys.exit(3)
        entry.mkdir(parents=True)
        (entry/'source').symlink_to(base/'usr/src'/f'damx-lightbar-{version}')
    elif action == 'install':
        (base/'lib/modules/test-kernel/extra').mkdir(parents=True,exist_ok=True)
        (base/'lib/modules/test-kernel/extra/damx_lightbar.ko').touch()
