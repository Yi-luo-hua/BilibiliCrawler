"""Local wheel smoke, or installed-package smoke inside a clean G-stage venv.

Wheel mode reuses interpreter dependencies (F). The G matrix runner creates
fresh venvs before calling --installed; one invocation is not a full matrix.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

CANARY = "sk-package-smoke-canary-918273"
TOOLS = {"crawl_comments", "crawl_and_analyze", "analyze_run", "get_task_status",
         "stop_task", "list_runs", "delete_run"}


def run(command, cwd, env, expected=0):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=60)
    assert result.returncode == expected, (command[0], result.returncode, result.stderr.decode("utf-8", errors="replace"))
    assert CANARY.encode() not in result.stdout + result.stderr
    return result.stdout.decode("utf-8")


async def handshake(command, args, cwd, env):
    from mcp import Client, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=command, args=args, cwd=cwd, env=env)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr:
        async with Client(stdio_client(params, errlog=stderr), mode="legacy", read_timeout_seconds=10) as client:
            assert {item.name for item in (await client.list_tools()).tools} == TOOLS
        stderr.seek(0)
        assert CANARY not in stderr.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path, nargs="?")
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--expect-mcp", choices=("yes", "no"))
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    if bool(args.wheel) == args.installed:
        parser.error("provide a wheel or --installed, exclusively")
    wheel = args.wheel.resolve(strict=True) if args.wheel else None
    if args.installed:
        import site as python_site
        from importlib import metadata
        assert sys.prefix != sys.base_prefix and not python_site.ENABLE_USER_SITE
        assert all(Path(dist.locate_file("")).resolve().is_relative_to(Path(sys.prefix).resolve())
                   for dist in metadata.distributions()), "dependency outside venv"
    with tempfile.TemporaryDirectory(prefix="bilibili-install-", dir=args.work_dir) as directory:
        root = Path(directory)
        site, cwd, home = root / "site", root / "unrelated-cwd", root / "home"
        cwd.mkdir()
        home.mkdir()
        env = {name: value for name, value in os.environ.items() if name in
               {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}}
        env.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
                   PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HOME=str(home), USERPROFILE=str(home),
                   LOCALAPPDATA=str(root / "local"), XDG_DATA_HOME=str(root / "data"),
                   XDG_CONFIG_HOME=str(root / "config"), XDG_CACHE_HOME=str(root / "cache"),
                   BILIBILI_LLM_API_KEY=CANARY, BILIBILI_LLM_BASE_URL="http://127.0.0.1:9/v1",
                   BILIBILI_LLM_MODEL="test-model")
        if args.installed:
            site = Path(sysconfig.get_path("purelib"))
            run([sys.executable, "-m", "pip", "check"], cwd, env)
        else:
            env["PYTHONPATH"] = str(site)
            run([sys.executable, "-m", "pip", "install", "--no-deps", "--no-index", "--target", str(site), str(wheel)], cwd, env)
        # Accidental imports of legacy generic namespaces must fail, even in a
        # working directory containing those names. Only the canonical package
        # is installed, and it must not reach back into this repository.
        for name in ("src", "backend", "config", "utils"):
            (cwd / f"{name}.py").write_text("raise AssertionError('legacy namespace imported')\n", encoding="utf-8")
        suffix = ".exe" if os.name == "nt" else ""
        scripts = Path(sysconfig.get_path("scripts")) if args.installed else site
        cli = next(scripts.rglob("bilibili-crawler" + suffix))
        mcp_cli = next(scripts.rglob("bilibili-crawler-mcp" + suffix))
        help_text = run([str(cli), "--help"], cwd, env)
        assert "python -m bilibili_crawler" in help_text and "backend.agent" not in help_text
        run([str(mcp_cli), "--help"], cwd, env)
        run([sys.executable, "-m", "bilibili_crawler", "--help"], cwd, env)
        before = {p.relative_to(root) for p in root.rglob("*")}
        doctor = json.loads(run([str(cli), "doctor"], cwd, env))
        assert doctor["ok"] and not doctor["provider"]["checked"]
        assert before == {p.relative_to(root) for p in root.rglob("*")}, "doctor created files"
        listing = json.loads(run([str(cli), "list-runs"], cwd, env))
        assert listing["runs"] == []
        runs = Path(listing["root"])
        assert runs.is_relative_to(root) and not runs.is_relative_to(site) and not runs.is_relative_to(cwd)
        code = '''
import importlib.abc, importlib.metadata, json, os, sys
from pathlib import Path
requirements = importlib.metadata.requires('bilibili-crawler') or []
assert any(item.lower().startswith('pillow>=') and 'extra' not in item for item in requirements), 'missing core Pillow dependency'
class CoreOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'mcp', 'qrcode', 'jieba', 'wordcloud', 'src', 'backend', 'config', 'utils'}:
            raise AssertionError('optional or legacy import: ' + fullname)
sys.meta_path.insert(0, CoreOnly())
import bilibili_crawler
from bilibili_crawler.service import paths
from bilibili_crawler.processor.analysis_processor import LLMAnalysisProcessor
from bilibili_crawler.agent import main
from bilibili_crawler.service.models import TaskSnapshot
from bilibili_crawler.service.recovery import analysis_recovery_hint
assert not paths.SOURCE_CHECKOUT
assert Path(bilibili_crawler.__file__).is_relative_to(Path(sys.argv[1]))
assert len(LLMAnalysisProcessor.STOP_WORDS) == 32
assert LLMAnalysisProcessor._clean_word_token('转发抽奖') == ''
assert main(['doctor']) == 0
assert main(['list-runs']) == 0
failed = TaskSnapshot(task_id='smoke-task', run_id='smoke-run', kind='analyze', status='failed',
                      error_code='LLM_AUTH', artifacts={'comments_json': 'comments.json'})
hint = analysis_recovery_hint(failed, cli=True)
assert 'python -m bilibili_crawler analyze-run smoke-run' in hint and 'backend.agent' not in hint
from bilibili_crawler.service.agent_service import AgentService
class Crawler:
    def __init__(self, progress):
        self.progress = progress
        self.target_info = {'title': '安装验证'}
    def stop(self): pass
    def crawl_comments(self, *args, **kwargs):
        return [{'comment_id': 1, 'content': '包安装测试评论', 'like_count': 1, 'is_reply': False}]
class Analysis:
    _build_markdown_report = LLMAnalysisProcessor._build_markdown_report
    @staticmethod
    def analyze(comments, dynamics, params, progress=None, cancel_event=None):
        return {'summary': '安装验证 ' + os.environ['BILIBILI_LLM_API_KEY'],
                'meta': {'analyzed_records': len(comments), 'total_records': len(comments)}}
service = AgentService(api=object(), crawler_factory=Crawler, analysis_processor=Analysis)
task = service.start_crawl_and_analyze('BV1xx411c7mD', max_pages=1)
completed = service.wait(task.task_id, timeout=10)
assert completed.status == 'completed', completed.error_code
assert {'comments_json', 'analysis_json', 'report_markdown'} <= set(completed.artifacts)
secret = os.environ['BILIBILI_LLM_API_KEY']
assert secret not in completed.summary
for artifact in service.store.root.rglob('*'):
    if artifact.is_file():
        assert secret.encode() not in artifact.read_bytes()
print(json.dumps({'version': importlib.metadata.version('bilibili-crawler')}))
'''
        output = run([sys.executable, "-c", code, str(site)], cwd, env)
        version = json.loads(output.splitlines()[-1])["version"]
        mcp_available = importlib.util.find_spec("mcp") is not None
        if args.expect_mcp:
            assert mcp_available == (args.expect_mcp == "yes"), "unexpected MCP installation state"
        if args.installed:
            output = run([sys.executable, str(Path(__file__).with_name("package_crawl_probe.py"))], cwd, env)
            assert json.loads(output)["real_crawl_and_analysis"]
        if mcp_available:
            asyncio.run(handshake(str(mcp_cli), [], cwd, env))
            asyncio.run(handshake(sys.executable, ["-m", "bilibili_crawler", "mcp"], cwd, env))
        else:
            run([str(mcp_cli)], cwd, env, expected=2)
        print(json.dumps({"ok": True, "version": version, "mcp_handshake": mcp_available,
                          "core_pipeline": True, "isolated_paths": True,
                          "real_crawl_and_analysis": args.installed,
                          "clean_dependency_environment": args.installed}))


if __name__ == "__main__":
    main()
