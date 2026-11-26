#!/usr/bin/env bash
# Full gate: pipeline, contract, dev checks, canaries, determinism, secret grep, pytest.
set -u
cd "$(dirname "$0")/.."
KIT=${KIT:-../Secret-Wards-ToolKit}
PY=${PY:-python}
[ -x .venv/bin/python ] && PY=.venv/bin/python
TRUTH=$KIT/dev/truth/truth.json
SECRET=practice
FAIL=0
step() { echo; echo "=== $1"; }
rm -rf out_a out_b out_c out_d .tmp_scan
mkdir -p .tmp_scan/tmp .tmp_scan/home

step "pipeline (secret=practice), timing + peak RSS"
START=$(date +%s)
TMPDIR=$PWD/.tmp_scan/tmp HOME=$PWD/.tmp_scan/home RAKSHA_SECRET=$SECRET /usr/bin/time -l $PY main.py --input $KIT/dev/input --output out_a > .tmp_scan/stdout.txt 2> .tmp_scan/stderr.txt || { echo "PIPELINE FAILED"; FAIL=1; }
echo "wall $(( $(date +%s) - START )) s"; cat .tmp_scan/stdout.txt
grep -E "maximum resident" .tmp_scan/stderr.txt | awk '{printf "peak RSS %.0f MB\n", $1/1048576}'

step "validate_output"
python3 $KIT/validate_output.py --input $KIT/dev/input --output out_a | tee .tmp_scan/val.txt | tail -5
grep -q "CONTRACT OK" .tmp_scan/val.txt || FAIL=1

step "check_dev"
python3 $KIT/check_dev.py --output out_a

step "eval_dev"
$PY tools/eval_dev.py --output out_a --truth $TRUTH

step "linking diagnostics (precision/recall, wrong merges, traps)"
$PY tools/link_diag.py --output out_a --truth $TRUTH --show 3 | cut -c1-300

step "privacy layer: temporal, bands, generalisation (tools/eval_privacy.py)"
$PY tools/eval_privacy.py --output out_a --truth $TRUTH | grep -v "^METRICS"

step "attack simulation A1/A3/A4/A5 vs raw (tools/attack_sim.py)"
$PY tools/attack_sim.py --kit $KIT --release out_a --raw-cache .tmp_scan/raw_attack.json | grep -v "^ATTACK"

step "pseudonym consistency (every claimed PSN appears in its exported file)"
$PY tools/psn_check.py --output out_a || FAIL=1

step "clean-document token retention"
$PY tools/clean_check.py --output out_a --truth $TRUTH || FAIL=1

step "canary scan (output, logs, stdout/stderr, TMPDIR, HOME)"
$PY tools/canary_scan.py --output out_a --truth $TRUTH --extra .tmp_scan/stdout.txt .tmp_scan/stderr.txt .tmp_scan/tmp .tmp_scan/home || FAIL=1
echo "leftover files in TMPDIR/HOME: $(find .tmp_scan/tmp .tmp_scan/home -type f | wc -l | tr -d ' ')"

step "generalisation proxy: run without learning names from structured fields"
RAKSHA_SECRET=$SECRET $PY main.py --input $KIT/dev/input --output out_d --ablate-names > /dev/null
python3 $KIT/check_dev.py --output out_d | sed -n "/PERSONAL DATA/p;/by language/p;/by hiding/p;/MEDICAL/p"

step "determinism (same secret, second run)"
RAKSHA_SECRET=$SECRET $PY main.py --input $KIT/dev/input --output out_b > /dev/null
if diff -r out_a/sanitized out_b/sanitized > /dev/null && cmp -s out_a/records.jsonl out_b/records.jsonl; then echo "IDENTICAL"; else echo "DIFFERS"; FAIL=1; fi

step "different secret must change pseudonyms"
RAKSHA_SECRET=another-secret $PY main.py --input $KIT/dev/input --output out_c > /dev/null
if cmp -s out_a/records.jsonl out_c/records.jsonl && diff -rq out_a/sanitized out_c/sanitized > /dev/null; then
  if grep -q '"patient": "PSN' out_a/records.jsonl; then echo "SAME (BAD)"; FAIL=1; else echo "same: no pseudonyms are emitted yet (expected before Phase 4)"; fi
else echo "DIFFERS (good)"; fi

step "secret grep (output, logs, stdout, stderr)"
if grep -rqF -e "$SECRET" -e another-secret out_a out_b out_c .tmp_scan/stdout.txt .tmp_scan/stderr.txt --exclude-dir=sanitized 2>/dev/null; then echo "SECRET FOUND"; FAIL=1; else echo "clean"; fi

step "pytest"
$PY -m pytest -q || FAIL=1

echo; [ $FAIL -eq 0 ] && echo "CHECK_ALL: PASS" || echo "CHECK_ALL: FAIL"
rm -rf .tmp_scan
exit $FAIL
