"""Initialize a mounted /data directory, then permanently drop root privileges."""
import os
from pathlib import Path

def main():
    database=Path(os.getenv('DATABASE_PATH','/data/bunker.sqlite3'))
    database.parent.mkdir(parents=True,exist_ok=True)
    if os.geteuid()==0:
        os.chown(database.parent,10001,10001)
        for suffix in ('','-wal','-shm','.lock'):
            p=Path(str(database)+suffix)
            if p.exists(): os.chown(p,10001,10001)
        os.setgroups([]); os.setgid(10001); os.setuid(10001)
    if not os.access(database.parent,os.W_OK):
        raise SystemExit(f'Persistent directory must be writable by uid {os.getuid()}: {database.parent}')
    os.execvp('python',['python','-m','bunker.bot'])

if __name__=='__main__': main()
