# ==============================================================================
# RoadTrace AI Frontend - Multi-stage Production Dockerfile
# Stage 1: Build Vite React bundle
# Stage 2: Serve optimized static assets via Nginx
# ==============================================================================

# Stage 1: Build React 18 / Vite application
FROM node:18-alpine AS builder

WORKDIR /app

# Copy dependency manifests
COPY package.json package-lock.json* ./
RUN npm ci || npm install

# Copy application source
COPY . .

# Build production distribution
RUN npm run build


# Stage 2: Minimal Nginx web server
FROM nginx:1.25-alpine AS runner

# Remove default nginx site
RUN rm -rf /etc/nginx/conf.d/default.conf

# Copy custom Nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy compiled static files from builder
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

# Healthcheck testing HTTP response from localhost
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
