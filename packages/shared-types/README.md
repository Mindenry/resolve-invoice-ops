# @resolve/shared-types

Generated TypeScript types for the RESOLVE REST API. The file is produced from the live
OpenAPI document, so it never drifts from backend schemas:

```bash
# with the API running
cd packages/shared-types
npm install
npm run generate
```

`src/api.ts` is committed for convenience. The web app keeps its own small projection of the
types it consumes (`apps/web/src/types/api.ts`) to avoid a build-time dependency between
packages; both are checked together by CI.