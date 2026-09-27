"""Detecção de cena e corte de vídeo em pedaços utilizáveis.

Decisão que vale explicar: a detecção de cena usa o filtro `select='gt(scene,N)'`
do próprio ffmpeg, não o PySceneDetect. O PySceneDetect arrasta o OpenCV, que
soma ~200 MB na imagem e RAM equivalente por worker. O filtro do ffmpeg entrega
o mesmo sinal lendo o vídeo uma vez, e o binário já está ali para cortar.

A regra central do corte: **um segmento nunca cruza fronteira de cena.** É isso
que evita o clipe que troca de assunto no meio, que é inútil por mais bonito que
seja.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# O showinfo imprime uma linha por quadro selecionado; é daí que saem os cortes.
_PTS = re.compile(r"pts_time:([0-9.]+)")


class CorteError(RuntimeError):
    pass


@dataclass
class Sonda:
    """O que o ffprobe conta sobre o arquivo."""

    duracao_s: float
    largura: int
    altura: int
    fps: float

    @property
    def aspecto(self) -> float:
        return self.largura / self.altura if self.altura else 0.0


@dataclass
class Segmento:
    indice: int
    cena_id: int
    inicio_s: float
    fim_s: float

    @property
    def duracao_s(self) -> float:
        return self.fim_s - self.inicio_s


def _executar(args: list[str], timeout: float = 1800.0) -> str:
    proc = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
    )
    if proc.returncode != 0:
        raise CorteError(
            f"comando falhou ({proc.returncode}): {' '.join(args[:3])}… "
            f"{proc.stderr[-400:]}"
        )
    return proc.stdout + proc.stderr


def sondar(arquivo: Path) -> Sonda:
    """Lê duração e dimensões. Usa o ffmpeg em modo de análise porque o
    ffprobe não vem no pacote do binário estático."""
    saida = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(arquivo)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    ).stderr

    duracao = 0.0
    if m := re.search(r"Duration: (\d+):(\d+):([\d.]+)", saida):
        h, mi, s = m.groups()
        duracao = int(h) * 3600 + int(mi) * 60 + float(s)

    largura = altura = 0
    if m := re.search(r"(\d{2,5})x(\d{2,5})", saida):
        largura, altura = int(m.group(1)), int(m.group(2))

    fps = 0.0
    if m := re.search(r"([\d.]+) fps", saida):
        fps = float(m.group(1))

    if duracao <= 0 or largura <= 0:
        raise CorteError(f"não foi possível sondar {arquivo.name}: {saida[-300:]}")

    return Sonda(duracao_s=duracao, largura=largura, altura=altura, fps=fps)


def detectar_cenas(arquivo: Path, *, limiar: float = 0.30) -> list[float]:
    """Devolve os instantes de troca de cena, em segundos.

    O limiar 0.30 é conservador: pega corte seco e transição marcada, e ignora
    variação de luz e movimento de câmera. Limiar baixo demais fragmenta o vídeo
    em pedaços de meio segundo.
    """
    saida = _executar([
        FFMPEG, "-hide_banner", "-nostats",
        "-i", str(arquivo),
        "-filter:v", f"select='gt(scene,{limiar})',showinfo",
        "-an", "-f", "null", "-",
    ])
    instantes = sorted({float(v) for v in _PTS.findall(saida)})
    return instantes


def planejar_segmentos(
    sonda: Sonda,
    cenas: list[float],
    *,
    duracao_alvo: float = 6.0,
    duracao_minima: float = 3.0,
    margem_s: float = 0.25,
) -> list[Segmento]:
    """Fatia o vídeo em segmentos de `duracao_alvo`, respeitando as cenas.

    Cada cena é preenchida com segmentos inteiros. A sobra da cena vira um
    segmento só se alcançar `duracao_minima` — resto de 0,8s não serve para
    nada e só inflaria o catálogo.

    A `margem_s` descarta o primeiro e o último instante de cada cena, onde
    costuma haver fade, blur de movimento e frame de transição.
    """
    fronteiras = [0.0, *[c for c in cenas if 0 < c < sonda.duracao_s], sonda.duracao_s]
    fronteiras = sorted(set(fronteiras))

    segmentos: list[Segmento] = []
    for cena_id, (abre, fecha) in enumerate(pairwise(fronteiras)):
        inicio = abre + margem_s
        fim = fecha - margem_s
        if fim - inicio < duracao_minima:
            continue

        cursor = inicio
        while fim - cursor >= duracao_minima:
            termino = min(cursor + duracao_alvo, fim)
            if termino - cursor < duracao_minima:
                break
            segmentos.append(
                Segmento(
                    indice=len(segmentos),
                    cena_id=cena_id,
                    inicio_s=round(cursor, 3),
                    fim_s=round(termino, 3),
                )
            )
            cursor = termino

    return segmentos


def cortar(
    origem: Path,
    segmento: Segmento,
    destino: Path,
    *,
    altura_alvo: int = 1080,
    fps_alvo: int = 30,
    folga_s: float = 0.5,
) -> Path:
    """Extrai um segmento, normalizado e sem áudio.

    `-ss` antes do `-i` é seek rápido por keyframe; o `-ss` depois seria exato
    mas decodificaria desde o início do arquivo, o que num filme de 2 horas é
    inviável.

    A `folga_s` existe por um motivo concreto: o seek por keyframe entrega
    menos do que se pede. Medido aqui, 4,98s pedidos viraram 4,73s. Como a
    regra de ranqueamento exige que o clipe cubra o bloco, entregar menos que o
    planejado tornaria o clipe inutilizável justamente na fronteira. Pedir com
    folga e depois **sondar o arquivo real** resolve: quem manda no catálogo é a
    duração medida, nunca a planejada.

    Áudio é descartado: o vídeo final tem narração própria, e áudio de acervo só
    pesa e atrapalha.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    escala = (
        f"scale=-2:'min({altura_alvo},ih)':flags=bicubic,"
        f"pad=ceil(iw/2)*2:ceil(ih/2)*2"
    )
    _executar([
        FFMPEG, "-hide_banner", "-nostats", "-y",
        "-ss", f"{max(0.0, segmento.inicio_s):.3f}",
        "-i", str(origem),
        "-t", f"{segmento.duracao_s + folga_s:.3f}",
        "-an",
        "-vf", escala,
        "-r", str(fps_alvo),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(destino),
    ], timeout=600)

    if not destino.exists() or destino.stat().st_size == 0:
        raise CorteError(f"corte gerou arquivo vazio: {destino.name}")
    return destino


