import { defineConfig } from 'vitest/config';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './test/setupTests.ts',
    include: [
      'src/**/*.{test,spec}.{js,ts,jsx,tsx}',
      '../../shared/**/*.{test,spec}.{js,ts,jsx,tsx}',
    ],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  // The shared design-mode suites live outside this app's root, so Vite must
  // be explicitly allowed to serve/transform files from the dashboard folder.
  server: {
    fs: {
      allow: [path.resolve(__dirname, '../..')],
    },
  },
  esbuild: {
    jsx: 'automatic',
  },
  cacheDir: './.vitest',
});
