import { createServer } from "node:http";
import { toNodeHandler } from "better-auth/node";
import { auth } from "./auth.ts";

const port = Number(process.env.AUTH_PORT ?? 3005);

// Loopback only: Flask is the single client. Never expose this port publicly.
createServer(toNodeHandler(auth)).listen(port, "127.0.0.1", () => {
  console.log(`Better Auth listening on http://127.0.0.1:${port}/api/auth`);
});
