import json
import os
from pathlib import Path

from fastapi_app.agent import hermes_config


def _norm(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def test_build_hermes_pythonpath_excludes_backend_root_and_children(monkeypatch, tmp_path):
    hermes_dir = tmp_path / "tools" / "hermes-agent"
    backend_root = tmp_path / "prism_backend"
    nested_backend_dir = backend_root / "utils"
    external_dir = tmp_path / "external"
    base_dir = tmp_path / "base"

    for path in (hermes_dir, nested_backend_dir, external_dir, base_dir):
        path.mkdir(parents=True, exist_ok=True)

    # 路径分隔符必须用 os.pathsep：Windows 是 ";"，POSIX(Linux CI) 是 ":"。
    # 生产代码 build_hermes_pythonpath 按 os.pathsep 拆分 base，
    # 测试若写死 ";"，在 Linux 上整串会被当成单个路径 -> 断言必挂（跨平台假失败）。
    pythonpath = hermes_config.build_hermes_pythonpath(
        hermes_dir,
        base=os.pathsep.join(
            [str(base_dir), str(backend_root), str(nested_backend_dir), str(external_dir)]
        ),
        exclude=(backend_root,),
    ).split(os.pathsep)

    normalized = [_norm(path) for path in pythonpath]

    # 防回归：每个元素都必须是真实存在的目录，不允许是「夹带分隔符的整串」。
    # 分隔符写死时（Windows ";" / POSIX ":"）就会在这里响，而不是在别的平台上炸。
    assert all(Path(entry).is_dir() for entry in pythonpath)

    assert normalized[0] == _norm(hermes_dir.resolve())
    assert _norm(base_dir.resolve()) in normalized
    assert _norm(external_dir.resolve()) in normalized
    assert _norm(backend_root.resolve()) not in normalized
    assert _norm(nested_backend_dir.resolve()) not in normalized


def test_get_gateway_platform_status_uses_isolated_subprocess(monkeypatch, tmp_path):
    hermes_dir = tmp_path / "tools" / "hermes-agent"
    backend_root = tmp_path / "prism_backend"
    nested_backend_dir = backend_root / "utils"
    python_exe = tmp_path / "prismenv" / "Scripts" / "python.exe"
    extra_dir = tmp_path / "extra"

    for path in (hermes_dir, nested_backend_dir, python_exe.parent, extra_dir):
        path.mkdir(parents=True, exist_ok=True)
    python_exe.write_text("", encoding="utf-8")

    # 同上：PYTHONPATH 的分隔符也要跟着平台走 os.pathsep
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join([str(backend_root), str(nested_backend_dir), str(extra_dir)]),
    )
    monkeypatch.setattr(hermes_config, "get_hermes_source_path", lambda: hermes_dir)
    monkeypatch.setattr(hermes_config, "get_backend_root", lambda: backend_root)
    monkeypatch.setattr(hermes_config, "get_hermes_python_path", lambda: python_exe)

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs["cwd"]
        # safe_run 用 env_extra 传额外环境变量（不是 subprocess.run 的 env）
        captured["env"] = kwargs["env_extra"]

        class Result:
            stdout = json.dumps({"platforms": ["discord"]}, ensure_ascii=False)

        return Result()

    # A1 迁移后 hermes_config 走 subprocess_safe.safe_run，不再直接用 subprocess
    monkeypatch.setattr(hermes_config, "safe_run", fake_run)

    status = hermes_config.get_gateway_platform_status()
    pythonpath = str(captured["env"]["PYTHONPATH"]).split(os.pathsep)

    assert status == {"configured": True, "platforms": ["discord"], "reason": ""}
    normalized = [_norm(path) for path in pythonpath]

    # 防回归：同上，每个元素都必须是真实存在的目录
    assert all(Path(entry).is_dir() for entry in pythonpath)

    assert captured["cwd"] == str(hermes_dir)
    assert normalized[0] == _norm(hermes_dir.resolve())
    assert _norm(extra_dir.resolve()) in normalized
    assert _norm(backend_root.resolve()) not in normalized
    assert _norm(nested_backend_dir.resolve()) not in normalized
