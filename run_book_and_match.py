"""
run_book_and_match.py
Waits for book.bin to be generated, then runs ELO matches.
Run this AFTER gen_book.py is already running in background.
"""
import subprocess, sys, os, time

ROOT = r'C:\Users\Hiksh\Desktop\College\3rd\Alogrithm\pj\Deeper-Blue'
SF   = os.path.join(ROOT, 'stockfish', 'stockfish-windows-x86-64-avx2.exe')
BOOK = os.path.join(ROOT, 'c_engine', 'book.bin')

print('=== Waiting for book.bin ===', flush=True)
while not os.path.exists(BOOK):
    time.sleep(30)
    print(f'  still waiting... ({time.strftime("%H:%M:%S")})', flush=True)

print(f'\nbook.bin found ({os.path.getsize(BOOK)} bytes)', flush=True)

print('\n=== Step 2: ELO 1500 match (10 games) ===', flush=True)
subprocess.run([sys.executable, '-u', 'main.py', 'match',
    '--opponent', SF,
    '--elo', '1500', '--games', '10',
    '--output', 'data/match_v3_elo1500.csv'],
    cwd=ROOT)

print('\n=== Step 3: ELO 2000 match (10 games) ===', flush=True)
subprocess.run([sys.executable, '-u', 'main.py', 'match',
    '--opponent', SF,
    '--elo', '2000', '--games', '10',
    '--output', 'data/match_v3_elo2000.csv'],
    cwd=ROOT)

print('\n=== All done ===', flush=True)
