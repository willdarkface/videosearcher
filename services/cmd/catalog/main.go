// catalog — busca no acervo próprio.
//
// Em Go porque é o caminho mais quente do sistema: o dashboard consulta o
// catálogo em toda interação, e o ranqueamento vai bater aqui uma vez por bloco.
//
// Toda consulta passa pela view `clipes_usaveis`, que já exclui licença não
// comprovada. Material de licença duvidosa fica no banco para auditoria e nunca
// chega a ser oferecido.
package main

import (
	"context"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/willdarkface/videosearcher/services/internal/db"
	"github.com/willdarkface/videosearcher/services/internal/httpx"
)

type servidor struct {
	pool *pgxpool.Pool
}

type clipe struct {
	UUID       string   `json:"uuid"`
	Tipo       string   `json:"tipo"`
	Objeto     string   `json:"objeto"`
	Keyframe   *string  `json:"keyframe"`
	DuracaoS   float64  `json:"duracao_s"`
	Largura    int      `json:"largura"`
	Altura     int      `json:"altura"`
	Aspecto    *float64 `json:"aspecto"`
	Provider   string   `json:"provider"`
	LicencaID  string   `json:"licenca_id"`
	Credito    *string  `json:"credito"`
	Look       *string  `json:"look"`
	Caption    *string  `json:"caption"`
	Palavras   []string `json:"palavras"`
	Relevancia float64  `json:"relevancia"`
}

func main() {
	healthcheck := flag.Bool("healthcheck", false, "testa se a porta responde e sai")
	flag.Parse()

	porta := valorOu("PORT", "8081")
	if *healthcheck {
		os.Exit(httpx.Healthcheck(porta))
	}

	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))

	ctx := context.Background()
	pool, err := db.Pool(ctx)
	if err != nil {
		slog.Error("não foi possível conectar no postgres", "erro", err)
		os.Exit(1)
	}
	defer pool.Close()

	s := &servidor{pool: pool}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /saude", s.saude)
	mux.HandleFunc("GET /clipes/busca", s.buscar)
	mux.HandleFunc("GET /estatisticas", s.estatisticas)

	if err := httpx.Servir(porta, httpx.ComLog(mux)); err != nil {
		slog.Error("servidor encerrou com erro", "erro", err)
		os.Exit(1)
	}
}

func (s *servidor) saude(w http.ResponseWriter, r *http.Request) {
	if err := s.pool.Ping(r.Context()); err != nil {
		httpx.Erro(w, http.StatusServiceUnavailable, "postgres inacessível")
		return
	}
	httpx.JSON(w, http.StatusOK, map[string]string{"estado": "ok", "servico": "catalog"})
}

// buscar aceita filtros que espelham as regras de ranqueamento, para o
// pipeline poder delegar a filtragem ao banco em vez de trazer tudo e descartar.
//
//	q                 texto livre (busca full-text)
//	tipo              video | photo
//	duracao_min/max   janela de duração, que é a regra dos 30%
//	look              bw_archival | painting | color_modern | sepia
//	canal_excluir     não devolve clipe já usado neste canal
//	limite            padrão 20
func (s *servidor) buscar(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	termo := strings.TrimSpace(q.Get("q"))
	limite := inteiroOu(q.Get("limite"), 20)
	if limite > 100 {
		limite = 100
	}

	condicoes := []string{"TRUE"}
	args := []any{}
	adicionar := func(cond string, valor any) {
		args = append(args, valor)
		condicoes = append(condicoes, strings.ReplaceAll(cond, "?", "$"+strconv.Itoa(len(args))))
	}

	if tipo := q.Get("tipo"); tipo == "video" || tipo == "photo" {
		adicionar("c.tipo = ?::tipo_midia", tipo)
	}
	if v := q.Get("duracao_min"); v != "" {
		adicionar("c.duracao_s >= ?", decimalOu(v, 0))
	}
	if v := q.Get("duracao_max"); v != "" {
		adicionar("c.duracao_s <= ?", decimalOu(v, 0))
	}
	if v := q.Get("look"); v != "" {
		adicionar("c.look = ?::look_visual", v)
	}
	if v := q.Get("canal_excluir"); v != "" {
		adicionar(
			"NOT EXISTS (SELECT 1 FROM usos u WHERE u.clipe_id = c.id AND u.canal = ?)",
			v,
		)
	}

	relevancia := "0::double precision"
	if termo != "" {
		args = append(args, termo)
		pos := "$" + strconv.Itoa(len(args))
		condicoes = append(condicoes,
			"(bt.vetor @@ websearch_to_tsquery('simple', "+pos+") OR bt.clipe_id IS NULL)")
		relevancia = "COALESCE(ts_rank(bt.vetor, websearch_to_tsquery('simple', " + pos + ")), 0)"
	}

	args = append(args, limite)
	sql := `
		SELECT c.uuid, c.tipo::text, c.objeto, c.keyframe, c.duracao_s,
		       c.largura, c.altura, c.aspecto, c.provider, c.licenca_id,
		       c.credito, c.look::text, d.caption,
		       COALESCE(
		         ARRAY(
		           SELECT p.termo FROM clipe_palavras cp
		           JOIN palavras p ON p.id = cp.palavra_id
		           WHERE cp.clipe_id = c.id
		           ORDER BY cp.peso DESC LIMIT 12
		         ), '{}'
		       ) AS palavras,
		       ` + relevancia + ` AS relevancia
		FROM clipes_usaveis c
		LEFT JOIN descricoes d ON d.clipe_id = c.id
		LEFT JOIN busca_texto bt ON bt.clipe_id = c.id
		WHERE ` + strings.Join(condicoes, " AND ") + `
		ORDER BY relevancia DESC, c.criado_em DESC
		LIMIT $` + strconv.Itoa(len(args))

	linhas, err := s.pool.Query(r.Context(), sql, args...)
	if err != nil {
		slog.Error("consulta falhou", "erro", err)
		httpx.Erro(w, http.StatusInternalServerError, "consulta ao catálogo falhou")
		return
	}
	defer linhas.Close()

	resultados := make([]clipe, 0, limite)
	for linhas.Next() {
		var c clipe
		if err := linhas.Scan(
			&c.UUID, &c.Tipo, &c.Objeto, &c.Keyframe, &c.DuracaoS,
			&c.Largura, &c.Altura, &c.Aspecto, &c.Provider, &c.LicencaID,
			&c.Credito, &c.Look, &c.Caption, &c.Palavras, &c.Relevancia,
		); err != nil {
			slog.Error("leitura de linha falhou", "erro", err)
			httpx.Erro(w, http.StatusInternalServerError, "leitura do resultado falhou")
			return
		}
		resultados = append(resultados, c)
	}
	if err := linhas.Err(); err != nil {
		httpx.Erro(w, http.StatusInternalServerError, "erro ao percorrer resultados")
		return
	}

	httpx.JSON(w, http.StatusOK, map[string]any{
		"total":    len(resultados),
		"clipes":   resultados,
		"consulta": termo,
	})
}

