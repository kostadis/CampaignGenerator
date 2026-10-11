import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

// Component tests: Vue Test Utils in jsdom. Playwright owns e2e/ (*.spec.ts);
// component tests live beside their component as *.test.ts so the two runners
// never pick up each other's files.
export default mergeConfig(viteConfig, defineConfig({
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
    restoreMocks: true,
    unstubGlobals: true,
  },
}))
