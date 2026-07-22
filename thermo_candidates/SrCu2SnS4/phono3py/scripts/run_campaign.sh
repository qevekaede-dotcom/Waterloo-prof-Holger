#!/bin/bash
# Autonomous phono3py force-calculation campaign for SrCu2SnS4.
#
# Stages (all idempotent; rerunning this script resumes where it stopped):
#   0. Force-convergence checks on disp-00001 against the 90/720 Ry, 3x3x3
#      benchmark: (a) k-mesh 2x2x2, (b) cutoffs 60/480 Ry at the decided
#      k-mesh. A candidate is accepted if max |dF| <= KTHRESH. Decisions are
#      recorded in checks/DECISIONS.txt and applied to all campaign inputs.
#   1. Run every fc_calcs/disp-*/scf.in through pw.x with health checks,
#      one retry per failure (nk=1), per-run timing in campaign_log.csv.
#   2. Collect forces + compute kappa_L via scripts/postprocess.py.
#
# Usage:  nohup caffeinate -i bash scripts/run_campaign.sh >> campaign.out 2>&1 &
# Requires: thermo-bt2 env (sourced below). QE_NP/QE_NK overridable.

set -u
source "$HOME/scientific-tools/env/thermo-bt2.sh"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
QE_NP="${QE_NP:-12}"
QE_NK="${QE_NK:-2}"
PW="$(which pw.x)"
LOG="$ROOT/campaign_log.csv"
FAILED="$ROOT/FAILED.list"
KTHRESH="5.0e-5"   # Ry/bohr, max force-component difference allowed
DECISIONS="$ROOT/checks/DECISIONS.txt"

[ -f "$LOG" ] || echo "run_id,wall_seconds,kmesh,ecut,nk,status" > "$LOG"

healthy () { # $1=scf.out
    grep -q "JOB DONE" "$1" 2>/dev/null \
      && grep -q "convergence has been achieved" "$1" \
      && grep -q "Forces acting on atoms" "$1"
}

run_pw () {  # $1=dir  $2=nk   -> 0 on healthy completion
    local d="$1" nk="$2"
    ( cd "$d" && rm -rf tmp \
      && mpirun -np "$QE_NP" "$PW" -nk "$nk" -in scf.in > scf.out 2> scf.err )
    rm -rf "$d/tmp"
    healthy "$d/scf.out"
}

verdict () { # $1=report file -> echoes PASS or FAIL
    grep '^RESULT=' "$1" | cut -d= -f2
}

# ---------- Stage 0: force-convergence checks ----------
BENCH="$ROOT/fc_calcs/disp-00001"
if [ ! -f "$DECISIONS" ]; then
    echo "[stage0 $(date '+%F %T')] force-convergence checks"
    mkdir -p "$ROOT/checks/k222" "$ROOT/checks/lowcut"
    healthy "$BENCH/scf.out" || { echo "[stage0] ERROR: benchmark disp-00001 (90/720, 3x3x3) missing or unhealthy"; exit 1; }

    # (a) k-mesh check: 2x2x2 at 90/720
    if ! healthy "$ROOT/checks/k222/scf.out"; then
        sed 's/^  3 3 3 0 0 0/  2 2 2 0 0 0/' "$BENCH/scf.in" > "$ROOT/checks/k222/scf.in"
        SECONDS=0
        run_pw "$ROOT/checks/k222" "$QE_NK" || { echo "[stage0] k222 run failed"; exit 1; }
        echo "check_k222,$SECONDS,2 2 2,90/720,$QE_NK,ok" >> "$LOG"
    fi
    python "$ROOT/scripts/compare_forces.py" "$BENCH/scf.out" \
        "$ROOT/checks/k222/scf.out" "$KTHRESH" > "$ROOT/checks/k222_report.txt" \
        || { echo "[stage0] k comparison failed"; exit 1; }
    if [ "$(verdict "$ROOT/checks/k222_report.txt")" = "PASS" ]; then
        KMESH="2 2 2"; KREF="$ROOT/checks/k222/scf.out"
    else
        KMESH="3 3 3"; KREF="$BENCH/scf.out"
    fi
    echo "[stage0] k-mesh decision: $KMESH"

    # (b) cutoff check: 60/480 at the decided k-mesh (reference = 90/720 at
    #     the same k-mesh, which already exists from step (a))
    if ! healthy "$ROOT/checks/lowcut/scf.out"; then
        sed -e 's/ecutwfc = 90/ecutwfc = 60/' -e 's/ecutrho = 720/ecutrho = 480/' \
            "$(dirname "$KREF")/scf.in" > "$ROOT/checks/lowcut/scf.in"
        SECONDS=0
        run_pw "$ROOT/checks/lowcut" "$QE_NK" || { echo "[stage0] lowcut run failed"; exit 1; }
        echo "check_lowcut,$SECONDS,$KMESH,60/480,$QE_NK,ok" >> "$LOG"
    fi
    python "$ROOT/scripts/compare_forces.py" "$KREF" \
        "$ROOT/checks/lowcut/scf.out" "$KTHRESH" > "$ROOT/checks/lowcut_report.txt" \
        || { echo "[stage0] cutoff comparison failed"; exit 1; }
    if [ "$(verdict "$ROOT/checks/lowcut_report.txt")" = "PASS" ]; then
        ECUTWFC=60; ECUTRHO=480
    else
        ECUTWFC=90; ECUTRHO=720
    fi
    echo "[stage0] cutoff decision: $ECUTWFC/$ECUTRHO Ry"

    {
        echo "# Force-convergence decisions for the campaign (threshold $KTHRESH Ry/bohr)"
        echo "# Reports: checks/k222_report.txt, checks/lowcut_report.txt"
        echo "KMESH=$KMESH"
        echo "ECUTWFC=$ECUTWFC"
        echo "ECUTRHO=$ECUTRHO"
    } > "$DECISIONS"
