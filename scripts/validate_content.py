import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bunker.content import Content
if __name__=='__main__':
    counts=Content().validate()
    print('\n'.join(f'{k}: {v}' for k,v in counts.items()))
    print(f'Total requested categories: {sum(counts.values())}')
