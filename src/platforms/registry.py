"""Platform registry — maps platform names to their implementation classes."""

from .linkedin import LinkedInPlatform
from .naukri import NaukriPlatform
from .internshala import IntershalaPlatform
from .unstop import UnstopPlatform
from .wellfound import WellfoundPlatform
from .indeed import IndeedPlatform
from .glassdoor import GlassdoorPlatform
from .ycombinator import YCombinatorPlatform
from .cutshort import CutshortPlatform

PLATFORM_REGISTRY = {
    "linkedin": LinkedInPlatform,
    "naukri": NaukriPlatform,
    "internshala": IntershalaPlatform,
    "unstop": UnstopPlatform,
    "wellfound": WellfoundPlatform,
    "indeed": IndeedPlatform,
    "glassdoor": GlassdoorPlatform,
    "ycombinator": YCombinatorPlatform,
    "cutshort": CutshortPlatform,
}


def get_platform(name: str, config):
    """Return an initialized platform instance by name."""
    name = name.lower()
    cls = PLATFORM_REGISTRY.get(name)
    if not cls:
        raise ValueError(f"Unknown platform: '{name}'. Available: {list(PLATFORM_REGISTRY.keys())}")
    return cls(config)
