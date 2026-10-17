#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Record restored package licenses and retain bundled notices before publishing."""
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parents[1]
assets = json.loads((root / 'DivAcerManagerMax/obj/project.assets.json').read_text())
folders = [Path(p) for p in assets['packageFolders']]
rows = []
packages = dict(assets['libraries'])
# Self-contained runtime packs are download dependencies, not ordinary libraries.
for framework in assets['project']['frameworks'].values():
    for dependency in framework.get('downloadDependencies', []):
        versions = [v.strip() for v in dependency['version'].strip('[]').split(',')]
        if len(set(versions)) != 1:
            raise SystemExit('Expected an exact runtime-pack version')
        name = dependency['name'] + '/' + versions[0]
        packages[name] = dict(type='package', path=name.lower())
for name, meta in sorted(packages.items()):
    if meta['type'] != 'package':
        continue
    package = next((p / meta['path'] for p in folders if (p / meta['path']).exists()), None)
    if package is None:
        raise SystemExit(f'Missing restored package: {name}')
    nuspec = ET.parse(next(package.glob('*.nuspec'))).getroot()
    license_node = next((n for n in nuspec.iter() if n.tag.endswith('license')), None)
    if license_node is None:
        raise SystemExit(f'Missing package license declaration: {name}')
    notice_names = []
    for file in package.iterdir():
        if file.is_file() and any(word in file.name.lower() for word in ('license', 'notice', 'copying')):
            dest = root / 'LICENSES' / (name.replace('/', '-') + '-' + file.name)
            shutil.copyfile(file, dest)
            notice_names.append(dest.name)
    rows.append(f'| {name} | {license_node.text} | {", ".join(notice_names) or "Shared upstream texts in LICENSES"} |')
(root / 'THIRD-PARTY-NOTICES.md').write_text('''# Third-party components

Generated from the restored NuGet package metadata. Versioned native-package notices are retained in LICENSES. Shared MIT texts for Avalonia, DialogHost, LiveCharts, Material.Icons, MessageBox, MicroCom, and Tmds.DBus are retained with original copyright notices. Inter, Open Sans, and Oxanium font licenses and Material Design icon license notices are also included. .NET runtime MIT and third-party notices accompany the self-contained runtime.

| Package/version | Declared license | Bundled notices |
| --- | --- | --- |
''' + '\n'.join(rows) + '\n')
