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
