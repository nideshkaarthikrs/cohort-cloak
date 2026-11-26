# CLAUDE.md: CohortCloak (Secret Wards, Track 3)

This repo is our submission for Yugaantar DevForge Track 3, "Secret Wards". It is an offline, CPU-only, LLM-free privacy firewall for synthetic Indian hospital records.
**Read `PLAN.md` before doing anything.** It holds the findings, architecture, design decisions, phases, gates, status board and running log.

## Hard rules (non-negotiable)
- **No LLMs**, no generative models, no pretrained transformers >50M params. Rules, gazetteers and classical ML only. Declare every model in the README (currently: none).
- **Offline at run time:** no network calls in `python main.py ...`. Limits are 2 CPUs, 4 GB RAM and 15 min. Target ≤60 s and ≤512 MB on dev.
- **Deterministic:** same input + same `RAKSHA_SECRET` → byte-identical `sanitized/` and `records.jsonl`. A different secret → different pseudonyms and date shifts. Sort every set/dict iteration that affects output. No time, random or PID in outputs (report.json timing is the only exception).
- **Never write `RAKSHA_SECRET` anywhere**: not to files, logs, stdout/stderr or exception text.
- **Fail safe:** never copy a file we could not process. Quarantine it with a snake_case reason in report.json. Never skip a file silently. Never modify the input directory.
- **No hardcoding:** no dev names, IDs, file names or exact formats in code or lexicons. Gazetteers come only from Faker (en_IN, hi_IN) and hand-written generic lists, **never from dev data**. Dev data is for evaluation only.
- **Original work:** written during the hackathon. The kit's `starter/` is reference only. Detection, linking and privacy are ours.
- **PII-free side channels:** stdout, stderr, `logs/`, report.json, records.jsonl, output file names, TMPDIR and HOME are scanned for PII and canaries. Log only enums and integers. Never `str(exc)` from file processing; record the exception class name only.
- The ZKP sentence in the track overview is an organiser typo. Ignore it.
- **Dependencies:** runtime is rapidfuzz, jellyfish, indic-transliteration, phonenumbers, cryptography, PyYAML; dev is Faker, pytest. **Ask the user before adding anything else.**
- Code must run on **Python 3.10** (the evaluator's Linux version is unknown). Develop in `.venv` (uv, Python 3.11).

## Layout and paths
- Kit (never commit): `../Secret-Wards-ToolKit` (validators, `dev/input`, `dev/truth/truth.json`, `dev/attacker/`). Tools read it via `KIT=../Secret-Wards-ToolKit`.
- Package: `cloak/` (ingest, detect, link, privacy, rewrite, security, report). Entry point: `main.py`. Policy: `config/policy.yaml`. Lexicons: `data/lexicons/`.
- Outputs go to `out*/` (gitignored).

## Working protocol
1. Work **one phase at a time** in `PLAN.md` §6. Start by setting the phase to `in progress` on the Status board.
2. Write tests first for every guard and trap listed in that phase. Keep modules small and pure where possible.
3. At the end of a phase, run `bash tools/check_all.sh` (from Phase 1 onward). It runs the pipeline, `validate_output.py`, `check_dev.py`, `tools/eval_dev.py`, `tools/canary_scan.py`, the determinism diff, the different-secret check, the secret grep and `pytest`.
4. Paste the numbers into **PLAN.md §11 Running log**, with date, phase, gate pass/fail and key metrics. Update **§10 Status board**.
5. Commit as `Phase N: <summary>`, ending with the attribution trailer, then push to `origin main`.
6. **Stop and report to the user** with the numbers before starting the next phase.
- If a gate fails and the time box is overrun by >30 min, log it and ask the user whether to continue or move on.
- Fail closed for privacy, but always report the medical-preservation cost (the per-kind table from eval_dev).
- Debugging with `check_dev.py --show` in the terminal is fine (the data is synthetic). Never paste PII into repo files, tests' expected outputs from dev, or commit messages. Use invented test strings.
- Check generalisation on the stress set (Phase 6) before claiming improvements. Hidden data has unseen names, labels and formats.

## Commands
```bash
uv venv --python 3.11 .venv && . .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt
KIT=../Secret-Wards-ToolKit
RAKSHA_SECRET=practice python main.py --input $KIT/dev/input --output out
python3 $KIT/validate_output.py --input $KIT/dev/input --output out      # must print CONTRACT OK
python3 $KIT/check_dev.py --output out --show 10
bash tools/check_all.sh
python3 $KIT/check_submission.py --repo . --run                           # must print READY TO SUBMIT
```
