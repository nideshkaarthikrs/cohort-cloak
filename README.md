# CohortCloak: Secret Wards (Track 3)

**Team Moorthi Annan Gang**: Nidesh Kaarthik R S, SRISANJAY G, Prithviraj S, Sai Samanvith G.

An offline, CPU-only, LLM-free privacy firewall for synthetic Indian hospital records. It reads a mixed dump
(CSV/TSV, nested JSON, FHIR bundles, free text in English, Hindi and Hinglish), removes personal data, keeps the medical
content, links resolvable patient records with stable keyed pseudonyms, and generalises quasi-identifiers to reduce
re-identification risk. Ambiguous multi-patient batches are left unassigned rather than merged.

**Declared models: none.** No LLM, no neural network, no trained model of any kind. Detection is rules, validators,
gazetteers (Faker `en_IN`/`hi_IN` plus hand-written lists) and classical string similarity (RapidFuzz, Jellyfish).

## Setup and run

```bash
uv venv --python 3.11 .venv && . .venv/bin/activate        # runs on Python 3.10+
pip install -r requirements.txt -r requirements-dev.txt     # dev adds Faker and pytest only
RAKSHA_SECRET=practice python main.py --input ../Secret-Wards-ToolKit/dev/input --output out
python tools/audit.py --kit ../Secret-Wards-ToolKit          # verified practice measurements
python -m pytest -q                                       # regression tests
python3 ../Secret-Wards-ToolKit/check_submission.py --repo . --run
```

Runtime dependencies: rapidfuzz, jellyfish, indic-transliteration, phonenumbers, cryptography, PyYAML. No network is
used at run time. `RAKSHA_SECRET` only derives keys in memory and is never written anywhere.

## Architecture

```
input/ -> INGEST (sniff by content, decode, parse; quarantine with reason codes)
       -> pass 1 LEARN   names, IDs, ID shapes, d/m-vs-m/d votes from every channel (output discarded)
       -> pass 2 RENDER  role-based detection and rewrite; PSN / date / age / ICD / place placeholders carry payloads
       -> LINK           evidence per record -> blocking -> Fellegi-Sunter scores -> constrained clusters -> HMAC PSN
       -> PRIVACY PLAN   per-patient date shift, cluster-consistent age band, rare-diagnosis and k-anonymity decisions
       -> RESOLVE        placeholders become PSNs, shifted dates, bands, generalised codes/places -> sanitized/
       -> report.json + records.jsonl (+ logs/run.log with enums and integers only)
```

Modules: `cloak/ingest` (encoding, sniffing, record locators), `cloak/detect` (patterns, validators, guards, columns,
names, context, address, normalize, payloads, engine), `cloak/link` (translit, evidence, blocking, score, cluster,
pseudonym), `cloak/privacy` (dates, ages, suppress, plan), `cloak/rewrite` (structured, apply, filenames, keys_headers),
`cloak/security` (AES-GCM spill store, signal-safe cleanup), `cloak/report.py`. Policy lives in `config/policy.yaml`,
lexicons in `data/lexicons/` (no dev data; `tools/gen_lexicons.py` builds the name lists).

## How detection works

1. **Guards** protect clinical text first: doctors, doses, `1-0-1`, vitals, lab ranges, ICD codes, wards, hospital names,
   `K/C/O`/`H/O`/`C/O fever`, eponyms, ASHA workers.
2. **Hard identifiers** (phones incl. Devanagari digits, Aadhaar, ABHA, PAN, e-mail, insurance, label-anchored and
   shape-induced IDs) win over guards.
3. **Roles**: every CSV column and JSON key gets a role from multilingual header synonyms plus a value profile
   (values beat headers for phones, IDs, names). FHIR is read by context (patient, relative, practitioner, contained
   resources, extensions, base64 attachments, `text.div`).
4. **Names**: a run-time dictionary of every structured name (matched across spellings and scripts through phonetic
   skeletons), label/relation/honorific/Hinglish cues, WhatsApp senders, names next to phones, the gazetteer, and a
   fail-closed rule for two unknown capitalised words side by side. Detection runs on a normalised shadow string
   (homoglyphs, zero-width characters, diacritics, Indic digits) and decodes base64, percent, `\uXXXX` and HTML entities.
5. File names, headers and JSON keys are cleaned with the same dictionaries.

## Linkage

