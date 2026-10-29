# ARVA web interface: static build served by nginx, proxying /api to the API.
FROM node:22.11.0-alpine3.20 AS build
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web ./
# The commit the interface is built from, sent with the errors it reports to the API (scripts/start.sh passes it).
ARG ARVA_GIT_COMMIT=unknown
ENV VITE_ARVA_COMMIT=$ARVA_GIT_COMMIT
RUN npm run build

FROM nginx:1.27.2-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
