/**
 * Seed one admin and one normal customer through Better Auth's own sign-up API
 * (so passwords are hashed exactly like real sign-ups). Idempotent: existing
 * accounts are left alone apart from making sure their role is right.
 *
 *   npm run seed:users
 *
 * Passwords come from SEED_ADMIN_PASSWORD / SEED_USER_PASSWORD when set; otherwise a
 * random one is generated and printed once for each newly created account.
 */
import { randomBytes } from "node:crypto";
import { auth, pool } from "./auth.ts";

const accounts = [
  { name: "Keyora Admin", email: "admin@keyora.test", role: "admin", passwordEnv: "SEED_ADMIN_PASSWORD" },
  { name: "Sok Dara", email: "customer@keyora.test", role: "user", passwordEnv: "SEED_USER_PASSWORD" },
];

try {
  for (const account of accounts) {
    const existing = await pool.query('select id from "user" where email = $1', [account.email]);
    let created = false;
    let password: string | undefined;
    if (existing.rowCount === 0) {
      password = process.env[account.passwordEnv] || randomBytes(12).toString("base64url");
      await auth.api.signUpEmail({ body: { name: account.name, email: account.email, password } });
      created = true;
    }
    await pool.query('update "user" set role = $1 where email = $2', [account.role, account.email]);
    const shownPassword = !created ? "(unchanged)" : process.env[account.passwordEnv] ? `(from ${account.passwordEnv})` : password;
    console.log(`${created ? "created" : "exists "}  ${account.role.padEnd(5)}  ${account.email}  password: ${shownPassword}`);
  }
} finally {
  await pool.end();
}
