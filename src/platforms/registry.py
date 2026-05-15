from .linkedin import LinkedInPlatform
from .naukri import NaukriPlatform
from .indeed import IndeedPlatform
from .internshala import IntershalaPlatform
from .unstop import UnstopPlatform

PLATFORM_REGISTRY = {
    "linkedin": LinkedInPlatform,
    "naukri": NaukriPlatform,
    "indeed": IndeedPlatform,
    "internshala": IntershalaPlatform,
    "unstop": UnstopPlatform,
}


def get_platform(name: str):
    if name not in PLATFORM_REGISTRY:
        raise KeyError(f"Unknown platform {name!r}; available: {list(PLATFORM_REGISTRY)}")
    return PLATFORM_REGISTRY[name]