Per-record evidence (names, IDs, phones, DOB, age, gender, relative, village) feeds Fellegi-Sunter weights set by hand:
shared unique strong ID +12, full name +6, given name only +2, DOB +7 (day/month swap +5), relative +5, village +3,
birth year +-1 +2; link threshold 10. Hard cannot-links (gender, DOB, birth-year gap over 2, different Aadhaar/ABHA,
incompatible full names) and demotion of IDs shared by incompatible people (households, attendants) prevent wrong
merges. Clusters grow strongest edge first; a soft link is refused when a rival that cannot be the same person scores
within 3. Prose fragments (`Asha, W/o Kamal`) join a cluster only if exactly one cluster matches both names. The
pseudonym is `PSN-` plus 6 Crockford base32 characters of an HMAC-SHA256 keyed from `RAKSHA_SECRET`.

## Privacy layer and operating point

Dates are shifted by one nonzero keyed offset per patient. Date order is learned from the same source, then ambiguous candidates can be resolved after linking using reliable dates belonging to that patient. Generic filename words never vote across files. Yearless dates retain their style; when a reliably resolved shift crosses New Year, the shifted year is appended. A DOB cannot establish an encounter's missing year. Unknown years remain explicitly unresolved internally.

The selected local policy uses 20-year base age bands, a 75-year top code, `k_min: 3`, DOB/village redaction, PIN prefixes subject to location escalation, and cohort-scaled rare-diagnosis generalisation (5%, floor 3, cap 8). Procedures and package codes are kept. If procedure generalisation is enabled, learned procedure names are treated consistently in structured values and prose. Age anonymity cells use the actual exported bands and locations. Invalid negative ages are masked, not converted to positive ages.

A fixed 48-policy grid was evaluated on verified practice bytes. Candidates with leaks, false merges, protected-clinical losses, temporal regressions or medical retention below 4576/4855 were rejected. Selection uses a **local published-weight score estimate**, not the official evaluator: lower targeted-attack risk, higher medical retention and fewer policy changes break ties. Ground truth and attacker data are used only by audit tools, never the sanitisation pipeline.

| Practice measurement | Original commit | Local hardening |
|---|---:|---:|
| PII visible | 0/3230 | 0/3230 |
| Medical probes retained | 4576/4855 (94.3%) | 4666/4855 (96.1%) |
| Linking precision / recall | 1.000 / 1.000 | 1.000 / 1.000 |
| Originally measured stays exact | 74/78 | 78/78 |
| Own targeted attack, absolute success | 44.5% | 32.9% |
| Own targeted attack, ratio to raw | 48.3% | 35.7% |

The corrected temporal evaluator reads source encodings, accounts for DOB removal and repeated dates, and reports unresolved alignment rather than silently dropping it. It aligns 1042/1042 dated truth events; all 13959 comparable intervals and 201 admission/discharge pairs are exact. This expanded coverage is distinct from the original 78-pair comparison. Valid ages are truthful in 379/379 probes; one negative input age is reported separately. Medicines, doses, frequencies, labs, vitals, doctor names, complaints and history retain 100% of their practice probes. Remaining clinical losses are classified under ignored audit outputs, including intentional rare-diagnosis generalisation and encoded-probe evaluation artifacts.

Three synthetic validation sets were generated and frozen before policy selection. No tuning was performed against their individual answers. Against the original commit, all three retain identical medical utility and zero ID/name/canary leaks:

| Frozen seed | Medical/clean retention | ID/name/canary leaks |
|---|---:|---:|
| 31 | 96.9% | 0 |
| 73 | 100.0% | 0 |
| 107 | 98.1% | 0 |

These are synthetic validation measurements, not claims about the three hidden datasets.

## Security

PII-free side channels (logs hold enums and integers; exceptions are recorded by class name only); fail-safe
quarantine (a file that cannot be processed is never copied); the input is never modified; rendered output beyond
64 MB spills to AES-GCM files keyed by HKDF(secret, "at-rest"), removed on exit, error, SIGTERM and SIGINT; keys never
leave memory; pseudonyms and date shifts change with the secret and are not reversible without it.

## Generalisation, measured honestly

