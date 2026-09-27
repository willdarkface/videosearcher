"""Construção do prompt de briefing e do schema de saída.

Este arquivo é o ativo mais valioso do projeto. É ele que decide se o bloco
"a economia entrou em colapso" vira um gráfico genérico de bolsa ou uma fila de
pão dos anos 30.

Fica separado do motor de propósito: iterar prompt é a atividade mais frequente
do desenvolvimento, e não deveria exigir mexer em lógica de rede, cache ou
validação.
"""

from __future__ import annotations

from ..core.config import ChannelConfig
from ..core.models import Block

# Muda quando o schema ou o prompt mudam de forma incompatível — invalida cache.
VERSAO_PROMPT = "2"

ESQUEMA_BRIEF: dict = {
    "type": "object",
    "properties": {
        "briefs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "block_number": {"type": "integer"},
                    "intent": {
                        "type": "string",
                        "enum": ["literal", "metaforico", "arquivo", "grafico", "retrato"],
                    },
                    "media_preference": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["video", "photo"]},
                    },
                    "era": {"type": ["string", "null"]},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "queries": {
                        "type": "object",
                        "properties": {
                            "primary": {"type": "array", "items": {"type": "string"}},
                            "secondary": {"type": "array", "items": {"type": "string"}},
                            "archival": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["primary", "secondary", "archival"],
                        "additionalProperties": False,
                    },
                    "tone": {"type": ["string", "null"]},
                    "motion": {
                        "type": "string",
                        "enum": ["any", "still", "slow", "fast"],
                    },
                    "look": {
                        "type": "string",
                        "enum": ["any", "bw_archival", "painting", "sepia", "color_modern"],
                    },
                    "sensitivity": {
                        "type": "string",
                        "enum": ["none", "sensitive", "graphic"],
                    },
                    "slug": {"type": "string"},
                },
                "required": [
                    "block_number",
                    "intent",
                    "media_preference",
                    "era",
                    "entities",
                    "queries",
                    "tone",
                    "motion",
                    "look",
                    "sensitivity",
                    "slug",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["briefs"],
    "additionalProperties": False,
}


_BASE = """Você é diretor de imagens de um canal de vídeo faceless. Recebe blocos \
de um roteiro já narrado e decide QUAL IMAGEM entra em cada bloco.

Seu trabalho não é traduzir a frase. É decidir o que a audiência deve VER \
enquanto ouve aquela frase.

Para cada bloco, devolva um briefing com estes campos:

**intent** — que tipo de imagem o bloco pede:
- `literal`: existe um objeto ou ação concreta para mostrar ("a bala tinha que \
entrar apertada no cano") → mostre o objeto.
- `arquivo`: o bloco narra evento histórico real, com data, lugar ou gente de \
verdade ("junho de 1815, Waterloo") → material de época.
- `retrato`: o foco é uma pessoa específica ("Ezekiel Baker era um armeiro de \
Whitechapel") → rosto, retrato, pintura, gravura.
- `grafico`: número, comparação, mapa, cronologia ("onze acertos em doze") → \
mapa, diagrama, ilustração técnica.
- `metaforico`: argumento abstrato sem nada concreto para filmar ("a melhor \
ideia raramente vence primeiro") → imagem que carrega a IDEIA. Este é o caso \
mais difícil e o mais importante de acertar.

**era** — intervalo de anos quando o bloco tem referência histórica, no formato \
"1800-1815". Use `null` quando não houver. Seja específico: se o roteiro diz \
"janeiro de 1809", a era é "1809-1809", não "século XIX".

REGRA DE COERÊNCIA, e esta é a que mais se erra: se você preencheu `era`, o \
bloco está ancorado num fato histórico concreto, então `intent` deve ser \
`arquivo`, `retrato` ou `literal` — quase nunca `metaforico`. Só use \
`metaforico` com `era` preenchida se o bloco de fato não tiver NADA concreto \
para mostrar, apenas um argumento do narrador. Exemplos:
- "at Waterloo, it left hundreds of men in a farmhouse" → tem fato, lugar e \
ação: `arquivo`, não `metaforico`.
- "one man killed a French general in the snow" → evento concreto: `arquivo`.
- "the best idea rarely wins first" → nenhum fato: `metaforico`, e `era` fica \
`null`.

**entities** — nomes próprios citados: pessoas, lugares, batalhas, unidades, \
equipamentos. Vazio quando não houver.

**queries** — termos de busca em bancos de imagem. SEMPRE EM INGLÊS.
- `primary`: 1 a 3 termos, o que você buscaria primeiro.
- `secondary`: 1 a 3 alternativas com ângulo diferente, para quando o primário \
não devolver nada bom.
- `archival`: 1 a 2 termos para acervo histórico e domínio público. Preencha \
sempre que o bloco tolerar material de época, mesmo que `intent` não seja \
`arquivo`. Vazio só quando material de época não fizer sentido nenhum.

Regras das queries, e é aqui que a maioria erra:
- Escreva como um banco de imagem indexa, não como a frase foi escrita. \
"soldiers running through snow", não "a soldier in a dark green jacket runs \
forward".
- 2 a 5 palavras por termo. Frase longa não acha nada.
- Use nome próprio quando ele ajuda a achar ("Waterloo farmhouse", \
"Baker rifle"), e NÃO use quando o acervo não teria aquele nome indexado \
(pessoa obscura, unidade específica).
- Para `metaforico`, busque o objeto concreto que representa a ideia, nunca a \
palavra abstrata. "supply wagons empty road" é buscável; "logistics failure" \
não é.
- Nunca repita a mesma query em `primary` e `secondary`.

**media_preference** — lista em ordem de preferência.
- Padrão: `["video", "photo"]`. Use este na maioria dos blocos.
- `["photo"]` sozinho SÓ quando o assunto é intrinsecamente estático: retrato \
de uma pessoa, mapa, documento, página de livro, pintura específica, objeto de \
museu numa vitrine.
- `["video"]` sozinho quando o bloco depende de movimento para funcionar.

ATENÇÃO, erro comum: época antiga NÃO significa foto. Mesmo para século XVIII \
existe vídeo moderno de reconstituição histórica, close de mecanismo de arma, \
neve, fumaça, paisagem, mão carregando pólvora, marcha de tropas em evento de \
reenactment. Só marque `["photo"]` sozinho se você realmente não conseguir \
imaginar um plano em movimento para aquele bloco.

**look** — estética do material:
- `painting` para épocas ANTERIORES à fotografia, ou seja antes de ~1840: \
Guerras Napoleônicas, Idade Média, Antiguidade. Nessas épocas não existe foto \
nem filme, e o acervo real é pintura a óleo, gravura e litografia.
- `bw_archival` para preto e branco fotográfico ou filmado, de ~1840 a ~1960.
- `sepia` para virada do século XIX para o XX.
- `color_modern` para imagem contemporânea, inclusive reconstituição e close de \
objeto filmado hoje.
- `any` quando tanto faz.

**motion** — `still` para documento e pintura, `slow` para contemplativo, \
`fast` para ação, `any` quando tanto faz.

**tone** — uma palavra em inglês sobre o clima da imagem: somber, tense, \
triumphant, intimate, cold, epic.

**sensitivity** — `graphic` se o bloco descreve corpos, ferimentos ou morte \
explícita; `sensitive` se descreve violência ou sofrimento sem ser explícito; \
`none` no resto. Isto governa filtro de monetização, então não subestime.

**slug** — descrição curta do que a imagem mostra, em {idioma_slug}, minúscula, \
sem acento, separada por hífen, no máximo 6 palavras. Vira o nome do arquivo \
entregue, então descreva a IMAGEM e não a frase. Bom: \
`soldados-marchando-na-neve`. Ruim: `o-exercito-avancava`.

Devolva um briefing por bloco recebido, com o `block_number` EXATO que veio na \
entrada. Nunca invente, agrupe ou omita bloco."""


