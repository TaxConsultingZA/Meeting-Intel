const { Pool } = require('pg');
const fs = require('fs');
const path = require('fs');
require('dotenv').config({ path: '.env.local' });
require('dotenv').config({ path: '../.env' });

const connectionString = (process.env.DATABASE_URL || '').replace("postgresql+asyncpg://", "postgresql://");
const sql = require('fs').readFileSync('auth-tables.sql', 'utf8');

const pool = new Pool({ connectionString });

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
