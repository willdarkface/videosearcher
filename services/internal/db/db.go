// Package db concentra a conexão com o Postgres.
package db

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Pool devolve um pool configurado a partir do ambiente.
//
// O tamanho do pool é modesto de propósito: são vários serviços contra o mesmo
// Postgres, e max_connections=100 se esgota rápido se cada um abrir 25.
func Pool(ctx context.Context) (*pgxpool.Pool, error) {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		dsn = fmt.Sprintf(
			"postgres://%s:%s@%s:%s/%s?sslmode=disable",
			env("POSTGRES_USER", "vs"),
			env("POSTGRES_PASSWORD", "vs"),
			env("POSTGRES_HOST", "localhost"),
			env("POSTGRES_PORT", "5432"),
			env("POSTGRES_DB", "videosearcher"),
		)
	}

	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, fmt.Errorf("dsn inválido: %w", err)
	}
	cfg.MaxConns = 10
	cfg.MinConns = 1
	cfg.MaxConnLifetime = time.Hour
	cfg.MaxConnIdleTime = 5 * time.Minute
	cfg.HealthCheckPeriod = 30 * time.Second

	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("criando pool: %w", err)
	}

	pingCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	if err := pool.Ping(pingCtx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("postgres inacessível: %w", err)
	}
	return pool, nil
}

func env(chave, padrao string) string {
	if v := os.Getenv(chave); v != "" {
		return v
	}
	return padrao
}
