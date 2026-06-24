from __future__ import annotations

import io
import json
import shutil
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen


MAX_ARCHIVE_BYTES = 40_000_000
MAX_EXTRACTED_BYTES = 120_000_000
MAX_ARCHIVE_FILES = 2_000
GITHUB_HOSTS = {"github.com", "www.github.com"}


@dataclass(frozen=True)
class GitHubSkillSpec:
    owner: str
    repo: str
    ref: str
    subpath: str


def _open_url(request: Request, timeout: int = 60):
    return urlopen(request, timeout=timeout)


def parse_github_skill_url(url: str, *, ref: str = "") -> GitHubSkillSpec:
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"https", "http"} or parsed.netloc.lower() not in GITHUB_HOSTS:
        raise ValueError("只支持明确的 GitHub 仓库 URL，例如 https://github.com/owner/repo")

    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError("GitHub URL 缺少 owner/repo")
    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    if not owner or not repo:
        raise ValueError("GitHub URL 缺少 owner/repo")

    url_ref = ""
    subpath_parts: list[str] = []
    if len(parts) >= 4 and parts[2] in {"tree", "blob"}:
        url_ref = parts[3]
        subpath_parts = parts[4:]
        if parts[2] == "blob" and subpath_parts and subpath_parts[-1].lower() == "skill.md":
            subpath_parts = subpath_parts[:-1]

    subpath = "/".join(part for part in subpath_parts if part not in {"", "."})
    if any(part == ".." for part in PurePosixPath(subpath).parts):
        raise ValueError("GitHub skill 路径不能包含 ..")
    return GitHubSkillSpec(owner=owner, repo=repo, ref=str(ref or url_ref).strip(), subpath=subpath)


def _request(url: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "application/vnd.github+json, application/octet-stream;q=0.9",
            "User-Agent": "BNCT-TPS-Agent",
        },
    )


def _download(url: str, *, max_bytes: int = MAX_ARCHIVE_BYTES, timeout: int = 90) -> bytes:
    try:
        with _open_url(_request(url), timeout=timeout) as response:
            length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
            if length and int(length) > max_bytes:
                raise ValueError(f"下载内容过大，超过 {max_bytes // 1_000_000} MB")
            data = response.read(max_bytes + 1)
    except HTTPError as exc:
        raise FileNotFoundError(f"GitHub 下载失败: HTTP {exc.code}") from exc
    except URLError as exc:
        raise ConnectionError(f"无法连接 GitHub: {exc.reason}") from exc
    if len(data) > max_bytes:
        raise ValueError(f"下载内容过大，超过 {max_bytes // 1_000_000} MB")
    return data


def _default_branch(owner: str, repo: str) -> str:
    api_url = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}"
    try:
        payload = json.loads(_download(api_url, max_bytes=200_000, timeout=30).decode("utf-8"))
    except Exception:
        return ""
    branch = str(payload.get("default_branch") or "").strip()
    return branch if branch else ""


def _candidate_refs(spec: GitHubSkillSpec) -> list[str]:
    if spec.ref:
        return [spec.ref]
    refs = [_default_branch(spec.owner, spec.repo), "main", "master"]
    result: list[str] = []
    for ref in refs:
        if ref and ref not in result:
            result.append(ref)
    return result


def _archive_url(spec: GitHubSkillSpec, ref: str) -> str:
    return (
        f"https://codeload.github.com/{quote(spec.owner)}/{quote(spec.repo)}"
        f"/zip/refs/heads/{quote(ref, safe='/')}"
    )


def _safe_extract(zip_file: zipfile.ZipFile, destination: Path) -> None:
    members = zip_file.infolist()
    if len(members) > MAX_ARCHIVE_FILES:
        raise ValueError("GitHub skill 压缩包文件数量过多")
    total_size = sum(item.file_size for item in members)
    if total_size > MAX_EXTRACTED_BYTES:
        raise ValueError(f"GitHub skill 解压后超过 {MAX_EXTRACTED_BYTES // 1_000_000} MB")
    destination = destination.resolve()
    for member in members:
        parts = PurePosixPath(member.filename).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("GitHub skill 压缩包包含不安全路径")
        target = (destination / Path(*parts)).resolve()
        try:
            target.relative_to(destination)
        except ValueError as exc:
            raise ValueError("GitHub skill 压缩包包含越界路径") from exc
    zip_file.extractall(destination)


@contextmanager
def stage_github_skill(url: str, *, ref: str = "", temp_parent: Path | None = None) -> Iterator[Path]:
    spec = parse_github_skill_url(url, ref=ref)
    errors: list[str] = []
    temp_root = temp_parent or Path.cwd()
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_path = temp_root / f"bnct-github-skill-{uuid.uuid4().hex}"
    temp_path.mkdir()
    try:
        for candidate_ref in _candidate_refs(spec):
            try:
                archive = _download(_archive_url(spec, candidate_ref))
                extract_dir = temp_path / "extract"
                if extract_dir.exists():
                    for child in extract_dir.iterdir():
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                extract_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
                    _safe_extract(zip_file, extract_dir)
                archive_roots = [path for path in extract_dir.iterdir() if path.is_dir()]
                if not archive_roots:
                    raise ValueError("GitHub skill 压缩包为空")
                source = (archive_roots[0] / spec.subpath).resolve()
                try:
                    source.relative_to(archive_roots[0].resolve())
                except ValueError as exc:
                    raise ValueError("GitHub skill 子目录越界") from exc
                if not (source / "SKILL.md").is_file():
                    raise ValueError("GitHub 仓库或子目录中没有 SKILL.md")
                yield source
                return
            except (FileNotFoundError, ValueError, zipfile.BadZipFile, ConnectionError) as exc:
                errors.append(f"{candidate_ref}: {exc}")
                if spec.ref:
                    break
        joined = "; ".join(errors) if errors else "未能解析 GitHub 仓库"
        raise ValueError(f"无法安装 GitHub skill ({joined})")
    finally:
        shutil.rmtree(temp_path, ignore_errors=True)
