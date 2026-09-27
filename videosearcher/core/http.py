"""Cliente HTTP compartilhado pelos provedores de mídia."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

USER_AGENT = "videosearcher/0.1 (+https://github.com/willdarkface/videosearcher)"


class HttpError(RuntimeError):
    pass


class RateLimited(HttpError):
    pass


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    tentativas: int = 3,
) -> Any:
    """GET com retry e backoff. Levanta RateLimited em 429 para o roteador
    poder degradar para outro provedor em vez de insistir."""
    cabecalhos = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    cabecalhos.update(headers or {})

    ultimo_erro = ""
    for tentativa in range(tentativas):
        try:
            r = httpx.get(url, params=params, headers=cabecalhos, timeout=timeout,
                          follow_redirects=True)
        except httpx.HTTPError as exc:
            ultimo_erro = f"rede: {exc}"
            time.sleep(1.5 * (tentativa + 1))
            continue

        if r.status_code == 429:
            raise RateLimited(f"429 em {url}")
        if r.status_code >= 500:
            ultimo_erro = f"HTTP {r.status_code}"
            time.sleep(1.5 * (tentativa + 1))
            continue
        if r.status_code >= 400:
            raise HttpError(f"HTTP {r.status_code} em {url}: {r.text[:200]}")

        try:
            return r.json()
        except ValueError as exc:
            raise HttpError(f"resposta não-JSON de {url}: {exc}") from exc

    raise HttpError(f"falhou após {tentativas} tentativas em {url}: {ultimo_erro}")


def baixar(
    url: str,
    destino: Path,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 120.0,
    max_bytes: int | None = None,
) -> Path:
    """Baixa para arquivo temporário e só move ao final — evita arquivo parcial
    com nome definitivo se a conexão cair."""
    cabecalhos = {"User-Agent": USER_AGENT}
    cabecalhos.update(headers or {})
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(destino.suffix + ".part")

    def _escrever(resposta: httpx.Response) -> None:
        escritos = 0
        with parcial.open("wb") as f:
            for pedaco in resposta.iter_bytes(chunk_size=65536):
                f.write(pedaco)
                escritos += len(pedaco)
                if max_bytes and escritos > max_bytes:
                    _estourou(max_bytes)

    try:
        with httpx.stream("GET", url, headers=cabecalhos, timeout=timeout,
                          follow_redirects=True) as r:
            if r.status_code >= 400:
                _falhou(r.status_code, url)
            _escrever(r)
    except Exception:
        parcial.unlink(missing_ok=True)
        raise

    parcial.replace(destino)
    return destino


def _falhou(status: int, url: str) -> None:
    raise HttpError(f"HTTP {status} ao baixar {url}")


def _estourou(max_bytes: int) -> None:
    raise HttpError(f"arquivo maior que o limite de {max_bytes / 1e6:.0f} MB")
