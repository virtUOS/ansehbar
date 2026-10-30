FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json* ./
# `npm ci` when a lockfile exists (reliably installs the platform-specific
# optional dependencies, npm/cli#4828); plain install on the very first run.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .

EXPOSE 5179

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5179"]
