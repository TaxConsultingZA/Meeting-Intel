const { Pool } = require('pg');
const fs = require('fs');

const connectionString = (process.env.DATABASE_URL || '').replace("postgresql+asyncpg://", "postgresql://");
const sql = require('fs').readFileSync('auth-tables.sql', 'utf8');

if (!connectionString) {
  throw new Error('DATABASE_URL is missing. Run with: node --env-file=.env.local migrate-auth.js');
}

const pool = new Pool({
  connectionString,
  ssl: connectionString.includes('localhost')
    ? false
    : { rejectUnauthorized: false },
});

async function migrate() {
  try {
    console.log('Applying NextAuth tables...');
    await pool.query(sql);
    console.log('NextAuth tables created successfully!');
  } catch (err) {
    console.error('Migration error:', err.message);
  } finally {
    await pool.end();
  }
}

migrate();
