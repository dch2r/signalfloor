# signalfloor dashboard

A web view of the eval runs stored in [signalfloor-server](../packages/server/README.md). Built
with Next.js and TypeScript.

So far it lists runs. Comparing two runs and opening a case's trace come next.

## Running it

You need Node 24. With [nvm](https://github.com/nvm-sh/nvm), `nvm use` in the repo root picks it
up from `.nvmrc`. Start the API server first, then:

```bash
cd dashboard
npm install
npm run dev
```

Open http://localhost:3000. The dashboard talks to the API at `http://127.0.0.1:8000`. Set
`SIGNALFLOOR_API_URL` to use another address.

All API calls happen on the Next.js server, never in the browser, so the API doesn't need CORS
and doesn't have to be reachable from the user's machine.

## API types

The TypeScript types for the API are generated from the server's OpenAPI schema, so a change to
the API shows up as a type error here instead of a broken page. After changing the API, run:

```bash
uv run signalfloor-server openapi > dashboard/openapi.json
cd dashboard && npm run api:types
```

CI regenerates both files and fails if they differ from what is committed.

## Checks

```bash
npm run lint
npm run typecheck
npm test
npm run build
```