`tools/make_stress.py` builds sets with unseen names, translated headers, shifted columns, new ID and date formats,
hidden channels and canaries. Three seeds: 0% critical IDs, 0% names, 0 of 10 canaries. `tools/make_stress2.py` uses
layouts we never tuned on (title rows above headers, `=`-records, pipe files, arrays of arrays, claim FHIR, Hinglish
letters). Its **first run, before any fix, leaked 42.7% of names in full** (IDs 0%); the fixes now reach 0%, but that
number is tuned, not held out. A truly blind set (41 files, 38 layouts, written by a separate agent that never saw the
detectors) leaked **46 of 625 items (7.4%) on its first run** (phones, Aadhaar, PAN, e-mail and DOB 0); after fixing the
causes it is 9 of 625, again tuned, not blind. A second blind set written by Codex (50 adversarial layouts) leaked
**107 of 658 (16.3%) on its first run** (IDs in odd shapes, PINs and villages in prose, base64 in plain text); after the
fixes 18 of 658 (2.7%, tuned). A third set, again written by Codex but asking for realistic exports (60 files, 1,463 PII
items), was run once before any change: **3 leaked (0.2%)**, all Marathi names in Devanagari beside the Latin spelling. A fourth set (70 files, 2,864 items, 12
Indian scripts) leaked **310 (10.8%) on its first run**, every name in Bengali, Tamil, Telugu, Kannada, Malayalam, Odia,
Gurmukhi, Gujarati and Urdu script, because the name detectors knew only Latin and Devanagari; after adding per-script
transliteration and script-agnostic name rules it is 8 (0.3%, tuned). A fifth set (80 files, 2,824 items: OCR noise, long documents, pipe/TSV exports with title rows, chat logs, FHIR variants) leaked **225 (8.0%) on its first run**; after fixes 26 (0.9%, tuned), mostly villages that equal the hospital name (a scorer artifact: every patient mention was redacted), phones wrapped across a line, and heavily damaged names. Sets six to eight were written by other AI models from a prompt we wrote (the model never saw our code; we checked its answer key against the files before scoring). Set six (90 files, 318 items, realistic exports): **65 leaked (20.4%) on the first run**, after fixes 9 (tuned; the rest are invented `555` phones and PINs starting with 0). Set seven (70 files, 11 Indian scripts): **94 (14.3%)**, after fixes 55, of which 52 are in scripts the organisers do not score (Tamil, Urdu, Bengali and others) and 3 in Latin. Set eight (87 files, 827 items, Hindi, Hinglish and English only, the scored scripts): **8 leaked (1.0%) on the first run**, after fixes 2 (both scorer artifacts: `संतोष` inside `संतोषजनक`, `मधु` inside `मधुमेह`). These sets found real bugs, for example a `Generic name` header that made a drug list teach the name dictionary every drug, and text after an age field that was never scanned.

## Independent follow-up validation (27 November 2026)

A fresh agent with no chat history and no access to application code authored and froze two 24-file splits before scoring. The tuning split has 8,431 PII annotations; the untouched holdout has 8,427. Each represents 384 invented patients across unfamiliar exports. Corpus hashes, verbatim annotations and encoded payloads were checked separately; answers were never mounted into the sanitisation container. The runtime and policy were frozen before opening holdout results.

The first tuning run exposed 20 filename MRN leaks and clinical loss in carriage-return-only records. Generic fixes scan complete filename components before splitting separators and preserve original line boundaries. Hospital suffix guards avoid accidental institution-name removal. Contradictory unique IDs and multi-patient FHIR batches now abstain from a single-patient identity claim.

| Independent split | PII leaked | Medical probes kept | Files processed / quarantined |
|---|---:|---:|---:|
| Tuning, after fixes | 0 / 8431 | 1391 / 1671 | 20 / 4 |
| Holdout, first run after freeze | 0 / 8427 | 1393 / 1671 | 20 / 4 |

All medical probes in processed files survived. Overall holdout preservation is 83.4%; all 278 missing probes belong to quarantined HTML/XML files. Quarantine therefore has a measured utility cost. The custom linkage oracle locates assignments for only 56/384 patients, with 328 unresolved or unexported; no assigned pseudonym mixes different oracle patients. Each patient has only one oracle record, so these data cannot measure cross-record linkage recall. This is diagnostic coverage, not perfect linkage.

A second independent agent authored a targeted-privacy probe without seeing application source or the existing attacker. A bounded 12-policy comparison varied age bands (10/15/20), k (3/5) and top code (75/85); rare-diagnosis and procedure settings remained fixed. Candidates had to retain the previous 95.7% practice utility, perfect baseline linking, zero leaks, protected clinical fidelity and exact timelines. The selected 20-year/k=3/top=75 policy raises practice preservation to 96.1% and reduces our existing targeted estimate from 37.4% to 32.9%. Its local weighted score estimate is 95.83, not an official result.

The independent probe's correct, pure high-confidence heuristic claims fall from 3 to 2; six of 14 real targets remain unresolved. Its diagnostic mass bounds change from 34.8-77.7% to 30.2-73.1%. These are uncertainty bounds for that probe, not calibrated attack probabilities or official scores. Missing evidence is counted as unknown, not safety.

