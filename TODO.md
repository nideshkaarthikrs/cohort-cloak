# CohortCloak: remaining TODOs

Status: all 7 phases done, `check_submission.py --repo . --run` prints READY TO SUBMIT. Items below are what is left.

## Testing (do first)
- [x] **Network-off run (done 2026-11-26, via macOS `sandbox-exec` with `deny network*`: exit 0, CONTRACT OK, output byte-identical to the networked run).** Switch Wi-Fi off and run `RAKSHA_SECRET=practice python main.py --input ../Secret-Wards-ToolKit/dev/input --output out`. The code makes no network calls, but this is the real proof.
- [x] **Fresh-machine run (done 2026-11-26: clean clone of GitHub, fresh uv venv, `pip install -r requirements.txt`, output byte-identical, READY TO SUBMIT; Linux / 2-CPU still untested).** Clone the pushed repo into an empty folder, `pip install -r requirements.txt`, run `python main.py` with 2 CPUs. Nothing may depend on `.venv`, the sibling kit folder or untracked files. Repeat on Linux / Python 3.10 if available (3.10.20 already verified in a separate venv).
- [ ] **Held-out layout test.** A teammate writes a few new document layouts without looking at our detectors; run once, record leak numbers. Every test set so far is ours, so this is the most valuable check left.
- [ ] **Resource-limit run.** 2 CPUs (`taskset` or Docker) and a 4 GB memory cap on the dev data repeated 10x (about 430 MB peak, 23 s earlier) to confirm it stays safe.
- [~] **Manual review (started: notes, discharge, misc look right; FHIR, Hindi prescriptions still to skim).** Skim 10-20 output files per folder, especially Hindi/Hinglish text, FHIR bundles and discharge files, for over-redaction or leftovers the metrics cannot see.

## Quality improvements (if time allows)
- [ ] Spill the event table to disk (it is what grows memory on large inputs).
- [ ] Shift dates inside encoded payloads (base64, percent, `\u` escapes); not shifted today.
- [ ] Generalise procedures and package codes to categories.
- [ ] Fix the one remaining split patient in linking (two Hindi prescriptions the linker refuses to merge).
- [ ] Revisit the A5 trade-off (48% of raw vs medical kept 94.7%) if the organisers publish more about the attacker. Alternative: fixed rare-diagnosis threshold 8 gives A5 17% but medical 88.9%.

## Submission housekeeping
- [x] GitHub repo is public (unauthenticated HTTP 200, clone works).
- [x] Confirm the kit folder and the hackathon `.docx` are not tracked, and `docs/brief.pdf` is on `main`.
- [ ] Open `docs/brief.pdf` in a second viewer (font substitution, still 2 pages).
- [ ] Submit the repo link + `docs/brief.pdf` before the deadline.

## Notes
- Brief source: `brief/brief.html`. Regenerate the PDF with
  `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu --no-pdf-header-footer --print-to-pdf=docs/brief.pdf "file://$PWD/brief/brief.html"`
  and check it is still 2 pages.
- Full gate run: `bash tools/check_all.sh`. Stress / unseen-layout generators: `tools/make_stress.py`, `tools/make_stress2.py`.
