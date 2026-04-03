# Deeper-Blue

> Algorithm-based chess engine that challenges Deep Blue's 1997 moves, evaluated by Stockfish

알고리즘 수업 프로젝트 — 머신러닝·딥러닝 없이 **순수 알고리즘**만으로 1997년 딥블루의 수를 이기는 것을 목표로 합니다.  
[1997 Kasparov vs Deep Blue](https://en.wikipedia.org/wiki/Deep_Blue_versus_Kasparov,_1997,_Game_6) 의 기보를 활용해 미들게임·엔드게임 구간에서 우리 엔진의 수와 딥블루의 실제 수를 **Stockfish centipawn 점수**로 비교합니다.

---

## 프로젝트 구조

```
Deeper-Blue/
├── engine/
│   ├── evaluation.py      # 정적 평가 함수 (기물 가중치, PST, 폰 구조, 킹 안전, 모빌리티)
│   ├── minimax.py         # 탐색 엔진 (Negamax + Alpha-Beta + ID + QSearch + TT)
│   └── move_ordering.py   # 무브 정렬 (MVV-LVA, Killer, History, Check bonus)
├── analysis/
│   ├── pgn_parser.py      # PGN → FEN 추출, 미들/엔드게임 분류
│   └── comparator.py      # 우리 수 vs 딥블루 수 → Stockfish 비교
├── data/
│   └── pgn/               # 1997 Kasparov vs Deep Blue 6경기 PGN
├── stockfish/             # Stockfish 바이너리 (별도 다운로드 필요)
├── main.py                # CLI 진입점
├── requirements.txt
└── .gitignore
```

---

## 핵심 알고리즘

### 1. Negamax + Alpha-Beta Pruning

기본 Minimax를 부호 통일 형태(Negamax)로 구현합니다.  
Alpha-Beta Pruning으로 탐색 트리를 가지치기하여 평균 `O(b^(d/2))`로 줄입니다.

```
negamax(board, depth, α, β):
    if depth == 0: return quiescence(board, α, β)
    for move in ordered_moves(board):
        score = -negamax(after(move), depth-1, -β, -α)
        if score >= β: return score  # beta cutoff (prune)
        α = max(α, score)
    return α
```

### 2. Iterative Deepening (ID) + Aspiration Windows

깊이 1부터 시작해 반복적으로 깊이를 늘립니다.  
이전 반복의 점수를 중심으로 좁은 탐색 창(±50cp)을 설정해 더 많은 가지치기를 유도합니다.  
창 밖으로 점수가 벗어나면 전체 창으로 재탐색합니다.

### 3. Quiescence Search

수평선 효과(Horizon Effect)를 방지하기 위해 depth=0에 도달하면 캡처 무브만 계속 탐색합니다.  
Stand-pat 점수로 하한을 잡고 Delta Pruning으로 불필요한 캡처를 건너뜁니다.

### 4. Transposition Table

`chess.polyglot.zobrist_hash`로 포지션을 해싱해 캐싱합니다.  
`TT_EXACT / TT_LOWER / TT_UPPER` 플래그로 정확한 재사용 조건을 관리합니다.

### 5. Move Ordering

좋은 무브를 먼저 탐색할수록 Alpha-Beta 가지치기 효율이 올라갑니다.

| 우선순위 | 기법 | 설명 |
|----------|------|------|
| 1 | PV Move | 이전 반복에서 최선으로 찾은 수 |
| 2 | Winning Captures | MVV-LVA: 가장 값진 기물을 가장 싼 기물로 잡기 |
| 3 | Check-giving Moves | 체크 수는 강제적 특성상 먼저 탐색 |
| 4 | Killer Moves | 같은 깊이에서 beta-cutoff를 일으킨 조용한 수 |
| 5 | History Heuristic | 과거에 cutoff를 일으킨 빈도 기반 점수 |

### 6. Late Move Reduction (LMR)

이동 순서 후반부의 조용한 무브는 깊이를 줄여 탐색하고, alpha를 넘으면 전체 깊이로 재탐색합니다.

### 7. Null Move Pruning (NMP)

빈 수를 두어도 beta cutoff가 발생하면 실제 수를 두면 더 좋다는 가정으로 조기 반환합니다.  
Zugzwang 방지를 위해 주요 기물이 2개 이상일 때만 적용합니다.

### 8. Futility Pruning

depth 1~2에서 정적 평가 + 마진이 여전히 alpha 이하이면 조용한 무브를 건너뜁니다.

---

## 평가 함수 (evaluation.py)

| 컴포넌트 | 설명 |
|----------|------|
| **기물 가중치** | P=100, N=320, B=330, R=500, Q=900 cp |
| **Piece-Square Table** | 기물 종류별 위치 보너스 (Middlegame/Endgame 테이퍼드 적용) |
| **게임 페이즈** | 남은 주요 기물 수로 0.0(미들)~1.0(엔드) 계산, PST·킹 가중치 보간 |
| **폰 구조** | 이중폰(-20), 고립폰(-30), 패스트폰(+10~+120 승급 기준) |
| **킹 안전** | 미들게임: 폰 방패·오픈 파일 페널티 / 엔드게임: 중앙 접근 보너스 |
| **모빌리티** | 공격 가능 칸 수(자기 기물 제외) × 2cp |

---

## 비교 방식 (Comparator)

```
for position in deep_blue_games[move >= 15]:
    our_move  = SearchEngine.search(position)
    db_move   = pgn_record[position]

    our_score = Stockfish.eval(position + our_move)   # centipawns
    db_score  = Stockfish.eval(position + db_move)

    if our_score - db_score > 10cp: → 우리 승
    elif db_score - our_score > 10cp: → 딥블루 승
    else: → 동점
```

### 미들/엔드게임 기준

| 구분 | 기준 | 근거 |
|------|------|------|
| **오프닝** | move < 15 | 딥블루도 오프닝 북 사용, 알고리즘 비교 무의미 |
| **미들게임** | move ≥ 15, 주요기물 > 6 | 양쪽 전개 완료, 포지셔널 판단 시작 |
| **엔드게임** | move ≥ 15, 주요기물 ≤ 6 | Q·R·B·N 합계 |

---

## 설치 및 실행

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. Stockfish 설치

[https://stockfishchess.org/download/](https://stockfishchess.org/download/) 에서 다운로드 후  
`stockfish/` 디렉토리에 바이너리를 배치하세요.

### 3. 실행

**딥블루 기보 비교 (전체):**
```bash
python main.py compare
python main.py compare --depth 5 --verbose --output results.csv
```

**단일 FEN 분석:**
```bash
python main.py analyze --fen "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
```

**인터랙티브 모드:**
```bash
python main.py play
```

### CLI 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--depth N` | 4 | 탐색 깊이 (플라이) |
| `--time SEC` | 5.0 | 수당 시간 제한 (초) |
| `--stockfish PATH` | 자동 탐지 | Stockfish 바이너리 경로 |
| `--verbose` | False | 포지션별 상세 출력 |
| `--output FILE` | None | CSV 결과 저장 |

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

딥블루가 채택한 핵심 기법과의 대응:

| 딥블루 | Deeper-Blue |
|--------|-------------|
| Minimax + Alpha-Beta | Negamax + Alpha-Beta (fail-soft) |
| Iterative Deepening | + Aspiration Windows |
| Principal Variation Search | PVS — null window after first move |
| Check Extension | 체크 상황에서 depth+1 확장 (전술 놓침 방지) |
| Quiescence Search | + Delta Pruning |
| Transposition Table | Zobrist Hashing (polyglot) |
| Move Ordering | MVV-LVA + Killer + History + Check bonus |
| Null Move Pruning | 적응형 R (depth≥6 → R=3, else R=2) |
| Late Move Reduction | log 기반 공식: √(depth-1)×√moves |
| Futility Pruning | depth 1~2 |
| Evaluation Function | Material + PST + Pawn + Bishop pair + Rook bonuses + King safety + Mobility |
| Opening Book | 미사용 (move 15 이후만 비교) |
| Endgame Tablebase | 향후 추가 가능 |

---

## 평가 함수 상세 (evaluation.py)

| 컴포넌트 | 설명 |
|----------|------|
| **기물 가중치** | P=100, N=320, B=330, R=500, Q=900 cp |
| **Piece-Square Table** | 기물 종류별 위치 보너스 (Middlegame/Endgame 테이퍼드 적용) |
| **게임 페이즈** | 남은 주요 기물 수로 0.0(미들)~1.0(엔드) 계산 |
| **폰 구조** | 이중폰(-20), 고립폰(-30), **백워드폰(-20)**, 패스트폰(+10~+120) |
| **비숍 쌍** | 양색 비숍 보유 시 +50cp (오픈 포지션에서 강력) |
| **룩 오픈 파일** | 오픈 파일 +25cp, 세미오픈 파일 +12cp |
| **룩 7랭크** | 7랭크(흑은 2랭크) 진출 시 +25cp |
| **킹 안전** | 미들게임: 폰 방패·오픈 파일 페널티 / 엔드게임: 중앙 접근 보너스 |
| **모빌리티** | 공격 가능 칸 수 × 2cp |

---

## 향후 계획

- [ ] Stockfish / 다른 오픈소스 엔진과 직접 대결
- [ ] Endgame Tablebase 연동
- [ ] SEE (Static Exchange Evaluation) 기반 캡처 필터링
- [ ] 웹 UI에서 FEN 입력 및 시각적 결과 확인
