FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install --silent
COPY index.html vite.config.js ./
COPY public ./public
COPY src ./src
ARG VITE_API_URL=http://localhost:8001
ARG VITE_AUTH_URL=http://localhost:8002
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_AUTH_URL=$VITE_AUTH_URL
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -f /docker-entrypoint.d/10-listen-on-ipv6-by-default.sh
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
