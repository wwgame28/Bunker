"""Consistent online SQLite backup; do not copy just the .sqlite3 file in WAL mode."""
import argparse
import sqlite3
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('source'); p.add_argument('destination')
a=p.parse_args()
source=Path(a.source).resolve(); destination=Path(a.destination).resolve()
if source==destination or destination.exists(): raise SystemExit('Choose a new, different backup destination')
if not source.exists(): raise SystemExit('Source database does not exist')
destination.parent.mkdir(parents=True,exist_ok=True)
with sqlite3.connect(f'file:{source}?mode=ro',uri=True) as src, sqlite3.connect(destination) as dst:
    src.backup(dst)
    assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
print('Backup written:',destination)
