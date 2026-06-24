from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .providers import get_provider


WEB_SEARCH_MODES = {"auto", "ask", "off"}
WEB_SEARCH_NETWORKS = {"auto", "direct", "system"}


@dataclass(frozen=True)
class Settings:
    root: Path
    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    audit_dir: Path
    max_steps: int = 12
    interactive: bool = True
    web_search_mode: str = "auto"
    web_search_network: str = "auto"

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
    ) -> "Settings":
        resolved_root = Path(root).expanduser().resolve()
        if not resolved_root.is_dir():
            raise ValueError(f"工程目录不存在: {resolved_root}")

        max_steps = int(os.getenv("BNCT_AGENT_MAX_STEPS", "12"))
        if not 1 <= max_steps <= 50:
            raise ValueError("BNCT_AGENT_MAX_STEPS 必须在 1 到 50 之间")

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
            max_steps=max_steps,
            interactive=interactive,
            web_search_mode=configured_web_search_mode,
            web_search_network=configured_web_search_network,
        )