fi
KMESH=$(grep '^KMESH=' "$DECISIONS" | cut -d= -f2)
ECUTWFC=$(grep '^ECUTWFC=' "$DECISIONS" | cut -d= -f2)
ECUTRHO=$(grep '^ECUTRHO=' "$DECISIONS" | cut -d= -f2)
echo "[stage0] campaign settings: k = $KMESH, cutoffs = $ECUTWFC/$ECUTRHO Ry"

# Campaign inputs at the decided settings. disp-00001 already has a healthy
# output at settings at least as strict (it IS the reference), so it is
# regenerated only if it has no healthy output.
if healthy "$BENCH/scf.out"; then
    python "$ROOT/scripts/prepare_inputs.py" --kmesh $KMESH \
        --ecutwfc "$ECUTWFC" --ecutrho "$ECUTRHO"
else
    python "$ROOT/scripts/prepare_inputs.py" --kmesh $KMESH \
        --ecutwfc "$ECUTWFC" --ecutrho "$ECUTRHO" --force --only 00001
    python "$ROOT/scripts/prepare_inputs.py" --kmesh $KMESH \
        --ecutwfc "$ECUTWFC" --ecutrho "$ECUTRHO"
fi

# ---------- Stage 0.5: pristine-supercell residual forces (non-gating) ----------
if ! healthy "$ROOT/checks/pristine/scf.out"; then
    echo "[stage0.5 $(date '+%F %T')] pristine supercell residual-force check"
    python "$ROOT/scripts/prepare_inputs.py" --pristine --kmesh $KMESH \
        --ecutwfc "$ECUTWFC" --ecutrho "$ECUTRHO"
    SECONDS=0
    if run_pw "$ROOT/checks/pristine" "$QE_NK"; then
        echo "check_pristine,$SECONDS,$KMESH,$ECUTWFC/$ECUTRHO,$QE_NK,ok" >> "$LOG"
    else
        echo "[stage0.5] WARNING: pristine run failed; campaign continues"
    fi
fi
if healthy "$ROOT/checks/pristine/scf.out"; then
    maxres=$(awk '/Forces acting on atoms/,/Total force/ {
        if ($0 ~ /force =/) for (i=NF-2; i<=NF; i++) {v=($i<0?-$i:$i); if (v>m) m=v}
    } END {printf "%.3e", m}' "$ROOT/checks/pristine/scf.out")
    echo "[stage0.5] max residual force on undisplaced supercell: $maxres Ry/bohr" \
        | tee "$ROOT/checks/pristine_report.txt"
    awk -v m="$maxres" 'BEGIN { if (m+0 > 1e-4) print "[stage0.5] WARNING: residual forces exceed 1e-4 Ry/bohr — relaxation may be too loose for phonons; flag in the writeup" }'
fi

# ---------- Stage 1: force campaign ----------
echo "[stage1 $(date '+%F %T')] force campaign starting"
: > "$FAILED.tmp"
total=$(ls -d "$ROOT"/fc_calcs/disp-*/ | wc -l | tr -d ' ')
done_n=0
for d in "$ROOT"/fc_calcs/disp-*/; do
    id=$(basename "$d" | sed 's/disp-//')
    if healthy "$d/scf.out"; then
        done_n=$((done_n+1)); continue
    fi
    echo "[stage1 $(date '+%F %T')] running disp-$id ($done_n/$total done)"
    SECONDS=0
    if run_pw "$d" "$QE_NK"; then
        echo "$id,$SECONDS,$KMESH,$ECUTWFC/$ECUTRHO,$QE_NK,ok" >> "$LOG"
        done_n=$((done_n+1))
    else
        echo "[stage1] disp-$id failed, retrying with nk=1"
        SECONDS=0
        if run_pw "$d" 1; then
            echo "$id,$SECONDS,$KMESH,$ECUTWFC/$ECUTRHO,1,ok_retry" >> "$LOG"
            done_n=$((done_n+1))
        else
            echo "$id,$SECONDS,$KMESH,$ECUTWFC/$ECUTRHO,1,FAILED" >> "$LOG"
            echo "$id" >> "$FAILED.tmp"
            echo "[stage1] disp-$id FAILED twice; continuing"
        fi
    fi
done
mv "$FAILED.tmp" "$FAILED"
nfail=$(wc -l < "$FAILED" | tr -d ' ')
echo "[stage1 $(date '+%F %T')] campaign finished: $done_n/$total ok, $nfail failed"
if [ "$nfail" -gt 0 ]; then
    echo "[stage1] failed IDs in FAILED.list — fix before stage 2"; exit 2
fi

# ---------- Stage 2: collect forces, build FCs, kappa ----------
echo "[stage2 $(date '+%F %T')] force collection + kappa"
python "$ROOT/scripts/postprocess.py" || exit 3
echo "[all done $(date '+%F %T')]"
