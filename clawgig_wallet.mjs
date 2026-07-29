#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';

function base58Encode(buffer) {
  if (buffer.length === 0) return '';
  const digits = [0];
  for (const byte of buffer) {
    let carry = byte;
    for (let i = 0; i < digits.length; i += 1) {
      carry += digits[i] << 8;
      digits[i] = carry % 58;
      carry = Math.floor(carry / 58);
    }
    while (carry > 0) {
      digits.push(carry % 58);
      carry = Math.floor(carry / 58);
    }
  }
  let output = '';
  for (let i = 0; i < buffer.length && buffer[i] === 0; i += 1) {
    output += alphabet[0];
  }
  for (let i = digits.length - 1; i >= 0; i -= 1) {
    output += alphabet[digits[i]];
  }
  return output;
}

function decodeBase64Url(value) {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4);
  return Buffer.from(padded, 'base64');
}

const stateDir = process.env.CLAWGIG_STATE_DIR || '.clawgig-state';
const outputFile = process.env.CLAWGIG_WALLET_AUTH_FILE || '/tmp/clawgig-wallet-auth.json';
const privateKeyPath = path.join(stateDir, 'solana-private.pem');
const publicInfoPath = path.join(stateDir, 'solana-public.json');
const messagePath = path.join(stateDir, 'registration-message.txt');
fs.mkdirSync(stateDir, { recursive: true, mode: 0o700 });

let privateKey;
let publicKey;
if (fs.existsSync(privateKeyPath)) {
  privateKey = crypto.createPrivateKey(fs.readFileSync(privateKeyPath, 'utf8'));
  publicKey = crypto.createPublicKey(privateKey);
} else {
  const pair = crypto.generateKeyPairSync('ed25519');
  privateKey = pair.privateKey;
  publicKey = pair.publicKey;
  fs.writeFileSync(
    privateKeyPath,
    privateKey.export({ type: 'pkcs8', format: 'pem' }),
    { mode: 0o600 },
  );
}

const publicJwk = publicKey.export({ format: 'jwk' });
if (!publicJwk.x) throw new Error('Ed25519 public JWK is missing x');
const rawPublic = decodeBase64Url(publicJwk.x);
if (rawPublic.length !== 32) throw new Error(`Unexpected Ed25519 public key length: ${rawPublic.length}`);
const solanaWallet = base58Encode(rawPublic);

let message;
if (fs.existsSync(messagePath)) {
  message = fs.readFileSync(messagePath, 'utf8').trim();
} else {
  message = `Register BoundaryLedger Agent on ClawGig: ${crypto.randomUUID()}`;
  fs.writeFileSync(messagePath, `${message}\n`, { mode: 0o600 });
}
const messageBytes = Buffer.from(message, 'utf8');
const signature = crypto.sign(null, messageBytes, privateKey);
if (!crypto.verify(null, messageBytes, publicKey, signature)) {
  throw new Error('Generated Ed25519 signature failed local verification');
}
const walletSignature = base58Encode(signature);

fs.writeFileSync(
  publicInfoPath,
  `${JSON.stringify({ solana_wallet: solanaWallet, created_at: new Date().toISOString() }, null, 2)}\n`,
  { mode: 0o600 },
);
fs.writeFileSync(
  outputFile,
  `${JSON.stringify({ solana_wallet: solanaWallet, wallet_signature: walletSignature, wallet_message: message })}\n`,
  { mode: 0o600 },
);
console.log(JSON.stringify({ ok: true, solana_wallet: solanaWallet }));
