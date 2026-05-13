from .linkedin import LinkedInPlatform

PLATFORM_REGISTRY = {
    "linkedin": LinkedInPlatform,
}


def get_platform(name: str):
    if name not in PLATFORM_REGISTRY:
        raise KeyError(f"Unknown platform {name!r}; available: {list(PLATFORM_REGISTRY)}")
    return PLATFORM_REGISTRY[name]
