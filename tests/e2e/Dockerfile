FROM mcr.microsoft.com/playwright:v1.62.1-noble@sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e

WORKDIR /tests/e2e
COPY tests/e2e/package.json tests/e2e/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY --chown=pwuser:pwuser tests/e2e/ ./
RUN npm run check
RUN chown -R pwuser:pwuser /tests/e2e

USER pwuser
CMD ["npm", "test"]
