// bff — a única porta que o front conhece.
//
// Existe para manter CORS, validação e versionamento de API num lugar só, e
// para permitir quebrar os serviços internos sem tocar no front. Não tem regra
// de negócio: agrega, valida entrada e repassa.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/willdarkface/videosearcher/services/internal/db"
	"github.com/willdarkface/videosearcher/services/internal/httpx"
)

type servidor struct {
	pool        *pgxpool.Pool
	catalogURL  string
	pipelineURL string
	cliente     *http.Client
}

func main() {
	healthcheck := flag.Bool("healthcheck", false, "testa se a porta responde e sai")
	flag.Parse()

	porta := valorOu("PORT", "8080")
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

	s := &servidor{
		pool:        pool,
		catalogURL:  valorOu("CATALOG_URL", "http://catalog:8081"),
		pipelineURL: valorOu("PIPELINE_URL", "http://pipeline:8082"),
		cliente:     &http.Client{Timeout: 30 * time.Second},
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /saude", s.saude)
	mux.HandleFunc("GET /api/canais", s.canais)
	mux.HandleFunc("GET /api/projetos", s.listarProjetos)
	mux.HandleFunc("POST /api/projetos", s.criarProjeto)
	mux.HandleFunc("GET /api/projetos/{uuid}/blocos", s.blocosDoProjeto)
	mux.HandleFunc("GET /api/catalogo/busca", s.proxyCatalogo("/clipes/busca"))
	mux.HandleFunc("GET /api/catalogo/estatisticas", s.proxyCatalogo("/estatisticas"))

	manipulador := httpx.ComCORS(valorOu("CORS_ORIGIN", "http://localhost:3000"), httpx.ComLog(mux))
	if err := httpx.Servir(porta, manipulador); err != nil {
		slog.Error("servidor encerrou com erro", "erro", err)
		os.Exit(1)
	}
}

func (s *servidor) saude(w http.ResponseWriter, r *http.Request) {
	estado := map[string]any{"estado": "ok", "servico": "bff"}
	if err := s.pool.Ping(r.Context()); err != nil {
		estado["postgres"] = "inacessivel"
		httpx.JSON(w, http.StatusServiceUnavailable, estado)
		return
	}
	estado["postgres"] = "ok"
	httpx.JSON(w, http.StatusOK, estado)
}

// canais devolve os packs disponíveis. Hoje vem do pipeline, que é quem lê os
// YAMLs; o BFF só repassa para o front não precisar conhecer dois serviços.
func (s *servidor) canais(w http.ResponseWriter, r *http.Request) {
	s.repassar(w, r, s.pipelineURL+"/canais")
}

func (s *servidor) listarProjetos(w http.ResponseWriter, r *http.Request) {
	const sql = `
		SELECT p.uuid, p.nome, p.canal, p.legenda_nome, p.config, p.criado_em,
		       (SELECT count(*) FROM blocos b WHERE b.projeto_id = p.id) AS blocos,
		       (SELECT count(*) FROM blocos b
		         WHERE b.projeto_id = p.id AND b.clipe_id IS NOT NULL) AS resolvidos
		FROM projetos p
		ORDER BY p.criado_em DESC
		LIMIT 100`

	linhas, err := s.pool.Query(r.Context(), sql)
	if err != nil {
		slog.Error("listagem de projetos falhou", "erro", err)
		httpx.Erro(w, http.StatusInternalServerError, "não foi possível listar projetos")
		return
	}
	defer linhas.Close()

	type projeto struct {
		UUID        string         `json:"uuid"`
		Nome        string         `json:"nome"`
		Canal       string         `json:"canal"`
		LegendaNome *string        `json:"legenda_nome"`
		Config      map[string]any `json:"config"`
		CriadoEm    time.Time      `json:"criado_em"`
		Blocos      int            `json:"blocos"`
		Resolvidos  int            `json:"resolvidos"`
	}

	projetos := []projeto{}
	for linhas.Next() {
		var p projeto
		if err := linhas.Scan(&p.UUID, &p.Nome, &p.Canal, &p.LegendaNome,
			&p.Config, &p.CriadoEm, &p.Blocos, &p.Resolvidos); err != nil {
			httpx.Erro(w, http.StatusInternalServerError, "leitura de projeto falhou")
			return
		}
		projetos = append(projetos, p)
	}
	httpx.JSON(w, http.StatusOK, map[string]any{"projetos": projetos})
}

type novoProjeto struct {
	Nome           string   `json:"nome"`
	Canal          string   `json:"canal"`
	LegendaNome    string   `json:"legenda_nome"`
	LegendaTexto   string   `json:"legenda_texto"`
	ProporcaoVideo *float64 `json:"proporcao_video"`
	DuracaoMin     *float64 `json:"duracao_min"`
	DuracaoMax     *float64 `json:"duracao_max"`
}

func (s *servidor) criarProjeto(w http.ResponseWriter, r *http.Request) {
	var corpo novoProjeto
	if err := json.NewDecoder(io.LimitReader(r.Body, 8<<20)).Decode(&corpo); err != nil {
		httpx.Erro(w, http.StatusBadRequest, "JSON inválido")
		return
	}
	if corpo.Canal == "" || corpo.LegendaTexto == "" {
		httpx.Erro(w, http.StatusBadRequest, "canal e legenda_texto são obrigatórios")
		return
	}
	if corpo.ProporcaoVideo != nil && (*corpo.ProporcaoVideo < 0 || *corpo.ProporcaoVideo > 1) {
		httpx.Erro(w, http.StatusBadRequest, "proporcao_video deve estar entre 0 e 1")
		return
	}
	if corpo.Nome == "" {
		corpo.Nome = corpo.LegendaNome
	}

	config := map[string]any{}
	if corpo.ProporcaoVideo != nil {
		config["proporcao_video"] = *corpo.ProporcaoVideo
	}
	if corpo.DuracaoMin != nil && corpo.DuracaoMax != nil {
		config["duracao_bloco"] = []float64{*corpo.DuracaoMin, *corpo.DuracaoMax}
	}

	var uuid string
	const sql = `
		INSERT INTO projetos (nome, canal, legenda_nome, legenda_texto, config)
		VALUES ($1, $2, $3, $4, $5)
		RETURNING uuid`
	if err := s.pool.QueryRow(r.Context(), sql,
		corpo.Nome, corpo.Canal, corpo.LegendaNome, corpo.LegendaTexto, config,
	).Scan(&uuid); err != nil {
		slog.Error("criação de projeto falhou", "erro", err)
		httpx.Erro(w, http.StatusInternalServerError, "não foi possível criar o projeto")
		return
	}

	// O processamento é assíncrono: o pipeline consome da fila. O front
	// acompanha por /api/projetos/{uuid}/blocos.
	httpx.JSON(w, http.StatusAccepted, map[string]string{
		"uuid":   uuid,
		"estado": "enfileirado",
	})
}

func (s *servidor) blocosDoProjeto(w http.ResponseWriter, r *http.Request) {
	uuid := r.PathValue("uuid")
	const sql = `
		SELECT b.numero, b.inicio_s, b.fim_s, b.texto, b.brief, b.nota,
		       b.motivo, b.arquivo, c.uuid, c.tipo::text, c.objeto, c.keyframe,
		       c.duracao_s
		FROM blocos b
		JOIN projetos p ON p.id = b.projeto_id
		LEFT JOIN clipes c ON c.id = b.clipe_id
		WHERE p.uuid = $1
		ORDER BY b.numero`

	linhas, err := s.pool.Query(r.Context(), sql, uuid)
	if err != nil {
		httpx.Erro(w, http.StatusInternalServerError, "não foi possível carregar os blocos")
		return
	}
	defer linhas.Close()

	type bloco struct {
		Numero   int             `json:"numero"`
		InicioS  float64         `json:"inicio_s"`
		FimS     float64         `json:"fim_s"`
		Texto    string          `json:"texto"`
		Brief    json.RawMessage `json:"brief"`
		Nota     *float32        `json:"nota"`
		Motivo   *string         `json:"motivo"`
		Arquivo  *string         `json:"arquivo"`
		ClipeID  *string         `json:"clipe_uuid"`
		Tipo     *string         `json:"tipo"`
		Objeto   *string         `json:"objeto"`
		Keyframe *string         `json:"keyframe"`
		Duracao  *float64        `json:"duracao_asset_s"`
	}

	blocos := []bloco{}
	for linhas.Next() {
		var b bloco
		if err := linhas.Scan(&b.Numero, &b.InicioS, &b.FimS, &b.Texto, &b.Brief,
			&b.Nota, &b.Motivo, &b.Arquivo, &b.ClipeID, &b.Tipo, &b.Objeto,
			&b.Keyframe, &b.Duracao); err != nil {
			httpx.Erro(w, http.StatusInternalServerError, "leitura de bloco falhou")
			return
		}
		blocos = append(blocos, b)
	}
	httpx.JSON(w, http.StatusOK, map[string]any{"blocos": blocos})
}

// proxyCatalogo repassa a query string para o serviço de catálogo. O front não
// precisa saber que o catálogo é outro serviço.
func (s *servidor) proxyCatalogo(caminho string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		destino := s.catalogURL + caminho
		if bruto := r.URL.RawQuery; bruto != "" {
			destino += "?" + bruto
		}
		if _, err := url.Parse(destino); err != nil {
			httpx.Erro(w, http.StatusBadRequest, "parâmetros inválidos")
			return
		}
		s.repassar(w, r, destino)
	}
}

func (s *servidor) repassar(w http.ResponseWriter, r *http.Request, destino string) {
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, destino, nil)
	if err != nil {
		httpx.Erro(w, http.StatusInternalServerError, "requisição interna inválida")
		return
	}
	resp, err := s.cliente.Do(req)
	if err != nil {
		slog.Error("serviço interno inacessível", "destino", destino, "erro", err)
		httpx.Erro(w, http.StatusBadGateway, "serviço interno indisponível")
		return
	}
	defer resp.Body.Close()

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(resp.StatusCode)
	if _, err := io.Copy(w, io.LimitReader(resp.Body, 16<<20)); err != nil {
		slog.Error("falha ao repassar corpo", "erro", err)
	}
}

func valorOu(chave, padrao string) string {
	if v := os.Getenv(chave); v != "" {
		return v
	}
	return padrao
}
