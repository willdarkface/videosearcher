"""Regras duras de compatibilidade entre asset e bloco.

Estas são as regras que eliminam candidato antes de qualquer cálculo de
relevância. São baratas, determinísticas e auditáveis: todo veredito carrega o
motivo em texto, que vai para o `_manifest.csv` da entrega.

A regra central é a cobertura de duração:

  - **Vídeo precisa cobrir o bloco.** Duração maior ou igual à do bloco.
    Vídeo mais curto é rejeitado, porque as alternativas são esticar (degrada)
    ou repetir em loop (aparece).
  - **Foto não tem restrição de duração.** Com pan/zoom (Ken Burns) ela cobre
    qualquer intervalo. Por isso é o fallback universal: quando nenhum vídeo é
    longo o bastante para o bloco, a foto entra.
  - **Foto quer 16:9.** Dentro da tolerância, entra direto; fora dela, entra por
    crop central, desde que a resolução resultante ainda atenda o canal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.config import MidiaConfig
from ..core.models import Asset, Block, MediaType


@dataclass
class CropBox:
    """Recorte central para levar a imagem ao aspecto alvo."""

    width: int
    height: int
    x: int
    y: int

    @property
    def ffmpeg(self) -> str:
        return f"crop={self.width}:{self.height}:{self.x}:{self.y}"


@dataclass
class Veredito:
    """Resultado da avaliação de um candidato para um bloco."""

    aceito: bool
    motivo: str
    ajustes: list[str] = field(default_factory=list)
    bonus: float = 0.0
    crop: CropBox | None = None

    def __bool__(self) -> bool:  # pragma: no cover - conveniência
        return self.aceito


# ---------------------------------------------------------------------------
# Vídeo
# ---------------------------------------------------------------------------


def cobertura_video(asset: Asset, block: Block, midia: MidiaConfig) -> Veredito:
    """O vídeo é longo o bastante para cobrir o bloco?"""
    alvo = block.duration_s

    if asset.duration_s is None:
        return Veredito(False, "duração do vídeo desconhecida — não é possível garantir cobertura")

    if not midia.video_deve_cobrir_bloco:
        return Veredito(True, f"cobertura não exigida pelo canal ({asset.duration_s:.1f}s)")

    minimo = alvo - midia.tolerancia_cobertura_s
    if asset.duration_s < minimo:
        falta = alvo - asset.duration_s
        return Veredito(
            False,
            f"vídeo curto: {asset.duration_s:.1f}s para bloco de {alvo:.1f}s "
            f"(faltam {falta:.1f}s)",
        )

    folga = asset.duration_s - alvo
    ajustes = ["trim"] if folga > 0.05 else []
    return Veredito(
        True,
        f"cobre o bloco: {asset.duration_s:.1f}s ≥ {alvo:.1f}s (folga {folga:.1f}s)",
        ajustes=ajustes,
        bonus=_bonus_folga(folga, alvo, midia.folga_relativa_maxima),
    )


def _bonus_folga(folga: float, alvo: float, folga_maxima: float) -> float:
    """Pontua o encaixe de duração: 1.0 no encaixe justo, decaindo com a folga.

    Clipe muito mais longo que o bloco não é errado — só é mais arbitrário,
    porque alguém precisa escolher qual trecho usar. Então perde ponto, sem ser
    eliminado.
    """
    if alvo <= 0:
        return 1.0
    folga_relativa = max(0.0, folga) / alvo
    if folga_maxima <= 0:
        return 1.0
    return max(0.2, min(1.0, 1.0 - folga_relativa / folga_maxima))


# ---------------------------------------------------------------------------
# Foto
# ---------------------------------------------------------------------------


def calcular_crop(width: int, height: int, aspecto_alvo: float) -> CropBox:
    """Recorte central que leva a imagem ao aspecto alvo, sem escalar."""
    atual = width / height
    if atual > aspecto_alvo:
        novo_w = round(height * aspecto_alvo)
        novo_h = height
    else:
        novo_w = width
        novo_h = round(width / aspecto_alvo)
    novo_w = min(novo_w, width)
    novo_h = min(novo_h, height)
    return CropBox(width=novo_w, height=novo_h, x=(width - novo_w) // 2, y=(height - novo_h) // 2)


def aspecto_foto(asset: Asset, midia: MidiaConfig, resolucao_minima: int) -> Veredito:
    """A foto atende o aspecto alvo (16:9 por padrão), direto ou por crop?"""
    if asset.width <= 0 or asset.height <= 0:
        return Veredito(False, "dimensões da imagem desconhecidas")

    alvo = midia.aspecto_alvo
    atual = asset.width / asset.height
    desvio = abs(atual - alvo) / alvo

    # Foto sempre recebe movimento: parada no meio de narração parece erro.
    base_ajustes = ["kenburns"]

    if desvio <= midia.imagem_tolerancia_aspecto:
        if asset.height < resolucao_minima:
            return Veredito(
                False,
                f"resolução baixa: {asset.width}x{asset.height}, "
                f"canal exige altura ≥ {resolucao_minima}",
            )
        return Veredito(
            True,
            f"aspecto {atual:.2f} dentro da tolerância de {midia.imagem_aspecto}",
            ajustes=base_ajustes,
            bonus=1.0,
        )

    if not midia.permitir_crop_para_aspecto:
        return Veredito(
            False,
            f"aspecto {atual:.2f} fora de {midia.imagem_aspecto} e crop desabilitado no canal",
        )

    crop = calcular_crop(asset.width, asset.height, alvo)
    if crop.height < resolucao_minima:
        return Veredito(
            False,
            f"crop para {midia.imagem_aspecto} daria {crop.width}x{crop.height}, "
            f"abaixo do mínimo de {resolucao_minima}",
        )

    # Quanto mais material se perde no crop, menor a nota.
    area_mantida = (crop.width * crop.height) / (asset.width * asset.height)
    return Veredito(
        True,
        f"aspecto {atual:.2f} ajustado para {midia.imagem_aspecto} por crop central "
        f"({crop.width}x{crop.height}, mantém {area_mantida:.0%})",
        ajustes=[*base_ajustes, "crop"],
        bonus=max(0.3, area_mantida),
        crop=crop,
    )


# ---------------------------------------------------------------------------
# Avaliação unificada e seleção
# ---------------------------------------------------------------------------


def avaliar(asset: Asset, block: Block, midia: MidiaConfig, resolucao_minima: int) -> Veredito:
    """Aplica a regra correta conforme o tipo de mídia."""
    if asset.media_type is MediaType.VIDEO:
        veredito = cobertura_video(asset, block, midia)
        if veredito.aceito and asset.height and asset.height < resolucao_minima:
            return Veredito(
                False,
                f"resolução baixa: {asset.width}x{asset.height}, "
                f"canal exige altura ≥ {resolucao_minima}",
            )
        return veredito
    return aspecto_foto(asset, midia, resolucao_minima)


@dataclass
class Selecao:
    """Candidatos aprovados em ordem de preferência, e os motivos das recusas."""

    aprovados: list[tuple[Asset, Veredito]] = field(default_factory=list)
    recusados: list[tuple[Asset, Veredito]] = field(default_factory=list)

    @property
    def escolhido(self) -> tuple[Asset, Veredito] | None:
        return self.aprovados[0] if self.aprovados else None

    @property
    def alternativas(self) -> list[tuple[Asset, Veredito]]:
        return self.aprovados[1:]

    @property
    def usou_fallback_de_imagem(self) -> bool:
        escolhido = self.escolhido
        return escolhido is not None and escolhido[0].media_type is MediaType.PHOTO


def selecionar(
    block: Block,
    candidatos: list[Asset],
    midia: MidiaConfig,
    resolucao_minima: int,
    *,
    relevancia: dict[str, float] | None = None,
) -> Selecao:
    """Filtra e ordena candidatos para um bloco.

    Vídeo que cobre o bloco vem sempre antes de foto — é o comportamento pedido:
    só cai para imagem quando nenhum vídeo é longo o bastante. Dentro de cada
    grupo, ordena por relevância (quando informada) combinada com o bônus da
    regra.
    """
    relevancia = relevancia or {}
    selecao = Selecao()

    for asset in candidatos:
        veredito = avaliar(asset, block, midia, resolucao_minima)
        if veredito.aceito:
            selecao.aprovados.append((asset, veredito))
        else:
            selecao.recusados.append((asset, veredito))

    if not midia.fallback_para_imagem:
        selecao.aprovados = [
            par for par in selecao.aprovados if par[0].media_type is MediaType.VIDEO
        ]

    def chave(par: tuple[Asset, Veredito]) -> tuple[int, float]:
        asset, veredito = par
        prioridade_tipo = 0 if asset.media_type is MediaType.VIDEO else 1
        nota = relevancia.get(asset.uid, 1.0) * veredito.bonus
        return (prioridade_tipo, -nota)

    selecao.aprovados.sort(key=chave)
    return selecao
