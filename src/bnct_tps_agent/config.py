from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .providers import get_provider


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
        )
