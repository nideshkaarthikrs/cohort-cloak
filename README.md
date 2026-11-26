# CohortCloak: Secret Wards (Track 3)

**Team Moorthi Annan Gang**: Nidesh Kaarthik R S, SRISANJAY G, Prithviraj S, Sai Samanvith G.

An offline, CPU-only, LLM-free privacy firewall for synthetic Indian hospital records. It reads a mixed dump
(CSV/TSV, nested JSON, FHIR bundles, free text in English, Hindi and Hinglish), removes personal data, keeps the medical
content, gives every patient one stable keyed pseudonym across all files, and generalises what is left so a
voter-registry attacker cannot re-identify people.

**Declared models: none.** No LLM, no neural network, no trained model of any kind. Detection is rules, validators,
gazetteers (Faker `en_IN`/`hi_IN` plus hand-written lists) and classical string similarity (RapidFuzz, Jellyfish).

## Setup and run

```bash
uv venv --python 3.11 .venv && . .venv/bin/activate        # runs on Python 3.10+
pip install -r requirements.txt -r requirements-dev.txt     # dev adds Faker and pytest only
RAKSHA_SECRET=practice python main.py --input ../Secret-Wards-ToolKit/dev/input --output out
bash tools/check_all.sh                                     # every gate: contract, leaks, linking, privacy, stress, tests
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

Dates in every format keep their shape and move by one per-patient shift (never 0, up to +-180 days), so stays and
intervals stay exact. Ages become one band per patient that covers every observed age. Rare ICD codes go to their
category, then chapter, in all of a patient's records; k-anonymity over (gender, age band, district) widens bands and
finally replaces district, tehsil and PIN prefix with the state. `tools/sweep.py` scored policy variants with
`25*(1-risk)*min(1,U/0.4) + 20*U` using our own re-implementation of the attacks (`tools/attack_sim.py`); the table is
in `tools/sweep_results.md`. Chosen: DOB redacted (FHIR uses the data-absent-reason extension), village redacted,
tehsil to district, PIN 3-digit prefix, 5-year bands, `k_min` 5, rare threshold scaled with cohort size (floor 3, cap 8).

| Dev set (48 patients) | Value |
|---|---|
| personal data leaked (all languages and channels) | 0 of 3230 |
| medical values kept | 94.3% (rare diagnoses, procedures and package codes are generalised on purpose) |
| linking precision / recall / F0.5, wrong merges | 1.000 / 1.000 / 1.000, 0 (0 of 48 patients split) |
| own attack simulation vs raw: A3 / A4 / A5 | 4.4% / 2.1% / 48.3% |
| intervals exact, ages truthful | 99.5%, 350/350 |
| run time / peak memory | about 1 s / 52 MB (10x data: scaling exponent 0.89) |

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
number is tuned, not held out.

## Known limitations

- A5 (targeted attack) stays at 48% of raw on the dev set; stricter rare-diagnosis suppression lowers it to 17% but
  drops medical kept to about 89%.
- Entirely new document layouts remain the main risk; stress sets and attack numbers are our own, not the organisers'.
- Procedures and package codes are generalised only in structured fields (not inside prose); `rare_proc_mode: keep` turns it off.
- OPD file names keep the month; `dob_mode: redact` and village redaction cost generalisation score.
- Memory grows with the number of events (about 430 MB for 12 MB of dev data repeated ten times, about 980 MB and 64 s for 36 MB).
- Weights and thresholds were tuned on the practice data.
