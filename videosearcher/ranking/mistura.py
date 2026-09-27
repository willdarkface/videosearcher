"""Distribuição da proporção vídeo/imagem na entrega.

Por bloco, a pergunta "vídeo ou imagem?" tem resposta local. Mas a mistura do
vídeo final é global: querer 20% de vídeo e 80% de imagem não é uma regra que
cada bloco possa aplicar sozinho.

Então o fluxo é em dois tempos. Primeiro cada bloco descobre o melhor vídeo E a
melhor imagem que existem para ele. Depois o orçamento de vídeo é distribuído
entre os blocos que mais ganham com movimento — bloco de ação leva vídeo, bloco
de documento leva imagem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..core.config import MidiaConfig
from ..core.models import MediaType, VisualBrief
from .rules import Selecao


class TemSelecao(Protocol):
    """Qualquer objeto com brief e seleção serve — evita acoplar ao pipeline."""

    brief: VisualBrief
    selecao: Selecao


@dataclass
class ResultadoMistura:
    alvo_video: int = 0
    com_video: int = 0
    com_imagem: int = 0
    forcados_para_video: int = 0
    forcados_para_imagem: int = 0
    sem_escolha: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def proporcao_atingida(self) -> float:
        total = self.com_video + self.com_imagem
        return self.com_video / total if total else 0.0


def _prioridade_para_video(item: TemSelecao, midia: MidiaConfig) -> float:
    """Quanto este bloco ganha em receber vídeo em vez de imagem."""
    par = item.selecao.melhor_video
    if par is None:
        return -1.0
    _, veredito = par

    peso = midia.peso_motion_video.get(item.brief.motion.value, 1.0)

    # Brief que pediu só vídeo tem prioridade real: foi decisão do briefing.
    if item.brief.media_preference == [MediaType.VIDEO]:
        peso *= 2.0
    elif item.brief.media_preference and item.brief.media_preference[0] is MediaType.VIDEO:
        peso *= 1.2

    return veredito.bonus * peso


def aplicar_proporcao(itens: list[TemSelecao], midia: MidiaConfig) -> ResultadoMistura:
    """Ajusta as escolhas para aproximar a proporção alvo de vídeo.

    Bloco que só tem um tipo disponível mantém o que tem: a proporção é um alvo,
    não uma promessa. Cobertura vale mais que estética de mistura.
    """
    resultado = ResultadoMistura()
    com_resultado = [i for i in itens if i.selecao.escolhido is not None]
    resultado.sem_escolha = len(itens) - len(com_resultado)

    if not com_resultado:
        return resultado

    if midia.proporcao_video is None:
        # Alvo desligado: mantém a ordem do ranqueamento (vídeo sempre primeiro).
        for item in com_resultado:
            tipo = item.selecao.escolhido[0].media_type
            if tipo is MediaType.VIDEO:
                resultado.com_video += 1
            else:
                resultado.com_imagem += 1
        resultado.alvo_video = resultado.com_video
        return resultado

    proporcao = min(1.0, max(0.0, midia.proporcao_video))
    resultado.alvo_video = round(len(com_resultado) * proporcao)

    so_video: list[TemSelecao] = []
    so_foto: list[TemSelecao] = []
    ambos: list[TemSelecao] = []
    for item in com_resultado:
        tem_video = item.selecao.melhor_video is not None
        tem_foto = item.selecao.melhor_foto is not None
        if tem_video and tem_foto:
            ambos.append(item)
        elif tem_video:
            so_video.append(item)
        else:
            so_foto.append(item)

    # Quem não tem escolha já consome (ou não) o orçamento.
    for item in so_video:
        item.selecao.preferir(MediaType.VIDEO)
    for item in so_foto:
        item.selecao.preferir(MediaType.PHOTO)

    vagas = resultado.alvo_video - len(so_video)

    if vagas <= 0:
        if vagas < 0:
            resultado.avisos.append(
                f"{len(so_video)} blocos só têm vídeo disponível, acima do alvo de "
                f"{resultado.alvo_video} — a proporção de vídeo ficará mais alta"
            )
        for item in ambos:
            item.selecao.preferir(MediaType.PHOTO)
            resultado.forcados_para_imagem += 1
    else:
        ordenados = sorted(ambos, key=lambda i: -_prioridade_para_video(i, midia))
        for item in ordenados[:vagas]:
            item.selecao.preferir(MediaType.VIDEO)
            resultado.forcados_para_video += 1
        for item in ordenados[vagas:]:
            item.selecao.preferir(MediaType.PHOTO)
            resultado.forcados_para_imagem += 1

        if len(ambos) < vagas:
            resultado.avisos.append(
                f"faltou material de vídeo para o alvo: {resultado.alvo_video} "
                f"pedidos, {len(so_video) + len(ambos)} possíveis"
            )

    for item in com_resultado:
        if item.selecao.escolhido[0].media_type is MediaType.VIDEO:
            resultado.com_video += 1
        else:
            resultado.com_imagem += 1

    return resultado
