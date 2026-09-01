"""G: install both local artifacts into fresh CPython 3.10-3.13 environments.

Only installation downloads dependencies from PyPI. Smoke uses loopback fixtures.
All environments/logs remain under --work-dir; no global packages are modified.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from check_package_artifacts import audit


def execute(command, cwd, env, log):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=300)
    log.write_bytes(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}); see {log}")
    return result.stdout.decode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--sdist", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--python", action="append", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--source-ref",
                        help="immutable git commit whose runtime files must match the artifacts")
    parser.add_argument("--jobs", type=int, choices=range(1, 5), default=1,
                        help="concurrent interpreters (default 1 to avoid build/smoke disk contention)")
    parser.add_argument("--ci-shard", action="store_true",
                        help="validate exactly one supported interpreter; CI must cover the complete matrix")
    args = parser.parse_args()
    wheel, sdist = args.wheel.resolve(strict=True), args.sdist.resolve(strict=True)
    source_root = Path(__file__).resolve().parents[1] if args.source_ref else None
    artifact_report = audit(wheel, sdist, args.version,
                            (Path(__file__).resolve().parents[1], Path.home()),
                            source_root, args.source_ref)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="matrix-", dir=args.work_dir.resolve()))
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC"}}
    for name in ("temp", "home", "local"):
        (root / name).mkdir()
    env.update(TEMP=str(root / "temp"), TMP=str(root / "temp"), HOME=str(root / "home"),
               USERPROFILE=str(root / "home"), LOCALAPPDATA=str(root / "local"),
               PYTHONNOUSERSITE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    interpreters = {}
    for index, executable in enumerate(args.python):
        executable = executable.resolve(strict=True)
        version = json.loads(execute([str(executable), "-c",
            "import json,sys; print(json.dumps(list(sys.version_info[:3])))"], root, env, root / f"python-{index}.log"))
        minor = ".".join(map(str, version[:2]))
        if minor in interpreters:
            raise ValueError("duplicate Python minor version")
        interpreters[minor] = (executable, ".".join(map(str, version)))
    required = {"3.10", "3.11", "3.12", "3.13"}
    if args.ci_shard:
        if len(interpreters) != 1 or not set(interpreters) <= required:
            raise ValueError("a CI shard requires exactly one supported Python 3.10-3.13 interpreter")
    elif set(interpreters) != required:
        raise ValueError("the complete 3.10-3.13 matrix is required")
    scripts = Path(__file__).resolve().parent

    def check_python(item):
        minor, (executable, version) = item
        outcomes = []
        for artifact in (wheel, sdist):
            kind = "wheel" if artifact.suffix == ".whl" else "sdist"
            work = root / (minor + "-" + kind)
            work.mkdir()
            venv, runner = work / "venv", work / "unrelated-cwd"
            runner.mkdir()
            # No source tree on sys.path, nor editable install; copy only the
            # standalone acceptance harness, never runtime modules or fixtures.
            for name in ("check_package_install.py", "package_crawl_probe.py"):
                shutil.copyfile(scripts / name, runner / name)
            execute([str(executable), "-m", "venv", str(venv)], runner, env, work / "venv.log")
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            stages = []
            for extra in (False, True):
                name = "mcp" if extra else "core"
                execute([str(python), "-m", "pip", "install", "--no-cache-dir",
                         "--index-url", "https://pypi.org/simple", str(artifact) + ("[mcp]" if extra else "")],
                        runner, env, work / (name + "-install.log"))
                output = execute([str(python), str(runner / "check_package_install.py"), "--installed",
                                  "--expect-mcp", "yes" if extra else "no", "--work-dir", str(work)],
                                 runner, env, work / (name + "-smoke.log"))
                result = json.loads(output.splitlines()[-1])
                if not result["ok"] or result["version"] != args.version or not result["clean_dependency_environment"]:
                    raise RuntimeError("installed artifact mismatch")
                packages = json.loads(execute([str(python), "-m", "pip", "list", "--format=json"],
                                             runner, env, work / (name + "-packages.json")))
                stages.append({"extra": name, "smoke": result, "packages": packages})
                print(f"PASS Python {version} {kind} {name}", flush=True)
            outcomes.append({"python": version, "artifact": kind, "stages": stages})
        return outcomes

    report = {"ok": False, "mode": "ci-shard" if args.ci_shard else "full-matrix",
              "jobs": args.jobs, "artifacts": artifact_report, "matrix": [], "errors": []}
    report_path = root / "report.json"
    try:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            pending = {pool.submit(check_python, item): item[0] for item in sorted(interpreters.items())}
            for future in as_completed(pending):
                try:
                    report["matrix"].extend(future.result())
                except Exception as error:
                    report["errors"].append({"python": pending[future], "error": str(error)})
        report["matrix"].sort(key=lambda row: (row["python"], row["artifact"]))
        expected_rows = 2 if args.ci_shard else 8
        report["ok"] = not report["errors"] and len(report["matrix"]) == expected_rows
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Report: {report_path}", flush=True)
    if not report["ok"]:
        raise RuntimeError("matrix incomplete")


if __name__ == "__main__":
    main()
