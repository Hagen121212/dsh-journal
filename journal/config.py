from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
# Data lives outside the checkout so that upgrades and `git clean` never touch it.
DEFAULT_HOME = Path.home() / "DeepSeekJournal"


@dataclass
class Config:
    home: Path
    dsh_home: Path
    db_path: Path
    data_dir: Path
    reports_dir: Path
    logs_dir: Path
    static_dir: Path
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    reasoning_effort: str = "low"
    max_output_tokens: int = 24000
    temperature: float = 0.2
    timeout_seconds: int = 180
    max_calls_per_run: int = 120
    max_total_tokens_per_run: int = 3_000_000
    growth_interval_days: int = 14
    weekly_day: str = "SUN"
    weekly_time: str = "20:00"
    timezone: str = "Asia/Shanghai"
    redact_paths: bool = True
    store_raw_copy: bool = True
    node_path: str | None = None
    api_key_env: str = "DEEPSEEK_API_KEY"
    taxonomy: list[str] = field(default_factory=lambda: [
        "技术实现", "产品需求", "研究方法", "决策规划", "表达写作", "协作沟通", "元讨论", "未归类"
    ])

    @property
    def prompt_version(self) -> str:
        return "v1"

    @classmethod
    def load(cls) -> "Config":
        env_home = os.environ.get("JOURNAL_HOME")
        env_dsh = os.environ.get("DSH_HOME")
        home = Path(env_home or str(DEFAULT_HOME)).expanduser()
        dsh_home = Path(env_dsh or str(Path.home() / ".dsh")).expanduser()
        cfg_file = PROJECT_DIR / "config.toml"
        raw: dict = {}
        if cfg_file.exists():
            with cfg_file.open("rb") as f:
                raw = tomllib.load(f)

        paths = raw.get("paths", {})
        home = Path(paths.get("home", str(home))).expanduser()
        dsh_home = Path(paths.get("dsh_home", str(dsh_home))).expanduser()
        if env_home:
            home = Path(env_home).expanduser()
        if env_dsh:
            dsh_home = Path(env_dsh).expanduser()

        model = raw.get("model", {})
        budget = raw.get("budget", {})
        privacy = raw.get("privacy", {})
        schedule = raw.get("schedule", {})

        data_dir = home / "data"
        return cls(
            home=home,
            dsh_home=dsh_home,
            db_path=data_dir / "journal.db",
            data_dir=data_dir,
            reports_dir=home / "reports",
            logs_dir=home / "logs",
            static_dir=PROJECT_DIR / "static",
            base_url=model.get("base_url", "https://api.deepseek.com").rstrip("/"),
            model=model.get("model", "deepseek-flash"),
            reasoning_effort=model.get("reasoning_effort", "low"),
            max_output_tokens=int(model.get("max_output_tokens", 8192)),
            temperature=float(model.get("temperature", 0.2)),
            timeout_seconds=int(model.get("timeout_seconds", 180)),
            max_calls_per_run=int(budget.get("max_calls_per_run", 120)),
            max_total_tokens_per_run=int(budget.get("max_total_tokens_per_run", 3_000_000)),
            growth_interval_days=int(schedule.get("growth_interval_days", 14)),
            weekly_day=schedule.get("weekly_day", "SUN"),
            weekly_time=schedule.get("weekly_time", "20:00"),
            timezone=schedule.get("timezone", "Asia/Shanghai"),
            redact_paths=bool(privacy.get("redact_paths", True)),
            store_raw_copy=bool(privacy.get("store_raw_copy", True)),
            node_path=os.environ.get("DSH_NODE") or model.get("node_path"),
            api_key_env=model.get("api_key_env", "DEEPSEEK_API_KEY"),
            taxonomy=raw.get("taxonomy", [
                "技术实现", "产品需求", "研究方法", "决策规划", "表达写作", "协作沟通", "元讨论", "未归类"
            ]),
        )

    def ensure_dirs(self) -> None:
        for p in [
            self.home,
            self.data_dir,
            self.data_dir / "raw",
            self.reports_dir,
            self.reports_dir / "weekly",
            self.reports_dir / "growth",
            self.reports_dir / "baseline",
            self.logs_dir,
        ]:
            p.mkdir(parents=True, exist_ok=True)
