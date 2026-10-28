# signalfloor dashboard

A web view of the eval runs stored in [signalfloor-server](../packages/server/README.md). Built
with Next.js and TypeScript.

It has two pages so far:

- **Runs** lists every run, newest first, with a form to pick two runs to compare.
- **Compare** says whether the candidate is a real regression, a real improvement or noise,
  draws the confidence interval against zero, and lists the cases that dropped or gained the
  most.

The compare page answers with the same paired bootstrap as `signalfloor compare`, with a fixed
seed so the interval doesn't move when you reload. Its URL holds both run ids, so a comparison
can be shared as a link.

For the two prompt versions of the reference agent it shows a real improvement of +0.083, and
also that the gain is a net one: 22 questions got better and 12 got worse. One question that v1
answered perfectly scored 0 with v2. Opening a case's trace comes next.

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
