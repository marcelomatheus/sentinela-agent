FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY bff/package.json ./bff/package.json
COPY web/package.json ./web/package.json
RUN npm install -g npm@11.21.3 && npm ci
COPY bff ./bff
RUN npm run build --workspace @sentinela/bff
RUN npm prune --omit=dev

FROM node:22-alpine
ENV NODE_ENV=production PORT=3005
WORKDIR /app
RUN addgroup -S sentinela && adduser -S sentinela -G sentinela
COPY --from=build /app/node_modules /app/node_modules
COPY --from=build /app/bff/dist /app/bff/dist
COPY --from=build /app/package.json /app/package.json
COPY --from=build /app/bff/package.json /app/bff/package.json
USER sentinela
EXPOSE 3005
CMD ["node","bff/dist/index.js"]
