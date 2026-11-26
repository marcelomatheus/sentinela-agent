FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY bff/package.json ./bff/package.json
COPY web/package.json ./web/package.json
RUN npm ci
COPY bff ./bff
COPY web ./web
RUN npm run build
RUN npm prune --omit=dev

FROM node:22-alpine
ENV NODE_ENV=production PORT=3005 WEB_DIST=/app/web-dist
WORKDIR /app
RUN addgroup -S sentinela && adduser -S sentinela -G sentinela
COPY --from=build /app/node_modules /app/node_modules
COPY --from=build /app/bff/dist /app/bff/dist
COPY --from=build /app/web/dist /app/web-dist
COPY --from=build /app/package.json /app/package.json
COPY --from=build /app/bff/package.json /app/bff/package.json
USER sentinela
EXPOSE 3005
CMD ["node","bff/dist/index.js"]
