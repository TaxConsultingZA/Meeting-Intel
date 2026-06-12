const { Pool } = require('pg');
require('dotenv').config({ path: '.env.local' });
require('dotenv').config({ path: '../.env' });

const connectionString = (process.env.DATABASE_URL || '').replace("postgresql+asyncpg://", "postgresql://");

console.log('Testing connection to:', connectionString.replace(/:[^:@]+@/, ':***@'));

const pool = new Pool({
  connectionString,
  connectionTimeoutMillis: 5000,
});

async function test() {
  try {
    const client = await pool.connect();
    console.log('Successfully connected to DB');
    const res = await client.query('SELECT NOW()');
    console.log('Query result:', res.rows[0]);
    client.release();
    process.exit(0);
  } catch (err) {
    console.error('Connection error:', err.message);
    process.exit(1);
  }
}

test();
