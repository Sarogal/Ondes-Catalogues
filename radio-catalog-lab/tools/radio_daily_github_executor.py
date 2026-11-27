"""Dormant, explicitly authorized HTTPS Git adapter for the laboratory ref.

No environment credential discovery, CLI, scheduled invocation or production
publication. Use the independent readback adapter through the transfer contract.
"""
import base64
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from radio_daily_git_lab_transport import LocalGitLabTransport
from radio_daily_github_transfer_contract import TransferPlan, transmit


def _credential(token):
    if (not isinstance(token, str) or not 1 <= len(token) <= 8192
            or not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token)):
        raise ValueError("invalid explicit Git write credential")
    return "Authorization: Basic " + base64.b64encode(
        ("x-access-token:" + token).encode("ascii")).decode("ascii")


def _run(git, args, *, cwd, env, timeout):
    # Never propagate stderr, argv from exceptions, or the credential environment.
    try:
        result = subprocess.run([git, *args], cwd=cwd, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("isolated Git execution unavailable") from None
    if result.returncode:
        raise ValueError("isolated Git operation refused")


def transmit_github(source, store, plan, *, read_head, read_tree,
                    write_token, authorized=False, timeout=120, checkpoint=None):
    """Transfer only a verified direct successor, using an isolated bare repo.

    Explicit authorization is necessary but not sufficient: transmit() rebuilds
    the plan, checks the previous tree and reads the remote ref before/after
    the exact lease. No key or token is written to a file or command argument.
    A fresh temporary Git directory prevents source-local URL rewrites, hooks,
    credential helpers and push settings from influencing the network call.
    """
    if authorized is not True:
        raise ValueError("explicit laboratory transfer authorization required")
    if type(plan) is not TransferPlan or not isinstance(source, LocalGitLabTransport):
        raise ValueError("verified transfer plan and source required")
    if type(timeout) is not int or not 1 <= timeout <= 300:
        raise ValueError("invalid Git push timeout")
    header = _credential(write_token)
    git = shutil.which("git", path=os.defpath)
    if not git or not os.path.isabs(git):
        raise ValueError("trusted system Git unavailable")

    def execute(args):
        if args != plan.push_args():
            raise ValueError("unexpected Git transfer command")
        objects = (source.repository / "objects").resolve(strict=True)
        if not objects.is_dir() or any(c in str(objects) for c in ("\n", "\r")):
            raise ValueError("invalid source object directory")
        with tempfile.TemporaryDirectory(prefix="radio-github-transfer-") as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir(mode=0o700)
            repository = root / "transfer.git"
            env = dict(PATH=os.defpath, HOME=str(home), XDG_CONFIG_HOME=str(home),
                LANG="C", LC_ALL="C", GIT_CONFIG_NOSYSTEM="1",
                GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
                GIT_NO_REPLACE_OBJECTS="1")
            _run(git, ["init", "--bare", "--template=", "--object-format=sha1",
                       str(repository)], cwd=tmp, env=env, timeout=min(timeout, 30))
            (repository / "objects/info").mkdir(parents=True, exist_ok=True)
            (repository / "objects/info/alternates").write_text(str(objects)+"\n", encoding="utf-8")
            settings = [
                ("http.sslVerify", "true"),
                ("http.followRedirects", "false"),
                ("http.proxy", ""),
                ("credential.helper", ""),
                ("core.hooksPath", os.devnull),
                ("http.https://github.com/Sarogal/Ondes-Catalogues.git.extraHeader", header),
            ]
            push_env = dict(env, GIT_CONFIG_COUNT=str(len(settings)))
            for i, (key, value) in enumerate(settings):
                push_env["GIT_CONFIG_KEY_"+str(i)] = key
                push_env["GIT_CONFIG_VALUE_"+str(i)] = value
            _run(git, ["--git-dir="+str(repository), *args], cwd=tmp,
                 env=push_env, timeout=timeout)

    return transmit(source, store, plan, read_head=read_head, read_tree=read_tree,
                    execute=execute, checkpoint=checkpoint)
