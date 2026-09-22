/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_AUTH_ENV?: 'development' | 'production';
  readonly VITE_ALLOW_MOCK_FALLBACKS?: 'true' | 'false';
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