`tools/hl7_r4_check.py` uses the official HL7 validator 7.0.8, pinned R4 4.0.1 definitions, package SHA-256 checks and a digest-pinned Java container. Validation runs offline with two CPUs and 4 GiB; the application gains no Java or model dependency. It parses every OperationOutcome issue instead of trusting Java's exit code. Across 19 practice bundles, raw and sanitized data have the same 50 errors: 38 missing required Observation categories and 12 unresolved custom-extension definitions. A wholly synthetic valid collection covering nine resource types has zero errors before and after sanitisation. Reference checks are enabled; external terminology is disabled, so this is not complete certification.

```text
python tools/hl7_r4_check.py --input <fhir-input> --out out_r4_raw --tools-dir out_r4_tools --prepare
python tools/hl7_r4_check.py --input <sanitized-fhir> --out out_r4_release --tools-dir out_r4_tools --baseline out_r4_raw/summary.json
```

Strict checking returns failure for errors, including pre-existing ones. Baseline mode reports new errors separately and always retains absolute error counts. Preparation downloads pinned public development artifacts; actual validation uses no network. Keep input, tools and report directories separate. The large validator JAR and all audit data stay ignored and out of the submission/runtime image.

Evidence: ignored `out_audit/r4_validation_20261127/`, `out_audit/r4_checks_final/`, `out_audit/independent_blind_20261127/` and `out_audit/independent_attack_20261127/`. No holdout-specific runtime fixes were made after its first result.

## Known limitations

- Re-identification is reduced, not eliminated: the local targeted attacker still succeeds 32.9% of the time (35.7% of its raw-input baseline). Exact intervals, hospital context and common conditions remain informative.
- Rare diagnoses and their coded displays can be generalised intentionally. Exact practice preservation is 96.1%, not 100%; strict privacy and exact rare-diagnosis fidelity conflict.
- Ambiguous dates without reliable source/patient evidence fall back deterministically to DMY. A missing year without an encounter anchor cannot be established as fact; leap-day fragments remain printable without claiming a known year.
- Memory grows with the event table. Limits must be retested for larger or different datasets. `peak_rss_mb` measures the pipeline process's peak resident memory, not a sum of parent/child peaks; the Linux runner additionally records cgroup peak memory.
- New formats, novel cues and damaged OCR can still defeat detection. Historical blind-set results above remain historical; neither the practice set nor generated validation sets establish hidden-dataset performance.
- Independent HL7 validation is now available as a development check. The practice source and release both contain 50 pre-existing R4 errors; no full R4 certification is claimed. External terminology validation is disabled.
- Multi-patient FHIR bundles and units with contradictory unique identities are redacted but left unassigned. Safe abstention reduces linkage coverage on unfamiliar batch exports; it does not establish complete patient linking.

## Reproduce the local audit

Use Python 3.11 with the pinned requirements. Clone the official Team Kit with `git -c core.autocrlf=false clone https://github.com/Reinforce-SST/Secret-Wards-ToolKit.git <kit>`; audit commands reject practice files whose bytes differ from the supplied SHA-256.

```powershell
$env:RAKSHA_SECRET = "practice"
python tools/audit.py --kit <kit> --out out_audit/hardening
python tools/check_submission.py --kit <kit> --repo . --run
python -m pytest -q
```

`tools/check_submission.py` launches the unchanged official checker with native Windows shell quoting; on Linux it leaves quoting unchanged. The official validator and submission checker must still return `CONTRACT OK` and `READY TO SUBMIT`. Outputs, policy rows, source fingerprints, clinical-loss classifications and measurements stay under ignored `out*/` folders. To reproduce policy selection, use `--sweep`; add `--apply` only to update the local policy. The audit score explicitly approximates unavailable official components and is not an official 100-point score.

For actual Linux isolation, build dependencies while online, then execute offline:

```text
docker build --target audit -t cohortcloak-audit:local .
python tools/container_check.py --tests --output out_audit/linux_tests
python tools/container_check.py --input <kit>/dev/input --output out_audit/linux
```

The final measured practice run took 8.8 seconds including container startup and about 50 MiB process peak RSS under Docker; Windows took about 2.7 seconds and 50 MiB. These are observations on this machine, not hidden-set guarantees.

The runner enforces no network, two CPUs, 4 GiB RAM with no extra swap, a read-only root/input, private temporary directories and a 900-second timeout. Its allowlisted image contains no Team Kit, truth, attacker data, audit outputs, secrets or local environments. Secrets enter the runtime through stdin rather than container metadata. It verifies input immutability, temporary-file cleanup and the declared container limits. Build-only dependencies and frozen evaluation data never become pipeline inputs. No GitHub changes are made by any of these commands.