def extrair_keyframe(clipe: Path, destino: Path, *, em_segundos: float | None = None) -> Path:
    """Tira um quadro do meio do clipe — é o que o modelo de visão vai olhar.

    Meio e não começo: o primeiro quadro costuma ser transição.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    instante = em_segundos if em_segundos is not None else sondar(clipe).duracao_s / 2
    _executar([
        FFMPEG, "-hide_banner", "-nostats", "-y",
        "-ss", f"{max(0.0, instante):.3f}",
        "-i", str(clipe),
        "-frames:v", "1",
        "-vf", "scale=-2:'min(720,ih)'",
        "-q:v", "3",
        str(destino),
    ], timeout=120)

    if not destino.exists() or destino.stat().st_size == 0:
        raise CorteError(f"keyframe vazio para {clipe.name}")
    return destino


def metricas_visuais(keyframe: Path) -> dict[str, float]:
    """Mede saturação e brilho no keyframe.

    É isso que define `look=bw_archival` de verdade. Antes o look vinha do
    palpite do LLM sobre o texto do bloco, que não viu imagem nenhuma.
    """
    saida = _executar([
        FFMPEG, "-hide_banner", "-nostats",
        "-i", str(keyframe),
        "-vf", "signalstats,metadata=print:file=-",
        "-f", "null", "-",
    ], timeout=60)

    valores: dict[str, float] = {}
    for linha in saida.splitlines():
        if "lavfi.signalstats." not in linha:
            continue
        chave, _, valor = linha.partition("=")
        nome = chave.strip().split("lavfi.signalstats.")[-1]
        try:
            valores[nome] = float(valor)
        except ValueError:
            continue

    # SATAVG quando disponível; senão deriva do desvio dos canais de cor.
    saturacao = valores.get("SATAVG")
    if saturacao is None:
        u = abs(valores.get("UAVG", 128.0) - 128.0)
        v = abs(valores.get("VAVG", 128.0) - 128.0)
        saturacao = (u + v) / 2

    return {
        "saturacao": round(saturacao, 3),
        "brilho": round(valores.get("YAVG", 0.0), 3),
    }


def classificar_look(saturacao: float) -> str:
    """Converte saturação medida em `look`.

    Limiares calibrados na escala 0–128 do signalstats: material preto e branco
    de verdade fica perto de zero, e sépia tem saturação baixa mas não nula.
    """
    if saturacao < 4.0:
        return "bw_archival"
    if saturacao < 12.0:
        return "sepia"
    return "color_modern"


def dhash(keyframe: Path, tamanho: int = 8) -> str:
    """Hash perceptual por diferença de luminância.

    Existe para impedir que o mesmo clipe entre duas vezes por fontes
    diferentes. Escolhido dHash em vez de pHash de propósito: pHash precisa de
    DCT, logo numpy ou scipy, e isso dobraria o tamanho da imagem do worker por
    um ganho de precisão que não muda a decisão.
    """
    from PIL import Image

    with Image.open(keyframe) as img:
        cinza = img.convert("L").resize((tamanho + 1, tamanho), Image.Resampling.LANCZOS)
        pixels = list(cinza.getdata())

    bits = 0
    posicao = 0
    for linha in range(tamanho):
        base = linha * (tamanho + 1)
        for coluna in range(tamanho):
            if pixels[base + coluna] > pixels[base + coluna + 1]:
                bits |= 1 << posicao
            posicao += 1
    return f"{bits:016x}"


def quadro_chapado(hash_visual: str) -> bool:
    """Detecta quadro sem nenhuma variação de luminância.

    dHash todo zero significa que nenhum pixel é mais claro que o vizinho —
    tela preta, branca, fade ou cartela de cor sólida. Detecção de cena produz
    isso em transição, e são clipes sem conteúdo nenhum.

    Vale a nota: sem esta checagem, todo quadro chapado colidiria no mesmo hash
    e o primeiro entraria no acervo enquanto os demais seriam contados como
    duplicata — escondendo o defeito atrás de uma métrica que parece saudável.
    """
    return not hash_visual or set(hash_visual) <= {"0"}


def resumo_json(sonda: Sonda, cenas: list[float], segmentos: list[Segmento]) -> str:
    return json.dumps(
        {
            "duracao_s": sonda.duracao_s,
            "resolucao": f"{sonda.largura}x{sonda.altura}",
            "fps": sonda.fps,
            "cenas_detectadas": len(cenas),
            "segmentos_planejados": len(segmentos),
        },
        ensure_ascii=False,
    )
