// Package httpx traz o mínimo compartilhado entre os serviços HTTP:
// resposta JSON, log de acesso, CORS e desligamento limpo.
package httpx

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

// JSON escreve a resposta e nunca deixa o handler sem content-type.
func JSON(w http.ResponseWriter, status int, corpo any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	if corpo == nil {
		return
	}
	if err := json.NewEncoder(w).Encode(corpo); err != nil {
		slog.Error("falha ao serializar resposta", "erro", err)
	}
}

// Erro padroniza o corpo de erro para o front tratar de um jeito só.
func Erro(w http.ResponseWriter, status int, mensagem string) {
	JSON(w, status, map[string]string{"erro": mensagem})
}

// ComLog registra método, rota, status e duração.
func ComLog(proximo http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		inicio := time.Now()
		captura := &capturaStatus{ResponseWriter: w, status: http.StatusOK}
		proximo.ServeHTTP(captura, r)
		nivel := slog.LevelInfo
		if captura.status >= 500 {
			nivel = slog.LevelError
		}
		slog.Log(r.Context(), nivel, "requisicao",
			"metodo", r.Method,
			"rota", r.URL.Path,
			"status", captura.status,
			"ms", time.Since(inicio).Milliseconds(),
		)
	})
}

// ComCORS libera apenas as origens configuradas. O front é a única coisa que
// bate no BFF, então a lista costuma ter um item.
func ComCORS(origens string, proximo http.Handler) http.Handler {
	permitidas := map[string]bool{}
	for _, o := range strings.Split(origens, ",") {
		if o = strings.TrimSpace(o); o != "" {
			permitidas[o] = true
		}
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origem := r.Header.Get("Origin")
		if permitidas[origem] || permitidas["*"] {
			w.Header().Set("Access-Control-Allow-Origin", origem)
			w.Header().Set("Vary", "Origin")
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		}
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		proximo.ServeHTTP(w, r)
	})
}

// Servir sobe o servidor e espera SIGTERM para desligar sem cortar requisição
// no meio — importante porque o compose manda SIGTERM em cada deploy.
func Servir(porta string, manipulador http.Handler) error {
	srv := &http.Server{
		Addr:              ":" + porta,
		Handler:           manipulador,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      60 * time.Second,
		IdleTimeout:       90 * time.Second,
	}

	erros := make(chan error, 1)
	go func() {
		slog.Info("servidor ouvindo", "porta", porta)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			erros <- err
		}
	}()

	parar := make(chan os.Signal, 1)
	signal.Notify(parar, syscall.SIGINT, syscall.SIGTERM)

	select {
	case err := <-erros:
		return err
	case <-parar:
		slog.Info("desligando")
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		return srv.Shutdown(ctx)
	}
}

// Healthcheck permite `service -healthcheck` como teste do compose, evitando
// depender de curl numa imagem distroless que não tem shell.
func Healthcheck(porta string) int {
	conexao, err := net.DialTimeout("tcp", "127.0.0.1:"+porta, 3*time.Second)
	if err != nil {
		return 1
	}
	_ = conexao.Close()
	return 0
}

type capturaStatus struct {
	http.ResponseWriter
	status int
}

func (c *capturaStatus) WriteHeader(codigo int) {
	c.status = codigo
	c.ResponseWriter.WriteHeader(codigo)
}
