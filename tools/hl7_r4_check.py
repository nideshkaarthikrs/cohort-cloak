#!/usr/bin/env python3
"""Development-only, pinned offline HL7 R4 checks; Python standard library only.

--prepare permits pinned public artifact downloads and cache seeding. Validation
always runs with Docker networking disabled. Baselines measure error regression,
not absolute conformance. No application modules are imported.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import dataclass, asdict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import uuid

VERSION = '7.0.8'
FHIR_VERSION = '4.0.1'
IMAGE = 'eclipse-temurin@sha256:d77e090ae1f6970c047b443c6f0a6c1358b0426d44432bb5a7753408cd43de0d'
DOCKER = r'C:\Program Files\Docker\Docker\resources\bin\docker.exe' if os.name == 'nt' else 'docker'
DEFAULT_TOOLS = Path(__file__).resolve().parents[1] / 'out_audit' / 'r4_validation_20261127'
SEVERITIES = ('fatal', 'error', 'warning', 'information')
ERRORS = frozenset(('fatal', 'error'))
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024

@dataclass(frozen=True)
class Artifact:
    package: str
    version: str
    filename: str
    url: str
    sha256: str
    manifest: str

ARTIFACTS = (
    Artifact('validator', VERSION, 'validator_cli.jar', 'https://github.com/hapifhir/org.hl7.fhir.core/releases/download/7.0.8/validator_cli.jar', 'c7c901a978bf9edc8511ffc957cdfa64bda72c500c6461cfe97a254d97759407', 'validator_manifest.json'),
    Artifact('hl7.fhir.r4.core','4.0.1','hl7.fhir.r4.core-4.0.1.tgz','https://hl7.org/fhir/R4/hl7.fhir.r4.core.tgz','b090bf929e1f665cf2c91583720849695bc38d2892a7c5037c56cb00817fb091','hl7.fhir.r4.core_manifest.json'),
    Artifact('hl7.fhir.xver-extensions','0.1.0','hl7.fhir.xver-extensions-0.1.0.tgz','https://packages2.fhir.org/packages/hl7.fhir.xver-extensions/0.1.0','f3bb9fa2083402e88a02b41f433655274e8a1cca563211c8f7ba6fd0badf537a','xver_manifest.json'),
    Artifact('hl7.terminology.r4','6.2.0','hl7.terminology.r4-6.2.0.tgz','https://packages2.fhir.org/packages/hl7.terminology.r4/6.2.0','79404c9cc95491fc0155627cd039c401a6eb4748175328131e91b709a41300e2','terminology_manifest.json'),
    Artifact('hl7.fhir.uv.extensions.r4','5.2.0','hl7.fhir.uv.extensions.r4-5.2.0.tgz','https://packages2.fhir.org/packages/hl7.fhir.uv.extensions.r4/5.2.0','b406e75575f05676559d0759770c5939d023ee72fb2ef38e0b3259328487720a','extensions_manifest.json'),
    Artifact('hl7.terminology','7.5.0','hl7.terminology-7.5.0.tgz','https://packages2.fhir.org/packages/hl7.terminology/7.5.0','c54ebe534cd3f2474459eaed68e54c34f09b003766605b19e5552db376f2cc42','hl7.terminology_manifest.json'),
    Artifact('hl7.fhir.uv.extensions','5.4.1','hl7.fhir.uv.extensions-5.4.1.tgz','https://packages2.fhir.org/packages/hl7.fhir.uv.extensions/5.4.1','ba96da396bf1e94738105817c665647b1b3fed42090a298359eb7e5b80ff5616','hl7.fhir.uv.extensions_manifest.json'),
    Artifact('hl7.terminology.r5','7.5.0','hl7.terminology.r5-7.5.0.tgz','https://packages2.fhir.org/packages/hl7.terminology.r5/7.5.0','cabae9ff7828c05173369bd2244ab6eabafe19d65b02c140a76638c1f3a56bf9','hl7.terminology.r5_manifest.json'),
    Artifact('hl7.fhir.r5.core','5.0.0','hl7.fhir.r5.core-5.0.0.tgz','https://hl7.org/fhir/R5/hl7.fhir.r5.core.tgz','74b27cd1bfce9e80eaceac431edf230b0945a443564fbf5512f82e5fa50a80d4','hl7.fhir.r5.core_manifest.json'),
)
PACKAGES = ARTIFACTS[1:]

class CheckFailure(Exception):
    pass

def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise CheckFailure(f'Absent or malformed JSON report/metadata: {path}: {exc}') from exc

def is_link(path):
    try:
        return path.is_symlink() or getattr(path.lstat(), 'st_reparse_tag', 0) in (0xA0000003, 0xA000000C)
    except FileNotFoundError:
        return False

def safe_path(value):
    path = Path(value).expanduser().absolute()
    if any(c in str(path) for c in (',', '\r', '\n', '\x00')):
        raise CheckFailure('Mount paths must not contain commas, newlines, or NUL.')
    for ancestor in (path, *path.parents):
        if is_link(ancestor):
            raise CheckFailure(f'Symbolic links and junctions are not accepted: {ancestor}')
    return path.resolve()

def separated_paths(input_path, out_path, tools_path):
    paths = [safe_path(p) for p in (input_path, out_path, tools_path)]
    for i, a in enumerate(paths):
        for b in paths[i+1:]:
            if a == b or a in b.parents or b in a.parents:
                raise CheckFailure('Input, output and tools directories must be separate, without ancestor overlap.')
    return paths

def inventory_inputs(root):
    if not root.is_dir():
        raise CheckFailure('Input must be an existing directory.')
    files = []
    for current, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            p = Path(current) / name
            if is_link(p):
                raise CheckFailure(f'Input contains a symbolic link or junction: {p}')
        for name in names:
            p = Path(current) / name
            if not p.is_file():
                raise CheckFailure(f'Input is not a regular file: {p}')
            rel = p.relative_to(root).as_posix()
            if any(c in rel for c in ('\r','\n','\x00')):
                raise CheckFailure('Input filenames must not contain control characters.')
            files.append({'file': rel, 'sha256': sha256_file(p), 'bytes': p.stat().st_size,
                          'validated': p.suffix.lower() in ('.json', '.xml')})
    files.sort(key=lambda x:x['file'])
    if not any(x['validated'] for x in files):
        raise CheckFailure('Input has no FHIR JSON or XML files to validate.')
    return files

def validate_cache_volume(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        raise CheckFailure('Cache volume must be a named Docker volume, not a path or option.')
    return value

def verify_public_manifest(tools, artifact):
    path = tools / artifact.manifest
    if path.exists():
        if is_link(path):
            raise CheckFailure('Artifact metadata must not be a symbolic link.')
        meta = read_json(path)
        if any(meta.get(k) != v for k,v in (('version',artifact.version),('url',artifact.url),('sha256',artifact.sha256))):
            raise CheckFailure(f'Public metadata disagrees with pinned artifact: {artifact.manifest}')
        return {'file': artifact.manifest, 'sha256': sha256_file(path)}
    return None

def download_artifact(artifact, destination):
    partial = destination.with_name(destination.name + '.partial-' + uuid.uuid4().hex)
    try:
        request = urllib.request.Request(artifact.url, headers={'User-Agent':'cohortcloak-hl7-r4-check/1'})
        with urllib.request.urlopen(request, timeout=60) as response, partial.open('xb') as out:
            if not response.geturl().startswith('https://'):
                raise CheckFailure('Artifact download redirected away from HTTPS.')
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise CheckFailure('Artifact exceeds the download size limit.')
                out.write(chunk)
        if sha256_file(partial) != artifact.sha256:
            raise CheckFailure(f'Download checksum mismatch: {artifact.filename}')
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)

def verified_archive(path, artifact, destination=None):
    """Check every member before manual extraction; never use extractall."""
    seen = set(); index = []; metadata = None; total = 0
    try:
        with tarfile.open(path, 'r:gz') as archive:
            for member in archive:
                name = member.name
                parts = PurePosixPath(name).parts
                if (not parts or parts[0] != 'package' or name.startswith('/') or
                    any(p in ('..', '') or ':' in p for p in parts) or
                    any(c in name for c in ('\\', '\n', '\r', '\x00'))):
                    raise CheckFailure(f'Unsafe package archive member: {name!r}')
                normalized = '/'.join(parts)
                if normalized in seen or not (member.isdir() or member.isfile()):
                    raise CheckFailure(f'Duplicate, linked, or special archive member: {name!r}')
                seen.add(normalized)
                if len(seen) > 200000:
                    raise CheckFailure('Too many archive members.')
                if member.isdir():
                    continue
                total += member.size
                if member.size < 0 or total > MAX_ARCHIVE_BYTES:
                    raise CheckFailure('Package exceeds the extraction size limit.')
                stream = archive.extractfile(member)
                if stream is None:
                    raise CheckFailure('Unreadable archive member.')
                out = None; h = hashlib.sha256(); content = bytearray()
                try:
                    if destination is not None:
                        target = destination.joinpath(*parts)
                        if not target.resolve().is_relative_to(destination.resolve()):
                            raise CheckFailure('Archive extraction escaped its staging directory.')
                        target.parent.mkdir(parents=True, exist_ok=True)
                        out = target.open('xb')
                    for chunk in iter(lambda:stream.read(1024*1024), b''):
                        h.update(chunk)
                        if out is not None: out.write(chunk)
                        if normalized == 'package/package.json':
                            if len(content)+len(chunk)>1024*1024: raise CheckFailure('Oversized package metadata.')
                            content.extend(chunk)
                finally:
                    stream.close()
                    if out is not None: out.close()
                index.append((normalized,h.hexdigest()))
                if normalized == 'package/package.json': metadata=json.loads(content)
    except (tarfile.TarError, OSError, ValueError) as exc:
        raise CheckFailure(f'Malformed public package archive: {path.name}: {exc}') from exc
    if not isinstance(metadata,dict) or metadata.get('name') != artifact.package or metadata.get('version') != artifact.version:
        raise CheckFailure(f'Package identity/version mismatch: {artifact.filename}')
    return index
def prepare_artifacts(tools, prepare):
    if prepare:
        tools.mkdir(parents=True, exist_ok=True)
        ignore = tools / '.gitignore'
        if not ignore.exists():
            ignore.write_text('*\n!.gitignore\n', encoding='utf-8')
        elif is_link(ignore) or '*' not in ignore.read_text(encoding='utf-8').splitlines():
            raise CheckFailure('Prepare requires a tools-directory .gitignore that ignores artifacts with *; existing file was not changed.')
    if not tools.is_dir():
        raise CheckFailure('Tools directory is absent; use --prepare to obtain the pinned public artifacts.')
    records = []; indexes = {}
    for artifact in ARTIFACTS:
        metadata = verify_public_manifest(tools, artifact)
        path = tools / artifact.filename
        if is_link(path):
            raise CheckFailure('Artifact files must not be symbolic links.')
        if not path.exists():
            if not prepare:
                raise CheckFailure(f'Missing artifact {artifact.filename}; use --prepare.')
            download_artifact(artifact, path)
        if not path.is_file() or sha256_file(path) != artifact.sha256:
            raise CheckFailure(f'Pinned artifact checksum mismatch: {artifact.filename}; file was not overwritten.')
        records.append(dict(asdict(artifact), bytes=path.stat().st_size, public_manifest=metadata))
        if artifact.package != 'validator':
            indexes[artifact.package] = verified_archive(path, artifact)
    return records, indexes

def docker_command(args, timeout=60):
    try:
        return subprocess.run([DOCKER, *args], capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CheckFailure(f'Docker setup failed: {exc}') from exc

def docker_setup(cache_volume, prepare):
    image = docker_command(['image', 'inspect', IMAGE])
    if image.returncode and prepare:
        pull = docker_command(['pull', IMAGE], timeout=900)
        if pull.returncode:
            raise CheckFailure('Pinned Docker image pull failed: ' + pull.stderr[-2000:])
        image = docker_command(['image', 'inspect', IMAGE])
    if image.returncode:
        raise CheckFailure('Pinned Java image is not available locally; use --prepare. ' + image.stderr[-1000:])
    try:
        image_data = json.loads(image.stdout)[0]
        if not any(v.endswith('@'+IMAGE.split('@',1)[1]) for v in image_data.get('RepoDigests', [])):
            raise ValueError('Image digest is not the declared pinned digest.')
        image_id = image_data['Id']
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise CheckFailure('Malformed or unpinned Docker image metadata.') from exc
    volume = docker_command(['volume', 'inspect', cache_volume])
    if volume.returncode and prepare:
        created = docker_command(['volume', 'create', cache_volume])
        if created.returncode:
            raise CheckFailure('Could not create the declared public-definition cache volume.')
        volume = docker_command(['volume', 'inspect', cache_volume])
    if volume.returncode:
        raise CheckFailure('Cache volume does not exist; use --prepare.')
    try:
        info = json.loads(volume.stdout)[0]
        if info['Name'] != cache_volume or info['Driver'] != 'local' or info.get('Options'):
            raise ValueError('Only an ordinary local Docker volume without host-path/network options is accepted.')
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise CheckFailure('Unsafe or malformed cache volume metadata.') from exc
    return image_id

def mount_bind(source, destination, readonly=True):
    return 'type=bind,src='+str(safe_path(source))+',dst='+destination+(',readonly' if readonly else '')

def container_command(name, mounts, entrypoint, args):
    cmd = [DOCKER, 'run', '--name', name, '--rm', '--pull=never', '--network', 'none',
           '--memory', '4g', '--cpus', '2', '--cap-drop', 'ALL',
           '--security-opt', 'no-new-privileges', '--read-only',
           '--tmpfs', '/tmp:rw,nosuid,size=512m']
    for mount in mounts:
        cmd.extend(['--mount', mount])
    cmd.extend(['--entrypoint', entrypoint, IMAGE, *args])
    if os.name == 'nt' and sum(len(x)+3 for x in cmd)>28000:
        raise CheckFailure('Too many/long input paths for one Docker invocation; use smaller input batches.')
    return cmd

def _text(value):
    return value.decode('utf-8','replace') if isinstance(value,bytes) else value or ''

def run_container(mounts, entrypoint, args, timeout, log_path=None):
    name = 'cohortcloak-r4-check-' + uuid.uuid4().hex
    cmd = container_command(name, mounts, entrypoint, args)
    failure = None
    result = None
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        if log_path:
            Path(log_path).write_text('STDOUT\n'+result.stdout+'\nSTDERR\n'+result.stderr, encoding='utf-8')
    except subprocess.TimeoutExpired as exc:
        if log_path:
            Path(log_path).write_text('TIMED OUT\nSTDOUT\n'+_text(exc.stdout)+'\nSTDERR\n'+_text(exc.stderr), encoding='utf-8')
        failure = CheckFailure(f'Container {name} exceeded {timeout} seconds.')
    except OSError as exc:
        failure = CheckFailure(f'Could not run validator container {name}: {exc}')
    except KeyboardInterrupt:
        failure = CheckFailure(f'Interrupted container {name}.')
    finally:
        # Remove only the exact name created by this call, including on timeout.
        try:
            cleanup = subprocess.run([DOCKER,'rm','--force',name], capture_output=True, timeout=30)
            if failure and cleanup.returncode and 'no such container' not in _text(cleanup.stderr).lower():
                failure = CheckFailure(str(failure)+' Exact-name cleanup failed: '+_text(cleanup.stderr)[-1000:])
        except (OSError, subprocess.TimeoutExpired) as exc:
            if failure:
                failure = CheckFailure(str(failure)+f' Exact-name cleanup could not finish: {exc}')
    if failure:
        raise failure
    return result, name, cmd

SEED_SCRIPT = r'''
set -eu
root=/cache/.fhir/packages
for parent in /cache/.fhir "$root"; do
    if [ -L "$parent" ]; then exit 70; fi
done
mkdir -p "$root"
token="$1"
shift
for package in "$@"; do
    case "$package" in
        hl7.fhir.r4.core#4.0.1|hl7.fhir.xver-extensions#0.1.0|hl7.terminology.r4#6.2.0|hl7.fhir.uv.extensions.r4#5.2.0|hl7.terminology#7.5.0|hl7.fhir.uv.extensions#5.4.1|hl7.terminology.r5#7.5.0|hl7.fhir.r5.core#5.0.0) ;;
        *) exit 71 ;;
    esac
    dest="$root/$package"
    stage="$root/.cohortcloak-seed-$token-$package"
    backup="$root/.cohortcloak-backup-$token-$package"
    if [ -L "$dest" ] || [ -e "$stage" ] || [ -e "$backup" ]; then exit 72; fi
    if [ -e "$dest" ] && [ ! -d "$dest" ]; then exit 73; fi
    mkdir "$stage"
    cp -R "/seed/$package/." "$stage/"
    if [ -e "$dest" ]; then mv "$dest" "$backup"; fi
    if mv "$stage" "$dest"; then
        if [ -e "$backup" ]; then rm -rf -- "$backup"; fi
    else
        if [ -e "$backup" ]; then mv "$backup" "$dest"; fi
        exit 74
    fi
done
'''

def seed_cache(tools, cache_volume):
    with tempfile.TemporaryDirectory(prefix='.public-r4-seed-', dir=tools) as temporary:
        stage = Path(temporary)
        for artifact in PACKAGES:
            destination = stage/(artifact.package+'#'+artifact.version)
            destination.mkdir()
            verified_archive(tools/artifact.filename, artifact, destination)
        mounts = [mount_bind(stage,'/seed'), 'type=volume,src='+cache_volume+',dst=/cache']
        result, _, _ = run_container(mounts, 'sh', ['-c',SEED_SCRIPT,'public-definition-seed',uuid.uuid4().hex,
                                    *(a.package+'#'+a.version for a in PACKAGES)], 300)
        if result.returncode:
            raise CheckFailure('Public package cache preparation failed: '+result.stderr[-2000:])

def verify_cache(indexes, cache_volume, out):
    checksums = out/'package_checksums.sha256'
    lines = []
    for artifact in PACKAGES:
        base='/cache/.fhir/packages/'+artifact.package+'#'+artifact.version+'/'
        lines.extend(h+'  '+base+path+'\n' for path,h in indexes[artifact.package] if PurePosixPath(path).name not in ('.index.json','.index.db'))
    checksums.write_text(''.join(lines), encoding='utf-8')
    result, _, _ = run_container(['type=volume,src='+cache_volume+',dst=/cache,readonly',
                                 mount_bind(checksums,'/package_checksums.sha256')],
                                'sha256sum',['--quiet','-c','/package_checksums.sha256'],300,
                                out/'cache_verification.log')
    if result.returncode:
        raise CheckFailure('Cache files do not match the pinned public definitions; use --prepare. See cache_verification.log.')

def outcome_issues(document):
    """Accept validator OperationOutcome or a Bundle containing only outcomes."""
    issues=[]
    def visit(resource, context):
        if not isinstance(resource,dict):
            raise CheckFailure('Validator outcome resource must be an object.')
        if resource.get('resourceType')=='Bundle':
            entries=resource.get('entry')
            if not isinstance(entries,list) or not entries:
                raise CheckFailure('Validator outcome Bundle has no entries.')
            for i,entry in enumerate(entries):
                if not isinstance(entry,dict) or 'resource' not in entry:
                    raise CheckFailure('Malformed validator outcome Bundle entry.')
                visit(entry['resource'],context+f'/entry/{i}')
            return
        if resource.get('resourceType')!='OperationOutcome':
            raise CheckFailure('Expected OperationOutcome, or a Bundle of OperationOutcomes.')
        values=resource.get('issue')
        if not isinstance(values,list) or not values:
            raise CheckFailure('OperationOutcome must contain a nonempty issue array.')
        for i,issue in enumerate(values):
            validate_issue(issue)
            item=dict(issue);item['_outcome_locator']=context;item['_issue_index']=i
            if 'id' in resource: item['_outcome_id']=resource['id']
            issues.append(item)
    visit(document,'')
    return issues

def validate_issue(issue):
    if (not isinstance(issue,dict) or issue.get('severity') not in SEVERITIES or
        not isinstance(issue.get('code'),str) or not issue['code']):
        raise CheckFailure('Malformed OperationOutcome issue: valid R4 severity and code are required.')
    for key in ('location','expression'):
        if key in issue and (not isinstance(issue[key],list) or not all(isinstance(x,str) for x in issue[key])):
            raise CheckFailure('Malformed issue '+key+'.')
    if 'diagnostics' in issue and not isinstance(issue['diagnostics'],str):
        raise CheckFailure('Malformed issue diagnostics.')
    if 'details' in issue:
        details=issue['details']
        if not isinstance(details,dict) or ('text' in details and not isinstance(details['text'],str)):
            raise CheckFailure('Malformed issue details.')
        if 'coding' in details and (not isinstance(details['coding'],list) or
            not all(isinstance(c,dict) and all(isinstance(c.get(k,''),str) for k in ('system','code','version')) for c in details['coding'])):
            raise CheckFailure('Malformed issue details coding.')

def normalized_text(value, roots=()):
    value=value.replace('\\','/')
    for root in sorted((str(r).replace('\\','/').rstrip('/') for r in roots if r),key=len,reverse=True):
        value=value.replace(root,'<input>')
    value=re.sub(r'(?:file:/*)?/inputs/[^\s\'\"<>]+','<input>',value)
    value=re.sub(r'<input>/[^\s\'\"<>]+\.(?:json|xml)','<input>',value,flags=re.I)
    value=re.sub(r'\b(line|column|col)\s*[:=]?\s*\d+',lambda m:m.group(1).lower()+' <n>',value,flags=re.I)
    return ' '.join(value.split())

def signature(issue, roots=()):
    details=issue.get('details',{})
    coding=sorted((c.get('system',''),c.get('version',''),c.get('code','')) for c in details.get('coding',[]))
    value={'severity':issue['severity'],'code':issue['code'],'details_text':normalized_text(details.get('text',''),roots),
           'details_coding':coding,'diagnostics':normalized_text(issue.get('diagnostics',''),roots),
           'expression':sorted(normalized_text(v,roots) for v in issue.get('expression',[])),
           'location':sorted(normalized_text(v,roots) for v in issue.get('location',[]))}
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))

def error_counter(issues, roots=()):
    return Counter(signature(i,roots) for i in issues if i['severity'] in ERRORS)

def signature_rows(counter):
    return [{'signature':json.loads(k),'signature_sha256':hashlib.sha256(k.encode()).hexdigest(),'count':v}
            for k,v in sorted(counter.items()) if v]

def assess_issues(issues, baseline=None, roots=()):
    for issue in issues: validate_issue(issue)
    counts={s:sum(i['severity']==s for i in issues) for s in SEVERITIES}
    current=error_counter(issues,roots);errors=sum(current.values())
    result={'severity_counts':counts,'error_count':errors,'issues':issues,
            'error_signatures':signature_rows(current),'absolute_conformance':False,
            'passes_requested_checks':errors==0,'status':'errors_present' if errors else 'passed_requested_checks'}
    exit_code=1 if errors else 0
    if baseline is not None:
        for issue in baseline: validate_issue(issue)
        previous=error_counter(baseline,roots)
        introduced=current-previous;preexisting=current & previous;resolved=previous-current
        result['comparison']={'baseline_error_count':sum(previous.values()),'total_current_errors':errors,
              'pre_existing_error_count':sum(preexisting.values()),'introduced_error_count':sum(introduced.values()),
              'resolved_error_count':sum(resolved.values()),'pre_existing_errors':signature_rows(preexisting),
              'introduced_errors':signature_rows(introduced),'resolved_errors':signature_rows(resolved),
              'regression_passed':not bool(introduced)}
        result['status']='introduced_errors' if introduced else 'no_new_errors'
        exit_code=1 if introduced else 0
    return result,exit_code

def load_baseline(path):
    document=read_json(path)
    if isinstance(document,dict) and document.get('report_type')=='hl7-r4-development-check':
        if document.get('runtime_success') is not True or document.get('fhir_version')!=FHIR_VERSION or document.get('validator_version')!=VERSION:
            raise CheckFailure('Baseline must be a completed report using the pinned validator and R4 version.')
        issues=document.get('issues')
        if not isinstance(issues,list): raise CheckFailure('Baseline report lacks detailed issues.')
        for issue in issues: validate_issue(issue)
        tool_meta=document.get('tools',{})
        artifacts=tool_meta.get('artifacts',[]) if isinstance(tool_meta,dict) else []
        pins={x.get('package'):x.get('sha256') for x in artifacts if isinstance(x,dict)} if isinstance(artifacts,list) else {}
        trusted=document.get('docker_image')==IMAGE and all(pins.get(a.package)==a.sha256 for a in ARTIFACTS)
        return issues,document.get('input_directory'),trusted
    return outcome_issues(document),None,False

def parser():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--input',required=True,type=Path,help='FHIR JSON/XML directory; sources are collected recursively and mounted read-only.')
    p.add_argument('--out',required=True,type=Path,help='New or empty report directory; existing reports are never overwritten.')
    p.add_argument('--tools-dir',type=Path,default=DEFAULT_TOOLS)
    p.add_argument('--cache-volume',default='cohortcloak-hl7-r4-cache')
    p.add_argument('--prepare',action='store_true',help='Download only pinned public artifacts/image if absent and seed only declared public definition packages.')
    p.add_argument('--baseline',type=Path,metavar='REPORT_JSON',help='Prior launcher summary.json or validator OperationOutcome/Bundle; compare error multisets.')
    p.add_argument('--timeout',type=int,default=900,help='Validator container deadline in seconds (default 900).')
    return p

def main(argv=None):
    args=parser().parse_args(argv)
    report={'report_type':'hl7-r4-development-check','schema_version':1,'validator_version':VERSION,
            'fhir_version':FHIR_VERSION,'docker_image':IMAGE,'absolute_conformance':False,
            'runtime_success':False,'status':'setup_failure','severity_counts':{s:0 for s in SEVERITIES},
            'issues':[],'error_count':0,'exit_code':2,'passes_requested_checks':False,
            'normalization':'Error multisets retain severity, code, messages, coding and resource expressions; only known input roots, container source paths, whitespace and line/column numbers are normalized.'}
    out=None;output_ready=False
    try:
        if not 1<=args.timeout<=7200: raise CheckFailure('Timeout must be between 1 and 7200 seconds.')
        volume=validate_cache_volume(args.cache_volume)
        inp,out,tools=separated_paths(args.input,args.out,args.tools_dir)
        repo=Path(__file__).resolve().parents[1]
        if tools==repo or tools in repo.parents or tools==Path(__file__).resolve().parent:
            raise CheckFailure('Tools directory must not be the repository root, its ancestor, or the launcher source directory.')
        if out.exists() and (not out.is_dir() or any(out.iterdir())):
            raise CheckFailure('Output must be a new or empty directory; refusing to reuse old outcomes.')
        out.mkdir(parents=True,exist_ok=True);output_ready=True
        report.update(input_directory=str(inp),output_directory=str(out),tools_directory=str(tools),cache_volume=volume)
        inputs=inventory_inputs(inp);report['inputs']=inputs
        baseline=None;baseline_root=None
        if args.baseline:
            baseline_path=safe_path(args.baseline)
            baseline,baseline_root,verified=load_baseline(baseline_path)
            report['baseline']={'file':str(baseline_path),'sha256':sha256_file(baseline_path),'provenance_verified':verified}
        artifacts,indexes=prepare_artifacts(tools,args.prepare)
        report['tools']={'launcher_sha256':sha256_file(Path(__file__)),'artifacts':artifacts,
                         'package_versions':{a.package:a.version for a in PACKAGES}}
        report['docker_image_id']=docker_setup(volume,args.prepare)
        if args.prepare: seed_cache(tools,volume)
        verify_cache(indexes,volume,out)
        report['cache_verification']='SHA256 checked against pinned archive resource files; validator-maintained index metadata is excluded.'
        sources=['/inputs/'+i['file'] for i in inputs if i['validated']]
        mounts=[mount_bind(tools/'validator_cli.jar','/validator.jar'),mount_bind(inp,'/inputs'),
                mount_bind(out,'/reports',False),'type=volume,src='+volume+',dst=/cache']
        java=['-Xmx3g','-Duser.home=/cache','-jar','/validator.jar',*sources,'-version',FHIR_VERSION,
              '-tx','n/a','-no-http-access','-check-references','-output','/reports/validator_output.json']
        report['status']='runtime_failure'
        completed,name,cmd=run_container(mounts,'java',java,args.timeout,out/'validator.log')
        report.update(container_name=name,command=cmd,java_exit_code=completed.returncode)
        raw=out/'validator_output.json'
        issues=outcome_issues(read_json(raw))
        roots=(str(inp),baseline_root)
        assessment,exit_code=assess_issues(issues,baseline,roots)
        report.update(assessment)
        write_json(out/'operation_outcome.json',{'resourceType':'OperationOutcome',
                   'issue':[{k:v for k,v in i.items() if k not in ('_outcome_locator','_issue_index','_outcome_id')} for i in issues]})
        report.update(validator_output_sha256=sha256_file(raw),operation_outcome_sha256=sha256_file(out/'operation_outcome.json'))
        if inventory_inputs(inp)!=inputs:
            raise CheckFailure('Input files changed during validation; result is not reproducible.')
        if any(sha256_file(tools/a.filename)!=a.sha256 for a in ARTIFACTS):
            raise CheckFailure('A pinned tool artifact changed during validation.')
        if completed.returncode!=0:
            raise CheckFailure(f'Validator/container exited {completed.returncode}; complete successful execution is not established.')
        report['runtime_success']=True;report['exit_code']=exit_code
    except (CheckFailure,OSError,ValueError) as exc:
        report['failure']=str(exc);report['runtime_success']=False;report['exit_code']=2;report['passes_requested_checks']=False
        if 'comparison' in report: report['comparison']['regression_passed']=False
        if report['status'] not in ('setup_failure','runtime_failure'): report['status']='runtime_failure'
    except KeyboardInterrupt:
        report.update(failure='Interrupted.',runtime_success=False,status='runtime_failure',exit_code=2,passes_requested_checks=False)
    if output_ready:
        if (out/'validator.log').exists(): report['validator_log_sha256']=sha256_file(out/'validator.log')
        write_json(out/'summary.json',report)
    print(json.dumps({'summary':str(out/'summary.json') if output_ready else None,
                      'status':report['status'],'exit_code':report['exit_code'],
                      'severity_counts':report['severity_counts'],'absolute_conformance':False,
                      **({'failure':report['failure']} if 'failure' in report else {})},ensure_ascii=False))
    return report['exit_code']

if __name__=='__main__':
    raise SystemExit(main())
