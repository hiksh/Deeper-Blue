#!/usr/bin/env bash
# =============================================================================
# run_tuning.sh — Deeper-Blue Texel Tuning (overnight / multi-day run)
#
# 예상 소요 시간 (48코어 A100 서버 기준):
#   Phase 0  데이터 수집  :  15~30 분   (1M 포지션, Lichess 스트리밍)
#   Phase 1  스칼라 튜닝  :  ~9 시간    (26 파라미터, 1M 포지션, 300 iter)
#   Phase 2  PST 튜닝     :  ~12 시간   (538 파라미터, 200K 포지션, 100 iter)
#   ─────────────────────────────────────────────────────────────────────────
#   합계                  :  ~22 시간   (금요일 밤 → 일요일 오전)
#
# 사용법:
#   chmod +x run_tuning.sh
#
#   # 백그라운드 실행 + 로그 저장
#   nohup ./run_tuning.sh > logs/tuning_$(date +%Y%m%d_%H%M%S).log 2>&1 &
#
#   # 진행 상황 확인
#   tail -f logs/tuning_*.log
#
# 환경 변수로 설정 재정의 가능:
#   WORKERS=96 YEAR=2023 MONTH=6 SKIP_PST=1 ./run_tuning.sh
#
# 스칼라만 빠르게 (~10시간):
#   SKIP_PST=1 ./run_tuning.sh
# =============================================================================

set -euo pipefail

# ── 설정 ─────────────────────────────────────────────────────────────────────
WORKERS="${WORKERS:-48}"           # 사용할 CPU 코어 수
YEAR="${YEAR:-2024}"               # Lichess 데이터 연도
MONTH="${MONTH:-1}"                # Lichess 데이터 월
SKIP_PST="${SKIP_PST:-0}"          # 1이면 PST 튜닝 건너뜀

POS_1M="data/positions_1M.json.gz"
POS_200K="data/positions_200K.json.gz"
PARAMS_SCALAR="data/tuned_scalars.json"
PARAMS_FULL="data/tuned_full.json"

mkdir -p logs data/

# ── 유틸 ─────────────────────────────────────────────────────────────────────
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

elapsed_min() {
    echo $(( ($1) / 60 ))
}

# ── 시작 ─────────────────────────────────────────────────────────────────────
TOTAL_START=$(date +%s)
log "======================================================"
log "  Deeper-Blue Texel Tuning"
log "  Workers : ${WORKERS}"
log "  Data    : Lichess ${YEAR}-$(printf '%02d' ${MONTH})"
log "  PST     : $([ "${SKIP_PST}" = "1" ] && echo 'Skip' || echo 'Yes')"
log "======================================================"

# ── Phase 0: 포지션 데이터 수집 ───────────────────────────────────────────────
log ""
log "[ Phase 0 ] 포지션 수집 (1M, ELO ≥ 2200)"

if [ -f "${POS_1M}" ]; then
    log "  이미 존재 → 스킵: ${POS_1M}"
else
    T0=$(date +%s)
    python main.py download-positions \
        --year  "${YEAR}" \
        --month "${MONTH}" \
        --n     1000000 \
        --min-elo 2200 \
        --output "${POS_1M}"
    log "  완료 ($(elapsed_min $(($(date +%s) - T0))) 분) → ${POS_1M}"
fi

# ── Phase 1: 스칼라 튜닝 (26 파라미터, 1M 포지션) ────────────────────────────
log ""
log "[ Phase 1 ] 스칼라 튜닝 — 26 params, 1M pos, 300 iter"
log "  예상 소요: ~9 시간"

T1=$(date +%s)
python main.py tune \
    --positions "${POS_1M}" \
    --output    "${PARAMS_SCALAR}" \
    --workers   "${WORKERS}" \
    --iter      300
T1_END=$(date +%s)
log "  완료 ($(elapsed_min $((T1_END - T1))) 분) → ${PARAMS_SCALAR}"

# 파라미터 변화 출력 (파이썬 인라인)
python - <<'PYEOF'
from tuning.texel_tuner import load_params, print_diff
print_diff(load_params("data/tuned_scalars.json"))
PYEOF

# ── Phase 2: PST 튜닝 (선택) ─────────────────────────────────────────────────
if [ "${SKIP_PST}" = "1" ]; then
    log ""
    log "[ Phase 2 ] PST 튜닝 건너뜀 (SKIP_PST=1)"
    PARAMS_FINAL="${PARAMS_SCALAR}"
else
    log ""
    log "[ Phase 2 ] PST 튜닝 — 538 params, 200K pos, 100 iter"
    log "  예상 소요: ~12 시간"
    log "  스칼라 튜닝 결과를 초기값으로 사용: ${PARAMS_SCALAR}"

    T2=$(date +%s)
    python main.py tune \
        --positions    "${POS_1M}" \
        --max-positions 200000 \
        --params       "${PARAMS_SCALAR}" \
        --output       "${PARAMS_FULL}" \
        --pst \
        --workers      "${WORKERS}" \
        --iter         100
    T2_END=$(date +%s)
    log "  완료 ($(elapsed_min $((T2_END - T2))) 분) → ${PARAMS_FULL}"

    python - <<'PYEOF'
from tuning.texel_tuner import load_params, print_diff
print_diff(load_params("data/tuned_full.json"),
           load_params("data/tuned_scalars.json"))
PYEOF
    PARAMS_FINAL="${PARAMS_FULL}"
fi

# ── 완료 ─────────────────────────────────────────────────────────────────────
TOTAL_END=$(date +%s)
log ""
log "======================================================"
log "  튜닝 완료"
log "  총 소요시간 : $(elapsed_min $((TOTAL_END - TOTAL_START))) 분"
log "  최종 파라미터: ${PARAMS_FINAL}"
log "======================================================"
log ""
log "  사용 방법:"
log "    from tuning.texel_tuner import load_params"
log "    from engine.evaluation  import evaluate_with_params"
log "    params = load_params('${PARAMS_FINAL}')"
log "    score  = evaluate_with_params(board, params)"
log ""
log "  엔진 대전 테스트 (ELO 2200 Stockfish 10게임):"
log "    python main.py match --opponent stockfish/stockfish \\"
log "      --elo 2200 --games 10 --output data/match_after_tuning.csv"
