"""Classificação de licença — a camada que impede copyright strike.

Existe porque a suposição ingênua custa caro. O Internet Archive aceita upload
de qualquer usuário, e a coleção `opensource_movies` NÃO é garantia de licença:
é só onde uploads da comunidade caem. Itens como "The Mutiny of the HMS Bounty"
e "Frankenstein" estão lá, sem nenhum campo de licença, enviados de endereços
de e-mail pessoais. Tratar isso como domínio público é convite a strike num
canal monetizado.

A regra é simples e conservadora: licença só é considerada livre quando o
metadado prova. Sem prova, o asset é marcado `unknown` e o canal decide se
aceita — o padrão é não aceitar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Coleções do IA cujo conteúdo é domínio público por origem institucional:
# obra do governo dos EUA, acervos doados ou já em domínio público.
COLECOES_CONFIAVEIS = {
    "usgovfilms",
    "fedflix",
    "prelinger",
    "nasa",
    "universal_newsreels",
    "library_of_congress",
    "nationalarchives",
    "smithsonian",
    "sec_gov",
    "nist",
}

# Coleções que NÃO dizem nada sobre licença, apesar do nome sugerir o contrário.
COLECOES_SEM_GARANTIA = {"opensource_movies", "community", "communityvideo", "opensource"}

_LIVRES_SEM_ATRIBUICAO = ("publicdomain/zero", "publicdomain/mark", "cc0")
_LIVRES_COM_ATRIBUICAO = ("licenses/by/", "licenses/by-sa/")
_NAO_COMERCIAIS = ("licenses/by-nc", "licenses/by-nd", "-nc-", "-nd-")


@dataclass(frozen=True)
class Licenca:
    id: str
    url: str | None
    atribuicao: bool
    verificada: bool
    motivo: str = ""

    @property
    def usavel_comercialmente(self) -> bool:
        return self.verificada and self.id not in {"unknown", "nao-comercial"}


DESCONHECIDA = Licenca(
    id="unknown",
    url=None,
    atribuicao=True,
    verificada=False,
    motivo="item sem campo de licença; coleção não garante nada",
)


def classificar_licenca(metadata: dict[str, Any]) -> Licenca:
    """Deduz a licença a partir do metadado do item, sem chutar."""
    url = str(metadata.get("licenseurl") or "").strip().lower()
    direitos = str(metadata.get("rights") or "").strip()
    colecoes = _lista(metadata.get("collection"))

    if url:
        if any(marca in url for marca in _NAO_COMERCIAIS):
            return Licenca(
                id="nao-comercial",
                url=url,
                atribuicao=True,
                verificada=True,
                motivo="licença Creative Commons NC ou ND: proíbe uso comercial",
            )
        if any(marca in url for marca in _LIVRES_SEM_ATRIBUICAO):
            return Licenca(
                id="public-domain",
                url=url,
                atribuicao=False,
                verificada=True,
                motivo="licenseurl declara domínio público ou CC0",
            )
        if any(marca in url for marca in _LIVRES_COM_ATRIBUICAO):
            sa = "-sa" in url
            return Licenca(
                id="cc-by-sa" if sa else "cc-by",
                url=url,
                atribuicao=True,
                verificada=True,
                motivo="licenseurl declara CC BY" + (" SA" if sa else ""),
            )

    confiaveis = [c for c in colecoes if c.lower() in COLECOES_CONFIAVEIS]
    if confiaveis:
        return Licenca(
            id="public-domain",
            url=None,
            atribuicao=False,
            verificada=True,
            motivo=f"coleção institucional de domínio público: {confiaveis[0]}",
        )

    if direitos:
        return Licenca(
            id="declarado-nao-verificado",
            url=None,
            atribuicao=True,
            verificada=False,
            motivo=f"campo rights preenchido mas não interpretável: {direitos[:80]}",
        )

    sem_garantia = [c for c in colecoes if c.lower() in COLECOES_SEM_GARANTIA]
    if sem_garantia:
        return Licenca(
            id="unknown",
            url=None,
            atribuicao=True,
            verificada=False,
            motivo=(
                f"coleção '{sem_garantia[0]}' é upload de comunidade e não garante "
                f"licença; item sem licenseurl nem rights"
            ),
        )

    return DESCONHECIDA


def _lista(valor: Any) -> list[str]:
    if isinstance(valor, str):
        return [valor]
    if isinstance(valor, list):
        return [str(v) for v in valor]
    return []
