# SPDX-License-Identifier: GPL-3.0-only
import argparse
import sys


def main():
    parser=argparse.ArgumentParser(description='Acer Fedorizer native Linux control center')
    parser.add_argument('--preview',action='store_true',help='Use labelled preview data without hardware or session access')
    parser.add_argument('--screenshots',metavar='DIRECTORY',help='Capture every screen with preview data, then exit')
    args=parser.parse_args()
    try:
        from .app import Application
    except (ImportError,ValueError) as error:
        parser.exit(1,f'GTK4/libadwaita dependencies are unavailable: {error}\nRun ./setup.sh install.\n')
    app=Application(args.preview or bool(args.screenshots),args.screenshots)
    result=app.run([sys.argv[0]])
    return result or int(bool(getattr(app,'capture_error',None)))


if __name__=='__main__':
    raise SystemExit(main())
