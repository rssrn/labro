import '@testing-library/jest-dom';
import { configureAxe, toHaveNoViolations } from 'jest-axe';
import { expect } from 'vitest';

expect.extend(toHaveNoViolations);

// Suppress axe's "Document should have one main landmark" noise in component tests
configureAxe({
  rules: {
    region: { enabled: false },
  },
});
