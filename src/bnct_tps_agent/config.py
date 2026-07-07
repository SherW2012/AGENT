from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .providers import get_provider


WEB_SEARCH_MODES = {"auto", "ask", "off"}
WEB_SEARCH_NETWORKS = {"auto", "direct", "system"}
SEARCH_API_PROVIDERS = {"none", "bocha", "tavily", "brave"}


def user_data_dir() -> Path:
    """Stable per-user location for sessions and imported skills.

    Sessions and imported skills must survive switching the working directory,
    so they live here instead of under the project root. Overridable with
    BNCT_AGENT_DATA_DIR (used by tests and locked-down deployments)."""
    override = os.getenv("BNCT_AGENT_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".bnct_agent").resolve()


@dataclass(frozen=True)
class Settings:
    root: Path
    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    audit_dir: Path
    data_dir: Path
    max_steps: int = 32
    interactive: bool = True
    web_search_mode: str = "auto"
    web_search_network: str = "auto"
    auto_memory: bool = True
    search_provider: str = "none"
    search_api_key: str | None = None

    @classmethod
    def load(
        cls,
        root: str | Path,
        *,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        interactive: bool = True,
        web_search_mode: str | None = None,
        web_search_network: str | None = None,
        auto_memory: bool | None = None,
        search_provider: str | None = None,
        search_api_key: str | None = None,
    ) -> "Settings":
        resolved_root = Path(root).expanduser().resolve()
        if not resolved_root.is_dir():
            raise ValueError(f"工程目录不存在: {resolved_root}")

        # Per-turn tool-round budget. Multi-phase agentic skills (research,
        # build-fix loops) legitimately need dozens of rounds; hitting the
        # budget PAUSES the run (progress kept, user says 继续) instead of
        # failing it, so this is a cost checkpoint, not a hard wall.
        max_steps = int(os.getenv("BNCT_AGENT_MAX_STEPS", "32"))
        if not 1 <= max_steps <= 120:
            raise ValueError("BNCT_AGENT_MAX_STEPS 必须在 1 到 120 之间")

        profile = get_provider(provider or os.getenv("BNCT_AGENT_PROVIDER", "deepseek"))
        provider_model_env = f"BNCT_AGENT_{profile.id.upper()}_MODEL"
        configured_base_url = base_url
        if configured_base_url is None:
            configured_base_url = os.getenv(f"{profile.id.upper()}_BASE_URL") or profile.base_url
        configured_web_search_mode = (web_search_mode or os.getenv("BNCT_AGENT_WEB_SEARCH_MODE", "auto")).lower()
        if configured_web_search_mode not in WEB_SEARCH_MODES:
            raise ValueError("BNCT_AGENT_WEB_SEARCH_MODE must be one of: auto, ask, off")
        configured_web_search_network = (web_search_network or os.getenv("BNCT_AGENT_WEB_SEARCH_NETWORK", "auto")).lower()
        if configured_web_search_network not in WEB_SEARCH_NETWORKS:
            raise ValueError("BNCT_AGENT_WEB_SEARCH_NETWORK must be one of: auto, direct, system")
        if auto_memory is None:
            auto_memory = os.getenv("BNCT_AGENT_AUTO_MEMORY", "1").strip().lower() not in {"0", "false", "off"}
        configured_search_provider = (search_provider or os.getenv("BNCT_AGENT_SEARCH_PROVIDER", "none")).strip().lower()
        if configured_search_provider not in SEARCH_API_PROVIDERS:
            raise ValueError("BNCT_AGENT_SEARCH_PROVIDER must be one of: none, bocha, tavily, brave")
        configured_search_key = search_api_key or os.getenv("BNCT_AGENT_SEARCH_API_KEY") or None

        return cls(
            root=resolved_root,
            provider=profile.id,
            model=(
                model
                or os.getenv(provider_model_env)
                or os.getenv(f"{profile.id.upper()}_MODEL")
                or profile.default_model
            ),
            api_key=api_key or os.getenv(profile.key_env),
            base_url=configured_base_url,
            audit_dir=resolved_root / ".bnct_agent" / "audit",
            data_dir=user_data_dir(),
            max_steps=max_steps,
            interactive=interactive,
            web_search_mode=configured_web_search_mode,
            web_search_network=configured_web_search_network,
            auto_memory=bool(auto_memory),
            search_provider=configured_search_provider,
            search_api_key=configured_search_key,
        )
