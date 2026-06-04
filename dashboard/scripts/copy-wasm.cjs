const { cpSync, mkdirSync } = require('fs');
const { join } = require('path');
const src = join(__dirname, '../node_modules/sql.js/dist/sql-wasm.wasm');
const dest = join(__dirname, '../public/sql-wasm.wasm');
mkdirSync(join(__dirname, '../public'), { recursive: true });
cpSync(src, dest);
