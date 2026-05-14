# ── Stage 1: Install dependencies ────────────────────────────────────────────
FROM node:20-alpine AS deps

WORKDIR /app

# Copy package manifests first for layer-cache efficiency
COPY package.json package-lock.json ./

# Install production + dev deps (needed for the build step)
RUN npm ci

# ── Stage 2: Build the Next.js app ───────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Bring in node_modules from the deps stage
COPY --from=deps /app/node_modules ./node_modules

# Copy all source files
COPY . .

# Next.js may omit `public/`; Docker COPY requires the path to exist in the builder image
RUN mkdir -p public

# Build the production bundle
RUN npm run build

# ── Stage 3: Minimal production runner ───────────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
# Next.js telemetry — disable to keep the container silent
ENV NEXT_TELEMETRY_DISABLED=1

# Non-root user for security
RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs

# Copy only what Next.js `next start` needs
COPY --from=builder /app/public       ./public
COPY --from=builder /app/.next        ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.ts ./next.config.ts

# Ensure the nextjs user owns the app files
RUN chown -R nextjs:nodejs /app

USER nextjs

# The Next.js production server listens on port 3000 by default
EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME=0.0.0.0

CMD ["npm", "start"]
