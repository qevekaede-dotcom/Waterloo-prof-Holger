#!/bin/bash
# Snapshot campaign forensics into slurm_logs/evidence_<UTC>/ BEFORE they can
# be destroyed: rerunning a displacement overwrites its scf.out/scf.err/CRASH
# in place, so run this before any resubmission of failed indices. It also
# runs automatically at the start of stage2. Needs no credentials; safe to
# run repeatedly (every run makes a fresh timestamped snapshot); snapshots
# reach git when scripts/fetch_home.sh pulls the campaign home.
#
# Usage (from anywhere): bash scripts/slurm/collect_evidence.sh [jobid ...]
#   Passing SLURM job ids additionally records their sacct accounting.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
DEST="slurm_logs/evidence_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$DEST"

healthy () {
    grep -q "JOB DONE" "$1" 2>/dev/null \
      && grep -q "convergence has been achieved" "$1" \
      && grep -q "Forces acting on atoms" "$1"
}

for j in "$@"; do
    sacct -j "$j" --format=JobID%20,State,ExitCode,Elapsed,NodeList%24 \
        > "$DEST/sacct_$j.txt" 2>&1 || true
done

n=0
for d in fc_calcs/disp-*/; do
    if ! healthy "${d}scf.out"; then
        id=$(basename "$d")
        mkdir -p "$DEST/$id"
        for f in scf.err CRASH scf.out scf.in timing.csv; do
            [ -f "$d$f" ] && cp "$d$f" "$DEST/$id/"
        done
        n=$((n+1))
    fi
done

for f in campaign_log.csv campaign_log_slurm.csv FAILED.list \
         checks/DECISIONS.txt checks/k222_report.txt \
         checks/lowcut_report.txt checks/pristine_report.txt; do
    [ -f "$f" ] && cp "$f" "$DEST/"
done
find slurm_logs -maxdepth 1 -name 'stage*.out' -exec cp {} "$DEST/" \; 2>/dev/null
echo "[collect_evidence] $n unhealthy displacement(s); snapshot in $DEST"
