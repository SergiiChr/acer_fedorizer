#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded startup check: ping the new service before discarding rollback data."""
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from control_center.client import ControlClient


def wait_for_daemon(path,timeout=10,client_factory=ControlClient,clock=time.monotonic,pause=time.sleep):
    deadline=clock()+timeout
    last_error='No response'
    while True:
        remaining=deadline-clock()
        if remaining<=0: break
        client=client_factory(path,timeout=min(1,remaining))
        try:
            result=client.command('ping')
            if not isinstance(result,dict) or not isinstance(result.get('version'),str):
                raise ValueError('Invalid daemon ping response')
            return
        except (OSError,ValueError,RuntimeError) as error: last_error=str(error)
        finally: client.close()
        pause(min(.1,max(0,deadline-clock())))
    raise RuntimeError('Daemon did not become ready: '+last_error)


if __name__=='__main__':
    if len(sys.argv)!=2: raise SystemExit('Expected the service socket path')
    try: wait_for_daemon(sys.argv[1])
    except RuntimeError as error: raise SystemExit(str(error)) from error
