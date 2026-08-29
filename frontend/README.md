# UTSA Gno.land Explorer frontend

React and Vite frontend for the UTSA Gno.land Explorer.

## Local development

```bash
npm install
npm run dev
```

The Vite development server proxies `/api` requests to the local API at
`http://127.0.0.1:18180`. Set `VITE_API_ROOT` to use a different API base path.

## Production build

```bash
npm run build
```

The static output is written to `dist/`.

## Multichain frontend foundation

`src/config/networkRegistry.js` is the single source of static network configuration. A network's stable ID (for example, `gno-pearl`) is an application identity and does not change when a protocol runtime chain ID changes. The expected Pearl runtime chain ID (`pearl-1`) is registry metadata; the live value displayed by the explorer continues to come independently from `/api/health` through `useChainIdentity`.

Capabilities declare which navigation pages and feature surfaces a network supports. The model reserves Network Parameters and Consensus Diagnostics for future use, but Pearl does not enable them and this change adds no pages for them. Pearl keeps its legacy unprefixed URLs, including all list and detail routes.

Only Gno.land Pearl is registered today. No Cosmos network or Cosmos connectivity is included, and the backend, public API, indexer, and database remain Gno-only.
