// Generates the RSA-2048 key pair that signs offline licence files. Run once:
//   node platform/deploy/keygen.mjs
// Private key -> LICENSE_FILE_PRIVATE_KEY on the platform; public modulus -> the programs.
import { generateKeyPairSync } from "node:crypto";

const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
console.log(`LICENSE_FILE_PRIVATE_KEY=${privateKey.export({ type: "pkcs8", format: "der" }).toString("base64")}`);
console.log("\n# Public modulus (PUBLIC_KEY_N in monitor/barpi_monitor/license.py):");
console.log(publicKey.export({ format: "jwk" }).n);
console.log(`\n${publicKey.export({ type: "spki", format: "pem" })}`);
