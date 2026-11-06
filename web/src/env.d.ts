/// <reference types="astro/client" />

interface ImportMetaEnv {
  /** The data folder the build read (astro.config.mjs): "web/src/data" unless FP_DATA_DIR is set. */
  readonly FP_DATA_DIR: string;
}
