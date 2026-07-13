#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


REQUIRED_MEMBERS = {
    "install_server.sh",
    "docs/https_api_deployment.md",
    "ops/caddy/Caddyfile.example",
    "ops/systemd/bio-literature-digest-api.service.example",
    "scripts/audit_secrets.py",
    "scripts/serve_api.py",
}
FORBIDDEN_PARTS = {".archive", ".git", ".helloagents", ".venv", "__pycache__", "local", "var"}


def archive_member_path(member: str) -> PurePosixPath | None:
    path = PurePosixPath(member)
    if len(path.parts) == 1:
        return None
    if len(path.parts) < 1:
        raise ValueError(f"发行包成员缺少顶层目录：{member}")
    return PurePosixPath(*path.parts[1:])


def validate_members(members: list[str]) -> None:
    relative_members = [path for member in members if (path := archive_member_path(member)) is not None]
    files = {str(path) for path in relative_members}
    missing = sorted(REQUIRED_MEMBERS - files)
    if missing:
        raise ValueError(f"发行包缺少必要文件：{', '.join(missing)}")
    for path in relative_members:
        if any(part in FORBIDDEN_PARTS for part in path.parts) or path.suffix == ".pyc":
            raise ValueError(f"发行包包含禁止内容：{path}")


def validate_archive(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        validate_members([member.name for member in archive.getmembers()])


def write_checksum(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return checksum_path


def build_package(root: Path, output_dir: Path, release_date: str, revision: str) -> tuple[Path, Path]:
    package_name = f"bio-literature-digest-https-portable-{release_date}"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"{package_name}.tar.gz"
    temporary_path = output_dir / f".{package_name}.tar.gz.tmp"
    command = [
        "git",
        "archive",
        "--format=tar.gz",
        f"--prefix={package_name}/",
        f"--output={temporary_path}",
        revision,
    ]
    try:
        subprocess.run(command, cwd=root, check=True)
        validate_archive(temporary_path)
        temporary_path.replace(archive_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return archive_path, write_checksum(archive_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="从已提交的 Git 版本构建无私有配置的 HTTPS 便携包。")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--release-date", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    archive_path, checksum_path = build_package(root, args.output_dir.resolve(), args.release_date, args.revision)
    print(f"已生成：{archive_path}")
    print(f"校验文件：{checksum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