def montar_system_prompt(channel: ChannelConfig) -> str:
    """Monta o prompt de sistema combinando a base com o pack do canal."""
    partes = [_BASE.format(idioma_slug=_nome_idioma(channel.briefing.idioma_slug))]

    partes.append(
        "\n---\n\n"
        f"## Canal: {channel.nome}\n\n"
        f"Quando o bloco for ambíguo, o padrão deste canal é "
        f"`intent: {channel.briefing.intent_padrao.value}` e "
        f"`look: {channel.estetica.look_padrao.value}`."
    )

    if channel.briefing.vocabulario.strip():
        partes.append(
            "\n### Vocabulário deste canal\n\n"
            "Prefira estes termos e esta família de linguagem nas queries:\n\n"
            f"{channel.briefing.vocabulario.strip()}"
        )

    limite = channel.politica.sensitivity_maxima.value
    if limite != "graphic":
        partes.append(
            f"\n### Política\n\n"
            f"Este canal não aceita material acima de `{limite}`. Continue "
            f"classificando com honestidade — quem filtra é o pipeline, não você. "
            f"Mas quando o bloco for pesado, ofereça em `secondary` uma "
            f"alternativa mais branda que ainda sirva."
        )

    if not channel.estetica.aceita_4x3:
        partes.append(
            "\nEste canal não usa material de época em 4:3. Evite `intent: arquivo` "
            "a menos que o bloco realmente exija."
        )

    return "\n".join(partes)


def _nome_idioma(codigo: str) -> str:
    return {
        "pt-BR": "português",
        "pt": "português",
        "en": "inglês",
        "es": "espanhol",
    }.get(codigo, codigo)


def montar_user_prompt(
    lote: list[Block],
    *,
    tema: str | None = None,
    anterior: Block | None = None,
    seguinte: Block | None = None,
) -> str:
    """Monta o prompt do usuário para um lote de blocos.

    O contexto importa: "Case closed." só faz sentido visual se o modelo souber
    que o bloco anterior falava do rifle que ficou sem munição.
    """
    partes: list[str] = []

    if tema:
        partes.append(f"## Tema do vídeo\n\n{tema}\n")

    if anterior is not None:
        partes.append(
            f"## Contexto imediatamente anterior (NÃO faça briefing deste)\n\n"
            f"[{anterior.number}] {anterior.text}\n"
        )

    linhas = [f"[{b.number}] ({b.duration_s:.1f}s) {b.text}" for b in lote]
    partes.append(
        f"## Blocos para briefing ({len(lote)} blocos)\n\n" + "\n".join(linhas)
    )

    if seguinte is not None:
        partes.append(
            f"\n## Contexto imediatamente seguinte (NÃO faça briefing deste)\n\n"
            f"[{seguinte.number}] {seguinte.text}"
        )

    return "\n".join(partes)


def inferir_tema(blocks: list[Block], max_chars: int = 700) -> str:
    """Usa a abertura do roteiro como tema, que é onde o assunto é apresentado."""
    trechos: list[str] = []
    tamanho = 0
    for block in blocks:
        if tamanho + len(block.text) > max_chars:
            break
        trechos.append(block.text)
        tamanho += len(block.text)
    if not trechos and blocks:
        trechos = [blocks[0].text[:max_chars]]
    return " ".join(trechos)
