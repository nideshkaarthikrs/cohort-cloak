"""Run the local image with actual Linux resource and network isolation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid


def digest(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--image", default="cohortcloak-audit:local")
    ap.add_argument("--tests", action="store_true")
    ap.add_argument("--secret", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()
    docker = shutil.which("docker") or r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    name = "cohortcloak-audit-" + uuid.uuid4().hex[:10]
    cmd = [docker,"create","--name",name,"--network","none","--cpus","2","--memory","4g","--memory-swap","4g",
           "--pids-limit","256","--read-only","--tmpfs","/tmp:rw,nosuid,size=512m","--tmpfs","/home/cloak:rw,nosuid,size=64m",
           "-e","HOME=/home/cloak","-e","TMPDIR=/tmp","-e","PYTHONHASHSEED="+os.environ.get("PYTHONHASHSEED","17"),
           "--mount",f"type=bind,src={out},dst=/output","--entrypoint","python"]
    before = None
    secret = args.secret or os.environ.get("RAKSHA_SECRET", "")
    if args.tests:
        tail=["-m","pytest","-q","-p","no:cacheprovider","--basetemp","/tmp/tests"]
    else:
        if args.input is None: ap.error("--input is required")
        inp=args.input.resolve(); before=digest(inp)
        cmd += ["--mount",f"type=bind,src={inp},dst=/input,readonly"]
        entry = """import os,sys,runpy,json
from pathlib import Path
os.environ['RAKSHA_SECRET']=bytes.fromhex(sys.stdin.readline().strip()).decode()
sys.argv=['main.py','--input','/input','--output','/output/release']
try:
    runpy.run_path('main.py',run_name='__main__')
except SystemExit as exc:
    if exc.code not in (0,None): raise
files=sum(p.is_file() for base in ['/tmp','/home/cloak'] for p in Path(base).rglob('*'))
peak=Path('/sys/fs/cgroup/memory.peak')
hygiene={'temporary_files_remaining':files,'cgroup_peak_bytes':int(peak.read_text()) if peak.exists() else None,'network_interfaces':sorted(p.name for p in Path('/sys/class/net').iterdir())}
Path('/output/hygiene.json').write_text(json.dumps(hygiene,indent=2))
assert files==0
"""
        tail=["-c",entry]
        cmd.append("-i")
    env={k:v for k,v in os.environ.items() if k!="RAKSHA_SECRET"}
    if not args.tests and not secret: ap.error("Set RAKSHA_SECRET")
    started=time.monotonic()
    result={"network":"none","cpus":2,"memory_bytes":4*1024**3,"timeout_seconds":900}
    try:
        subprocess.run(cmd+[args.image]+tail,env=env,check=True,capture_output=True)
        run=subprocess.run([docker,"start","-a"]+([] if args.tests else ["-i"])+[name],env=env,input=None if args.tests else (secret.encode().hex()+"\n").encode(),capture_output=True,timeout=900)
        (out/"stdout.txt").write_bytes(run.stdout); (out/"stderr.txt").write_bytes(run.stderr)
        inspect=json.loads(subprocess.check_output([docker,"inspect",name]))[0]
        assert inspect["HostConfig"]["NetworkMode"]=="none"
        assert inspect["HostConfig"]["ReadonlyRootfs"] and inspect["HostConfig"]["MemorySwap"]==4*1024**3
        assert inspect["HostConfig"]["Memory"]==4*1024**3 and inspect["HostConfig"]["NanoCpus"]==2_000_000_000
        result.update(exit_code=inspect["State"]["ExitCode"],oom_killed=inspect["State"]["OOMKilled"],wall_seconds=round(time.monotonic()-started,3))
        if before is not None:
            result["input_unchanged"]=before==digest(inp)
            assert result["input_unchanged"]
        assert result["exit_code"]==0 and not result["oom_killed"], run.stderr.decode(errors="replace")[-1000:]
        print(run.stdout.decode("utf-8",errors="replace"))
    except subprocess.TimeoutExpired:
        result.update(timeout=True,exit_code=None)
        raise
    finally:
        subprocess.run([docker,"rm","-f",name],capture_output=True)
        (out/"container_check.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
