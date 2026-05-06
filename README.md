# Deeper-Blue

> Algorithm-based chess engine that challenges Deep Blue's 1997 moves, evaluated by Stockfish

알고리즘 수업 프로젝트 — 머신러닝·딥러닝 없이 **순수 알고리즘**만으로 1997년 딥블루의 수를 이기는 것을 목표로 합니다.  
[1997 Kasparov vs Deep Blue](https://en.wikipedia.org/wiki/Deep_Blue_versus_Kasparov,_1997,_Game_6) 의 기보를 활용해 미들게임·엔드게임 구간에서 우리 엔진의 수와 딥블루의 실제 수를 **Stockfish centipawn 점수**로 비교합니다.

---

## 최신 벤치마크 결과

> 조건: depth=4, 수당 3초, Stockfish 18 평가, 22개 포지션 (move ≥ 15, middlegame)

| 버전 | 승 | 패 | 무 | 승률 | 평균 델타 |
|------|----|----|-----|------|----------|
| **v1** (초기) | 5/22 | 11/22 | 6/22 | 22.7% | — |
| **v2** (개선) | **6/22** | 11/22 | 5/22 | **27.3%** | **+17.7 cp** |

> 평균 델타(+값) = Stockfish 기준 우리 수가 딥블루 수보다 평균 얼마나 좋은지 (cp)

### v1 → v2 주요 변화 포지션

| 포지션 | v1 | v2 | 변화 |
|--------|----|----|------|
| Game 3, move 17 | equal (-2 cp) | **ours (+17 cp)** | 역전 승 |
| Game 3, move 19 | equal (+4 cp) | **ours (+173 cp)** | 대폭 개선 |
| Game 5, move 16 | deep_blue (-50 cp) | **ours (+55 cp)** | 역전 승 |

---

## 프로젝트 구조

```
Deeper-Blue/
├── engine/
│   ├── minimax.py         # 탐색 엔진 (Negamax, Alpha-Beta, PVS, LMR, QSearch, TT...)
│   ├── evaluation.py      # 정적 평가 함수 (기물, PST, 폰 구조, 비숍쌍, 룩, 킹, 모빌리티)
│   └── move_ordering.py   # 무브 정렬 (MVV-LVA, Killer, History, Check bonus)
├── analysis/
│   ├── pgn_parser.py      # PGN → FEN 추출, 미들/엔드게임 분류
│   ├── comparator.py      # 우리 수 vs 딥블루 수 → Stockfish 비교
│   ├── engine_match.py    # 외부 UCI 엔진과 실제 게임 대전 (W/D/L 집계)
│   └── visualizer.py      # 비교 결과 차트 생성
├── game/
│   └── chess_gui.py       # Pygame GUI (사람 vs 엔진, 평가 바 포함)
├── web/
│   ├── app.py             # Flask 백엔드 (REST API)
│   └── templates/
│       └── index.html     # 웹 체스 UI (chessboard.js)
├── data/
│   └── pgn/               # 1997 Kasparov vs Deep Blue 6경기 PGN
├── stockfish/             # Stockfish 바이너리 (별도 다운로드 필요)
├── main.py                # CLI 진입점
├── requirements.txt       # 서버/배포용 의존성
├── requirements-local.txt # 로컬 GUI 포함 의존성
└── render.yaml            # Render 배포 설정
```

---

## 핵심 알고리즘 (engine/minimax.py)

### 1. Negamax + Alpha-Beta Pruning

기본 Minimax를 부호 통일 형태(Negamax)로 구현합니다.  
Alpha-Beta Pruning으로 탐색 트리를 가지치기해 평균 `O(b^(d/2))`로 줄입니다.

```
negamax(board, depth, α, β):
    if depth == 0: return quiescence(board, α, β)
    for move in ordered_moves(board):
        score = -negamax(after(move), depth-1, -β, -α)
        if score >= β: return score  # beta cutoff (prune)
        α = max(α, score)
    return α
```

### 2. Principal Variation Search (PVS)

첫 번째 수는 전체 창 `[-β, -α]`으로 탐색하고, 이후 수들은 **null window** `[-α-1, -α]`로 탐색합니다.  
null window 탐색이 alpha를 넘으면 전체 창으로 재탐색합니다.  
→ 같은 품질, 더 적은 노드 탐색.

```
if move_idx == 0:
    score = -negamax(depth-1, -β, -α)      # full window
else:
    score = -negamax(depth-1, -α-1, -α)    # null window
    if score > α:
        score = -negamax(depth-1, -β, -α)  # re-search
```

### 3. Iterative Deepening (ID) + Aspiration Windows

깊이 1부터 반복적으로 늘립니다.  
이전 반복의 점수를 중심으로 좁은 탐색 창(±50cp)을 설정해 더 많은 가지치기를 유도합니다.  
창 밖으로 점수가 벗어나면 전체 창으로 재탐색합니다.

### 4. Check Extension

체크 상황에서 `depth == 0`에 도달하면 `depth = 1`로 연장합니다.  
→ 체크메이트 패턴, 포크, 핀 등 전술적 수순을 놓치지 않도록 방지합니다.

```
if in_check and depth <= 0:
    depth = 1   # extend: don't enter quiescence while in check
```

### 5. Quiescence Search + Delta Pruning

수평선 효과(Horizon Effect)를 방지하기 위해 `depth == 0`에서 캡처·프로모션만 계속 탐색합니다.  
Stand-pat 점수로 하한을 잡고, **Delta Pruning**으로 alpha를 회복할 수 없는 캡처를 건너뜁니다.

```
stand_pat = evaluate(board)
if stand_pat + piece_value + 200 <= alpha: skip  # delta pruning
```

### 6. Transposition Table (TT)

`chess.polyglot.zobrist_hash`로 포지션을 해싱해 이전 탐색 결과를 재사용합니다.

| 플래그 | 의미 |
|--------|------|
| `TT_EXACT` | 정확한 점수 |
| `TT_LOWER` | beta cutoff 발생 — 하한값 |
| `TT_UPPER` | alpha 갱신 실패 — 상한값 |

항상 최신 결과로 덮어씌우는 방식(always-replace). 최대 ~100만 항목.

### 7. Late Move Reduction (LMR)

log 기반 공식으로 뒤쪽의 조용한 무브를 깊이를 줄여 탐색합니다.  
alpha를 넘으면 전체 깊이로 재탐색합니다.

```
reduction = max(1, int(√(depth-1) × √moves_searched))
```

- `depth < 3` 또는 앞쪽 4수는 적용 안 함
- 캡처, 프로모션, 체크 주는 수, 체크 중인 수는 적용 안 함

### 8. Null Move Pruning (NMP)

빈 수를 두어도 beta cutoff가 발생하면, 실제 수를 두면 더 좋다는 가정으로 조기 반환합니다.  
Zugzwang 방지를 위해 주요 기물(Q·R·B·N) 2개 이상일 때만 적용합니다.

```
감소량 R = 3 (depth ≥ 6)  /  R = 2 (depth < 6)
```

### 9. Futility Pruning

depth 1~2에서 정적 평가 + 마진이 alpha 이하면 조용한 무브를 건너뜁니다.

| depth | 마진 |
|-------|------|
| 1 | 100 cp |
| 2 | 300 cp |

---

## 무브 정렬 (engine/move_ordering.py)

좋은 무브를 먼저 탐색할수록 Alpha-Beta 가지치기 효율이 올라갑니다.

| 우선순위 | 기법 | 설명 |
|----------|------|------|
| 1 | **PV Move** | 이전 반복의 TT에서 찾은 최선 수 |
| 2 | **Winning Captures** | SEE > 0: 교환 후 실제 이득이 나는 캡처 |
| 3 | **Equal Captures** | SEE == 0: 등가 교환 |
| 4 | **Promotions** | 퀸 프로모션 우선 |
| 5 | **Check-giving Moves** | 체크 수는 강제적 특성상 먼저 탐색 |
| 6 | **Killer Moves** | 같은 깊이에서 beta cutoff를 일으킨 조용한 수 (최대 2개) |
| 7 | **History Heuristic** | 과거 beta cutoff 빈도 기반 (`depth²` 가중치) |
| 8 | **Losing Captures** | SEE < 0: 손해 교환은 맨 마지막 탐색 |

### SEE (Static Exchange Evaluation)

캡처 수의 교환 연속을 시뮬레이션해 실제 손익을 계산합니다.  
MVV-LVA는 첫 수만 보지만, SEE는 **재캡처까지 전부 고려**합니다.

```
예: 폰이 비숍 포획 (상대 룩이 지킴)
  MVV-LVA → 이득처럼 보임 (victim 비숍 = 330)
  SEE     → 330 - 100 = 230cp  (실제 이득, 정확)

예: 퀸이 폰 포획 (상대 룩이 지킴)
  MVV-LVA → 이득처럼 보임
  SEE     → 100 - 900 < 0  → 손해, 맨 마지막으로 정렬
```

**gain[] 배열로 교환 시뮬레이션 후 역방향 전파:**

```python
gain[0] = value(captured_piece)   # 첫 포획 이득
# 각 재캡처마다 gain[d] = value(piece_on_square)
# 역방향 전파: gain[i] = max(gain[i] - gain[i+1], 0)  # 재캡처 거부 옵션
```

Quiescence Search에서도 `SEE < 0`인 캡처를 즉시 건너뛰어 손해 교환 탐색을 제거합니다.

---

## 평가 함수 (engine/evaluation.py)

모든 점수는 **White 관점 centipawns** 기준. 양수 = 백 유리.

### 기물 가중치

| 기물 | 가치 |
|------|------|
| 폰 (P) | 100 cp |
| 나이트 (N) | 320 cp |
| 비숍 (B) | 330 cp |
| 룩 (R) | 500 cp |
| 퀸 (Q) | 900 cp |

### Piece-Square Table (PST) + 테이퍼드 평가

기물마다 위치 보너스 테이블을 갖습니다.  
게임 페이즈(0.0=미들, 1.0=엔드)에 따라 MG/EG 테이블을 선형 보간합니다.

```python
score = mg_value × (1 - phase) + eg_value × phase
```

| 기물 | MG 테이블 | EG 테이블 |
|------|-----------|-----------|
| 폰 | 중앙 전진, 전방 지향 | 승진 가까울수록 높은 점수 |
| 나이트 | 중앙 선호, 가장자리 패널티 | 동일 |
| 비숍 | 대각선 활동 우선 | 동일 |
| 룩 | 7랭크, 중앙 파일 | 동일 |
| 퀸 | 조기 전개 억제 | 동일 |
| 킹 | 캐슬링 후 코너 안전 | 중앙 집중 보너스 |

### 게임 페이즈

남은 주요 기물(Q·R·B·N)의 수로 0.0~1.0 계산합니다.

```
phase = 1.0 - (현재 기물 가중치 합 / 24)
Q=4, R=2, B=1, N=1 기준 (최대 합 = 24)
```

### 폰 구조

| 항목 | 패널티/보너스 |
|------|-------------|
| 이중 폰 (Doubled) | -20 cp |
| 고립 폰 (Isolated) | -30 cp |
| 백워드 폰 (Backward) | -20 cp (앞길이 막히고 뒤 지원 없음) |
| 패스트 폰 (Passed) | +10 ~ +120 cp (랭크에 따라 증가) |

### 비숍 쌍 보너스

양색 비숍(밝은칸 + 어두운칸) 모두 보유 시 **+50 cp**  
오픈 포지션에서 비숍 쌍은 강력한 전략적 이점입니다.

### 룩 보너스

| 항목 | 보너스 |
|------|--------|
| 오픈 파일 (양쪽 폰 없음) | +25 cp |
| 세미오픈 파일 (자기 폰 없음) | +12 cp |
| 7랭크 (흑은 2랭크) 진출 | +25 cp |

### 아웃포스트 (Outpost)

상대 폰이 공격할 수 없는 전진 거점에 위치한 나이트·비숍에 보너스를 부여합니다.

| 조건 | 보너스 |
|------|--------|
| 나이트, 5랭크 이상, 상대 폰 공격 없음 | +25 cp |
| 비숍, 5랭크 이상, 상대 폰 공격 없음 | +15 cp |
| 위 조건 + 자기 폰이 아웃포스트 방어 | +15 cp 추가 |

```
예: 백 나이트 d5 (상대 폰 없음, 자기 폰 c4가 지킴)
    → +25 + 15 = +40 cp
```

### 연결 룩 (Connected Rooks)

두 룩이 같은 랭크 또는 파일에서 사이에 기물 없이 서로를 볼 수 있을 때 **+20 cp**.  
`board.attacks(r1)`에 r2가 포함되는지로 판정 (중간 기물이 없으면 포함됨).

### 킹 안전

| 단계 | 평가 방식 |
|------|----------|
| 미들게임 | 킹 주변 폰 방패 보너스, 킹 인근 오픈 파일 패널티 |
| 엔드게임 | 킹이 중앙에 가까울수록 보너스 |

### 모빌리티

나이트·비숍·룩·퀸이 공격 가능한 칸 수 × **2 cp**  
(자기 기물 점령 칸 제외)

---

## 비교 방식 (analysis/)

### PGN 파싱 (pgn_parser.py)

1997 Kasparov vs Deep Blue 6경기 PGN 파일을 파싱해 포지션을 추출합니다.

**게임 페이즈 기준:**

| 구분 | 기준 | 근거 |
|------|------|------|
| 오프닝 (제외) | move < 15 | 딥블루도 오프닝 북 사용 → 알고리즘 비교 무의미 |
| 미들게임 | move ≥ 15, 주요 기물 > 6 | 양쪽 전개 완료, 포지셔널 판단 시작 |
| 엔드게임 | move ≥ 15, 주요 기물 ≤ 6 | Q·R·B·N 합계 기준 |

### 비교 로직 (comparator.py)

```
for position in deep_blue_games[move >= 15]:
    our_move  = SearchEngine.search(position)
    db_move   = pgn_record[position]

    our_score = Stockfish.eval(position + our_move)   # centipawns
    db_score  = Stockfish.eval(position + db_move)

    delta = our_score - db_score
    if delta > 10cp  → 우리 승
    if delta < -10cp → 딥블루 승
    else             → 동점
```

### 엔진 대전 (engine_match.py)

기보 비교의 한계(포지션 고립 비교)를 보완하기 위해, 외부 UCI 엔진과 **실제 전 게임**을 플레이합니다.

- Crafty 등 당대 수준의 오픈소스 엔진, 또는 ELO 제한 Stockfish 사용
- 컬러를 교대로 N게임 진행 후 W/D/L 집계
- 각 게임의 종료 사유(체크메이트, 스테일메이트, 반복 등) 함께 기록

```
for game in range(n_games):
    our_color = WHITE if game % 2 == 0 else BLACK
    play full game → SearchEngine vs opponent_engine
    record win / draw / loss + termination
```

---

## 실행 모드 (main.py)

### 1. 딥블루 기보 비교

```bash
python main.py compare
python main.py compare --depth 5 --time 3.0 --verbose --output results.csv
python main.py compare --charts output/   # 비교 후 차트도 생성
```

### 2. 결과 시각화

```bash
python main.py visualize --csv results.csv           # 창에 표시
python main.py visualize --csv results.csv --charts output/  # 파일로 저장
```

### 3. 단일 FEN 분석

```bash
python main.py analyze --fen "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
python main.py analyze --fen "..." --depth 6 --time 10
```

출력: 엔진의 최선 수 + 점수 + (Stockfish 참고 평가)

### 4. 인터랙티브 CLI 모드

```bash
python main.py play
python main.py play --depth 5 --time 5.0
```

FEN을 입력하면 엔진이 최선 수를 제안합니다.

### 5. Pygame GUI (사람 vs 엔진)

```bash
python main.py play-human                  # 백으로 플레이
python main.py play-human --color black    # 흑으로 플레이
python main.py play-human --depth 5 --time 5.0
```

### 6. 엔진 대전 (UCI 엔진 vs Deeper-Blue)

```bash
# ELO 2200 제한 Stockfish 상대 10게임 (1990년대 수준 시뮬레이션)
python main.py match --opponent stockfish/stockfish.exe --elo 2200 --games 10

# Crafty 상대 (http://craftychess.com/ 에서 다운로드)
python main.py match --opponent crafty.exe --games 20

# 결과 CSV 저장
python main.py match --opponent stockfish/stockfish.exe --elo 2200 --games 20 --output match.csv
```

**출력 예시:**
```
============================================================
  DEEPER-BLUE vs stockfish (ELO 2200)
============================================================
  Games played : 10
  Score        : 6.0/10  (4W / 4D / 2L)
  Score %      : 60.0%

  Game-by-game:
    Game  1 (White): W  [checkmate, 42 moves]
    Game  2 (Black): D  [50_moves, 100 moves]
    ...
============================================================
```

**`--elo` 기준 (Stockfish 한정):**

| ELO | 대략적 수준 |
|-----|------------|
| 1500 | 아마추어 |
| 2000 | 강한 아마추어 |
| 2200 | 1990년대 강한 컴퓨터 엔진 수준 |
| 2600 | 1997 딥블루 추정 ELO |
| (제한 없음) | Stockfish 풀 강도 (~3600) |

**키 조작:**

| 키 | 기능 |
|----|------|
| 클릭 | 기물 선택 / 이동 |
| `R` | 새 게임 |
| `F` | 보드 뒤집기 |
| `S` | 평가 점수 바 켜기/끄기 |
| `Q` / `Esc` | 종료 |

**평가 점수 바:**
- 패널 상단에 흰색/검정 비율로 현재 유불리를 시각화
- 숫자: `+2.15` = 백이 2.15폰 유리, `-1.30` = 흑이 유리
- 체크메이트 예상 시 `M4` 형태로 표시
- 엔진 수 후: 탐색 점수(더 정확) / 사람 수 후: 정적 평가

### CLI 공통 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--depth N` | 4 | 탐색 깊이 (플라이) |
| `--time SEC` | 5.0 | 수당 시간 제한 (초) |
| `--stockfish PATH` | 자동 탐지 | Stockfish 바이너리 경로 |
| `--verbose` | False | 포지션별 상세 출력 |
| `--output FILE` | None | CSV 결과 저장 |

---

## 웹 인터페이스 (web/)

Flask 백엔드 + chessboard.js 프론트엔드로 구성된 웹 체스 UI입니다.

### 로컬 실행

```bash
python web/app.py
# → http://localhost:5000
```

### API 엔드포인트

| Method | Endpoint | 설명 |
|--------|----------|------|
| `GET` | `/` | 웹 UI 서빙 |
| `POST` | `/api/new_game` | 새 게임 시작 `{"player_color": "white"\|"black"}` |
| `POST` | `/api/move` | 사람 수 전송 `{"move": "e2e4"}` (UCI 형식) |
| `GET` | `/api/state` | 현재 보드 상태 조회 |

### 웹 UI 기능

- 드래그&드롭 기물 이동
- 폰 프로모션 팝업 (퀸/룩/비숍/나이트 선택)
- 엔진 생각 중 애니메이션
- 무브 히스토리 (SAN 표기)
- 현재 차례 표시

### 배포 (Render)

```bash
# render.yaml 설정 기준
Start Command: gunicorn web.app:app
```

---

## 설치 및 실행

### 1. 의존성 설치

```bash
# 서버/비교 분석용 (배포 환경)
pip install -r requirements.txt

# 로컬 GUI 포함 (play-human 모드 필요)
pip install -r requirements-local.txt
```

### 2. Stockfish 설치 (비교 모드 필요)

[https://stockfishchess.org/download/](https://stockfishchess.org/download/) 에서 다운로드 후  
`stockfish/` 디렉토리에 바이너리를 배치하세요.

> 웹 모드(`web/app.py`)와 GUI 모드(`play-human`)는 Stockfish 없이 동작합니다.

---

## 데이터: 1997 Kasparov vs Deep Blue

| 게임 | 백 | 흑 | 결과 | 딥블루 색 |
|------|----|----|------|---------|
| Game 1 | Kasparov | Deep Blue | 1-0 | Black |
| Game 2 | Deep Blue | Kasparov | 1-0 | White |
| Game 3 | Kasparov | Deep Blue | 1/2-1/2 | Black |
| Game 4 | Deep Blue | Kasparov | 1/2-1/2 | White |
| Game 5 | Kasparov | Deep Blue | 1-0 | Black |
| Game 6 | Deep Blue | Kasparov | 1-0 | White |

> **참고**: `data/pgn/` 의 PGN 파일은 공개 기록을 기반으로 작성되었습니다.  
> 더 정확한 원본 기보는 [PGN Mentor](https://www.pgnmentor.com/) 등에서 다운로드하여 교체하세요.

---

## 알고리즘 수업 연관성

딥블루가 채택한 핵심 기법과 Deeper-Blue의 대응:

| 딥블루 | Deeper-Blue | 구현 위치 |
|--------|-------------|----------|
| Minimax + Alpha-Beta | Negamax + Alpha-Beta (fail-soft) | `minimax.py` |
| Principal Variation Search | PVS — null window after first move | `minimax.py` |
| Iterative Deepening | + Aspiration Windows (±50cp) | `minimax.py` |
| Check Extension | depth=0에서 체크 시 depth=1 연장 | `minimax.py` |
| Quiescence Search | + Delta Pruning + SEE < 0 Pruning | `minimax.py` |
| Transposition Table | Zobrist Hashing (polyglot), always-replace | `minimax.py` |
| Move Ordering | PV + **SEE** (winning/equal/losing) + Check + Killer + History | `move_ordering.py` |
| Null Move Pruning | 적응형 R=2/3, major piece guard | `minimax.py` |
| Late Move Reduction | log 기반: √(d-1)×√moves | `minimax.py` |
| Futility Pruning | depth 1~2, margin 100/300 cp | `minimax.py` |
| Evaluation Function | Material + PST + Pawn + Bishop pair + Rook + **Outpost** + **Connected Rooks** + King + Mobility | `evaluation.py` |
| Opening Book | 미사용 (move 15 이후만 비교) | — |
| Endgame Tablebase | 미구현 (향후 추가 가능) | — |

---

## 향후 계획

- [ ] Endgame Tablebase (Syzygy) 연동
- [ ] 웹 UI 평가 점수 바 추가
- [ ] 통계적 유의성 검증 (t-test / p-value) — 비교 결과의 신뢰도 수치화
