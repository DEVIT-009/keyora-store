/**
 * Better Auth for Keyora: email + password accounts.
 *
 * Only Flask talks to this service (server-to-server on 127.0.0.1); browsers never
 * call it directly. Flask relays the Set-Cookie headers it returns, so cookies are
 * issued for BETTER_AUTH_URL — the public Flask origin.
 */
import { betterAuth } from "better-auth";
import { admin } from "better-auth/plugins";
import { Pool } from "pg";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set (see .env.example)`);
  return value;
}

// .env holds the SQLAlchemy form (postgresql+psycopg://…); pg wants plain postgresql://.
// sslmode=require (what Neon gives you) is currently treated by pg as verify-full; say so
// explicitly so pg v9's switch to weaker libpq semantics can't silently downgrade it.
const databaseUrl = required("DATABASE_URL")
  .replace(/^postgres(ql)?(\+\w+)?:\/\//, "postgresql://")
  .replace(/([?&])sslmode=(require|prefer|verify-ca)\b/, "$1sslmode=verify-full");
const baseURL = required("BETTER_AUTH_URL");

export const pool = new Pool({ connectionString: databaseUrl });

export const auth = betterAuth({
  baseURL,
  secret: required("BETTER_AUTH_SECRET"),
  database: pool,
  trustedOrigins: [baseURL],
  emailAndPassword: {
    enabled: true,
    autoSignIn: true,
    minPasswordLength: 8,
    maxPasswordLength: 128,
  },
  user: {
    additionalFields: {
      // Cambodian number, digits only (validated by Flask before it gets here).
      phone: { type: "string", required: false },
    },
  },
  plugins: [
    // Adds "user".role ("user" | "admin", input: false — customers can never set it),
    // banned / banReason / banExpires, and refuses to create a session for a banned user
    // (error code BANNED_USER). Flask's admin writes role/ban columns directly and Flask
    // re-checks session + ban on every request (app/auth/__init__.py), so blocks and
    // sign-outs apply at once despite the cookie cache below. The plugin's own /admin/*
    // endpoints exist too, but only Flask can reach this service.
    admin({
      bannedUserMessage: "This account has been blocked. Contact Keyora support if you think this is a mistake.",
    }),
  ],
  session: {
    // Lets get-session answer from a signed cookie for 5 minutes instead of querying Postgres.
    cookieCache: { enabled: true, maxAge: 5 * 60 },
  },
});
