# Build multi-stage para os serviços Go. Imagem final ~25 MB, sem shell,
# rodando como usuário sem privilégio.
ARG SERVICE

FROM golang:1.25-alpine AS build
ARG SERVICE
WORKDIR /src

# Cache de dependências separado do código: mudar handler não rebaixa o cache.
COPY services/go.mod services/go.sum ./
RUN go mod download

COPY services/ ./
RUN CGO_ENABLED=0 GOOS=linux go build \
      -ldflags="-s -w" \
      -trimpath \
      -o /out/service \
      ./cmd/${SERVICE}

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/service /app/service
USER nonroot:nonroot
ENTRYPOINT ["/app/service"]
