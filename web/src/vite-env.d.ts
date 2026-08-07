/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PPT_MASTER_BASE_URL?: string;
  readonly VITE_PPT_MASTER_PAGE_COUNT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
