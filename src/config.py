"""
Configuration loader with dot-access support.
Loads and validates config/profile.yaml.
"""

import os
import yaml
from pathlib import Path


class AttrDict(dict):
    """Dictionary subclass that allows attribute-style dot access."""

    def __getattr__(self, name):
        try:
            value = self[name]
            if isinstance(value, dict):
                return AttrDict(value)
            return value
        except KeyError:
            raise AttributeError(f"Config has no attribute '{name}'")

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError:
            raise AttributeError(f"Config has no attribute '{name}'")

    def get(self, key, default=None):
        value = super().get(key, default)
        if isinstance(value, dict):
            return AttrDict(value)
        return value


def _to_attr_dict(obj):
    """Recursively convert dicts to AttrDict."""
    if isinstance(obj, dict):
        return AttrDict({k: _to_attr_dict(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_to_attr_dict(item) for item in obj]
    return obj


REQUIRED_FIELDS = {
    "personal.email": ("personal", "email"),
    "personal.full_name": ("personal", "full_name"),
    "ai.api_key": ("ai", "api_key"),
    "ai.provider": ("ai", "provider"),
    "search.keywords": ("search", "keywords"),
    "search.locations": ("search", "locations"),
    "search.min_fit_score": ("search", "min_fit_score"),
}


class Config:
    """Top-level config object. Access any key via dot notation."""

    def __init__(self, data: dict):
        self._data = _to_attr_dict(data)

    def __getattr__(self, name):
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"Config section '{name}' not found")

    def get(self, key, default=None):
        """Top-level dict-style get(); returns AttrDict for dict values."""
        value = self._data.get(key, default)
        if isinstance(value, dict):
            return AttrDict(value)
        return value

    def __contains__(self, key):
        return key in self._data

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        """Load and validate config from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found: {path}\n"
                "Copy config/profile.yaml.example and fill in your details."
            )

        with open(path, "r") as f:
            raw = yaml.safe_load(f)

        if raw is None:
            raise ValueError("Config file is empty.")

        config = cls(raw)
        config._validate()
        config._apply_env_overrides()
        return config

    def _validate(self):
        """Raise if any required field is missing or still a placeholder."""
        errors = []
        for field_path, keys in REQUIRED_FIELDS.items():
            value = self._data
            for key in keys:
                if not isinstance(value, dict) or key not in value:
                    errors.append(f"Missing required field: {field_path}")
                    value = None
                    break
                value = value[key]
            if value in (None, "", "YOUR_API_KEY", "you@example.com"):
                errors.append(f"Field '{field_path}' must be set to a real value.")

        if errors:
            raise ValueError("Config validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

    def _apply_env_overrides(self):
        """Allow env vars to override sensitive config values."""
        env_map = {
            "LINKEDIN_EMAIL": ("personal", "email"),
            "LINKEDIN_PASSWORD": None,  # stored separately, not in yaml
            "AI_API_KEY": ("ai", "api_key"),
            "GROQ_API_KEY": ("ai", "api_key"),
            "GEMINI_API_KEY": ("ai", "api_key"),
        }
        for env_var, keys in env_map.items():
            value = os.environ.get(env_var)
            if value and keys:
                section, field = keys
                if section in self._data:
                    self._data[section][field] = value

    def get_platform_credentials(self, platform: str) -> dict:
        """Return email/password for a given platform from env vars."""
        platform = platform.lower()
        prefix_map = {
            "linkedin": "LINKEDIN",
            "naukri": "NAUKRI",
            "internshala": "INTERNSHALA",
            "unstop": "UNSTOP",
            "wellfound": "WELLFOUND",
            "indeed": "INDEED",
            "glassdoor": "GLASSDOOR",
        }
        prefix = prefix_map.get(platform, platform.upper())
        email = os.environ.get(f"{prefix}_EMAIL") or self._data.get("personal", {}).get("email", "")
        password = os.environ.get(f"{prefix}_PASSWORD", "")
        if not password:
            password = os.environ.get("DEFAULT_PASSWORD", "")
        return {"email": email, "password": password}

    def is_platform_enabled(self, platform: str) -> bool:
        platforms = self._data.get("search", {}).get("platforms", [])
        return platform.lower() in [p.lower() for p in platforms]

    def __repr__(self):
        return f"Config(email={self._data.get('personal', {}).get('email', '?')}, " \
               f"platforms={self._data.get('search', {}).get('platforms', [])})"