// estatisticas alimenta o painel do dashboard: tamanho do acervo, e quanto dele
// está bloqueado por licença — que é a métrica de saúde jurídica da base.
func (s *servidor) estatisticas(w http.ResponseWriter, r *http.Request) {
	const sql = `
		SELECT
		  (SELECT count(*) FROM fontes)                                      AS fontes,
		  (SELECT count(*) FROM fontes WHERE licenca_verificada)             AS fontes_livres,
		  (SELECT count(*) FROM clipes)                                      AS clipes,
		  (SELECT count(*) FROM clipes_usaveis)                              AS clipes_usaveis,
		  (SELECT count(*) FROM clipes WHERE tipo = 'video')                 AS videos,
		  (SELECT count(*) FROM clipes WHERE tipo = 'photo')                 AS fotos,
		  (SELECT COALESCE(sum(bytes), 0) FROM clipes)                       AS bytes,
		  (SELECT count(*) FROM descricoes)                                  AS classificados,
		  (SELECT count(*) FROM embeddings)                                  AS com_embedding,
		  (SELECT count(DISTINCT termo) FROM palavras)                       AS palavras`

	var e struct {
		Fontes, FontesLivres, Clipes, ClipesUsaveis int64
		Videos, Fotos, Bytes, Classificados         int64
		ComEmbedding, Palavras                      int64
	}
	if err := s.pool.QueryRow(r.Context(), sql).Scan(
		&e.Fontes, &e.FontesLivres, &e.Clipes, &e.ClipesUsaveis,
		&e.Videos, &e.Fotos, &e.Bytes, &e.Classificados,
		&e.ComEmbedding, &e.Palavras,
	); err != nil {
		slog.Error("estatísticas falharam", "erro", err)
		httpx.Erro(w, http.StatusInternalServerError, "estatísticas indisponíveis")
		return
	}

	httpx.JSON(w, http.StatusOK, map[string]any{
		"fontes":            e.Fontes,
		"fontes_livres":     e.FontesLivres,
		"fontes_bloqueadas": e.Fontes - e.FontesLivres,
		"clipes":            e.Clipes,
		"clipes_usaveis":    e.ClipesUsaveis,
		"videos":            e.Videos,
		"fotos":             e.Fotos,
		"bytes":             e.Bytes,
		"classificados":     e.Classificados,
		"com_embedding":     e.ComEmbedding,
		"palavras":          e.Palavras,
	})
}

func valorOu(chave, padrao string) string {
	if v := os.Getenv(chave); v != "" {
		return v
	}
	return padrao
}

func inteiroOu(texto string, padrao int) int {
	if n, err := strconv.Atoi(texto); err == nil && n > 0 {
		return n
	}
	return padrao
}

func decimalOu(texto string, padrao float64) float64 {
	if f, err := strconv.ParseFloat(texto, 64); err == nil {
		return f
	}
	return padrao
}
