from .linkedin import LinkedInPlatform
from .naukri import NaukriPlatform
from .indeed import IndeedPlatform
from .internshala import IntershalaPlatform
from .unstop import UnstopPlatform
from .wellfound import WellfoundPlatform
from .glassdoor import GlassdoorPlatform

PLATFORM_REGISTRY = {
    "linkedin": LinkedInPlatform,
    "naukri": NaukriPlatform,
    "indeed": IndeedPlatform,
    "internshala": IntershalaPlatform,
    "unstop": UnstopPlatform,
    "wellfound": WellfoundPlatform,
    "glassdoor": GlassdoorPlatform,
}


def get_platform(name: str):
    if name not in PLATFORM_REGISTRY:
        raise KeyError(f"Unknown platform {name!r}; available: {list(PLATFORM_REGISTRY)}")
    return PLATFORM_REGISTRY[name]
