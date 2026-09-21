FROM node:24.14.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . ./
ARG SERVICE_VERSION=development
ARG GIT_COMMIT=unknown
ENV VITE_SERVICE_VERSION=$SERVICE_VERSION
RUN npm run build
FROM nginx:1.29.5-alpine
ARG SERVICE_VERSION=development
ARG GIT_COMMIT=unknown
LABEL org.opencontainers.image.version=$SERVICE_VERSION org.opencontainers.image.revision=$GIT_COMMIT
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:8080/health/live || exit 1
