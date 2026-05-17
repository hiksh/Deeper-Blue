# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## 프로젝트 현황 (2025-05-17 기준)

### 벤치마크 결과

| 버전 | 조건 | 승 | 패 | 무 | 승률 | 평균 델타 |
|------|------|----|----|-----|------|----------|
| v1 (초기) | depth=4, 22포지션 | 5 | 11 | 6 | 22.7% | — |
| v2 (개선) | depth=4, 22포지션 | 6 | 11 | 5 | 27.3% | +17.7 cp |
| **v3 (튜닝 후 목표)** | depth=4, 22포지션 | ? | ? | ? | **>35%?** | — |

비교 조건: move ≥ 15, middlegame, Stockfish 18 평가, 수당 3초

---

### 구현 완료 목록

| 기능 | 파일 | 상태 |
|------|------|------|
| Texel Tuning 데이터 수집 | `tuning/data_loader.py` | ✅ |
| Texel Tuning (scipy L-BFGS-B) | `tuning/texel_tuner.py` | ✅ |
| EvalParams (26 스칼라 + 8 PST) | `engine/evaluation.py` | ✅ |
| 통계 검증 (t-test / p-value / 95% CI) | `analysis/comparator.py` | ✅ |
| Syzygy 테이블베이스 연동 | `engine/minimax.py` | ✅ |
| 웹 UI 평가 점수 바 | `web/app.py`, `web/templates/index.html` | ✅ |
| 착수 히트맵 시각화 | `analysis/visualizer.py` | ✅ |
| CLI: `download-positions`, `tune` | `main.py` | ✅ |

---

### 튜닝 실행 방법

```bash
# 백그라운드 실행 (예상 ~22시간, 48코어 기준)
nohup ./run_tuning.sh > logs/tuning_$(date +%Y%m%d_%H%M%S).log 2>&1 &
tail -f logs/tuning_*.log

# 빠른 실행 (스칼라만, ~10시간)
SKIP_PST=1 nohup ./run_tuning.sh > logs/tune_scalar.log 2>&1 &
```

**출력 파일:**
- `data/positions_1M.json.gz` — 학습 포지션 (1M개)
- `data/tuned_scalars.json` — 스칼라 튜닝 결과 (26 params)
- `data/tuned_full.json` — PST 포함 튜닝 결과 (538 params)

---

### 튜닝 완료 후 분석 체크리스트

튜닝 완료 후 아래 순서로 결과를 분석한다.

#### 1. 파라미터 변화 확인

```python
from tuning.texel_tuner import load_params, print_diff
print_diff(load_params("data/tuned_scalars.json"))          # 기본값 대비 변화
print_diff(load_params("data/tuned_full.json"),
           load_params("data/tuned_scalars.json"))           # 스칼라 → PST 변화
```

주목할 포인트:
- `pawn` 값이 100에서 얼마나 변했는가 (체스 엔진은 보통 90-105)
- `isolated_pawn`, `doubled_pawn` 패널티 크기
- `passed_r5`, `passed_r6` — 패스트 폰 보너스 (가장 중요한 엔드게임 요소)
- `mobility_sq` — 2cp에서 올라갔는지 (모빌리티 과소평가 여부)

#### 2. 딥블루 기보 비교 (v2 vs v3)

```bash
# 튜닝 전 기준선 (이미 results_v2.csv 있으면 스킵)
python main.py compare --depth 4 --time 3.0 --output data/results_v2.csv --verbose

# 튜닝 후 — evaluate_with_params를 쓰도록 엔진 연결 필요 (아래 참고)
python main.py compare --depth 4 --time 3.0 --output data/results_v3.csv --verbose
```

결과 비교 포인트:
- 승률: 27.3% → ?% (목표: +5%p 이상)
- 평균 델타: +17.7 cp → ?cp
- **t-test p-value**: < 0.05이면 통계적으로 유의미한 개선
- 95% CI가 0 이상이면 "우리 엔진이 딥블루보다 낫다"고 주장 가능

#### 3. 엔진 대전 결과 분석

```bash
# ELO 2200 (1990년대 수준) 상대 20게임
python main.py match \
    --opponent stockfish/stockfish \
    --elo 2200 --games 20 \
    --output data/match_v3_elo2200.csv

# ELO 2600 (1997 딥블루 추정 수준) 상대 20게임
python main.py match \
    --opponent stockfish/stockfish \
    --elo 2600 --games 20 \
    --output data/match_v3_elo2600.csv
```

#### 4. 시각화 생성

```bash
# 딥블루 비교 차트 (히트맵 포함)
python main.py visualize --csv data/results_v3.csv --charts output/v3/

# 생성 파일:
#   output/v3/win_rate_by_game.png    — 게임별 승률
#   output/v3/delta_distribution.png  — 델타 분포
#   output/v3/score_timeline.png      — 게임 진행에 따른 델타
#   output/v3/phase_breakdown.png     — 미들/엔드게임 비율
#   output/v3/move_heatmap.png        — 착수 목적지 히트맵
```

#### 5. 튜닝된 파라미터를 엔진에 적용하는 법

현재 `compare` / `match` 명령은 기본 `evaluate()`를 사용한다.
튜닝된 파라미터로 검증하려면 `engine/evaluation.py`의 `_DEFAULT_PARAMS`를 교체하거나
`SearchEngine` 래퍼에서 `evaluate_with_params`를 호출하도록 수정해야 한다.

```python
# 빠른 검증 (단일 FEN)
from tuning.texel_tuner import load_params
from engine.evaluation import evaluate_with_params
import chess

params = load_params("data/tuned_full.json")
board  = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4")

default_score = evaluate_with_params(board, None)   # 기본값 (None이면 기본 eval 사용)
tuned_score   = evaluate_with_params(board, params)
print(f"기본: {default_score:+d} cp  →  튜닝 후: {tuned_score:+d} cp")
```

---

### 핵심 파라미터 설명 (분석 시 참고)

| 파라미터 | 기본값 | 의미 | 변화 방향 예측 |
|----------|--------|------|---------------|
| `pawn` | 100 | 폰 가치 | 거의 안 변함 (기준값) |
| `knight` | 320 | 나이트 가치 | 클로즈드 포지션 많으면 ↑ |
| `bishop` | 330 | 비숍 가치 | 오픈 포지션 많으면 ↑ |
| `isolated_pawn` | 30 | 고립 폰 패널티 | 보통 ↑ (과소평가 경향) |
| `passed_r5` | 80 | 5랭크 패스트 폰 | 보통 ↑ |
| `passed_r6` | 120 | 6랭크 패스트 폰 | 보통 ↑↑ (엔딩에서 결정적) |
| `mobility_sq` | 2 | 기물 이동 가능 칸당 보너스 | 보통 ↑ |
| `king_open_file` | 15 | 킹 주변 오픈 파일 패널티 | 보통 ↑ |