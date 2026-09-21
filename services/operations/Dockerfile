FROM golang:1.26.4-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /operations ./cmd/operations && CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /carrier ./cmd/carrier
FROM alpine:3.23
RUN apk add --no-cache ca-certificates && addgroup -S parceldesk && adduser -S -G parceldesk parceldesk
COPY --from=build /operations /usr/local/bin/operations
COPY --from=build /carrier /usr/local/bin/carrier
USER parceldesk
EXPOSE 8080 8081
ENTRYPOINT ["/usr/local/bin/operations"]
