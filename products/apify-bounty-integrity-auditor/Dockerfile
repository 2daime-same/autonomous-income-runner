FROM apify/actor-node:22

COPY package*.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY . ./
RUN npm run check
CMD ["npm", "start"]
