# Build the SPA, then serve it statically via nginx (which also proxies /api).
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
# nginx's entrypoint renders templates with envsubst using $PORT / $BACKEND_ORIGIN.
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV PORT=8080 BACKEND_ORIGIN=http://backend:8090
EXPOSE 8080
