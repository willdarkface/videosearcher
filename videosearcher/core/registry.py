"""Registro e roteamento de provedores de mídia.

Um provedor entra no sistema apenas por existir e usar `@register`. O import do
pacote `videosearcher.providers` carrega todos os módulos automaticamente, então
não existe lista central para manter.
"""

from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
from collections.abc import Iterable
from typing import TypeVar

from .models import VisualBrief
from .provider import Provider, ProviderStatus

_REGISTRY: dict[str, Provider] = {}
_loaded = False

T = TypeVar("T")


def register(cls: type[T]) -> type[T]:
    """Decorator que registra uma classe de provedor."""
    instance = cls()  # type: ignore[call-arg]
    name = getattr(instance, "name", None)
    if not name:
        raise ValueError(f"{cls.__name__} precisa definir o atributo `name`")
    if name in _REGISTRY:
        raise ValueError(f"provedor duplicado: {name}")
    _REGISTRY[name] = instance  # type: ignore[assignment]
    return cls


def _load_builtin_providers() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    import videosearcher.providers as pkg

    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name.startswith("_"):
            continue
        importlib.import_module(f"{pkg.__name__}.{mod.name}")


def all_providers() -> dict[str, Provider]:
    _load_builtin_providers()
    return dict(_REGISTRY)


def get_provider(name: str) -> Provider:
    providers = all_providers()
    if name not in providers:
        raise KeyError(f"provedor desconhecido: {name}. Disponíveis: {sorted(providers)}")
    return providers[name]


def providers_for(
    brief: VisualBrief,
    *,
    allowed: Iterable[str] | None = None,
    require_api_key: bool = True,
) -> list[Provider]:
    """Provedores compatíveis com o brief, na ordem de `allowed` quando informada.

    `allowed` normalmente vem de `channel.provedores.prioridade`, então a ordem
    de prioridade do canal é respeitada.
    """
    providers = all_providers()
    names = list(allowed) if allowed else sorted(providers)

    selected: list[Provider] = []
    for name in names:
        provider = providers.get(name)
        if provider is None:
            continue
        if not provider.accepts(brief):
            continue
        if require_api_key and not _api_key_present(provider):
            continue
        selected.append(provider)
    return selected


def _api_key_present(provider: Provider) -> bool:
    caps = provider.capabilities
    if not caps.requires_api_key:
        return True
    if not caps.api_key_env:
        return True
    return bool(os.getenv(caps.api_key_env, "").strip())


def _is_implemented(provider: Provider, method: str) -> bool:
    """Detecta se o provedor sobrescreveu o método ou herdou o stub da base."""
    from .provider import BaseProvider

    own = getattr(type(provider), method, None)
    base = getattr(BaseProvider, method, None)
    if own is None:
        return False
    return inspect.unwrap(own) is not inspect.unwrap(base) if base else True


def status() -> list[ProviderStatus]:
    """Estado de todos os provedores registrados, para o comando `providers`."""
    out: list[ProviderStatus] = []
    for name, provider in sorted(all_providers().items()):
        missing = [
            m for m in ("search", "normalize", "download") if not _is_implemented(provider, m)
        ]
        out.append(
            ProviderStatus(
                name=name,
                implemented=not missing,
                api_key_present=_api_key_present(provider),
                capabilities=provider.capabilities,
                missing=missing,
            )
        )
    return out
