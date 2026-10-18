import fs from "node:fs";
import zlib from "node:zlib";

const [, , src, dst] = process.argv;
if (!src || !dst) {
  console.error("usage: node decompress_session.mjs <input.zstd> <output.jsonl>");
  process.exit(2);
}

const buf = fs.readFileSync(src);
const magic = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);
const offsets = [];
let pos = 0;
while ((pos = buf.indexOf(magic, pos)) !== -1) {
  offsets.push(pos);
  pos += 4;
}
if (offsets.length === 0) {
  console.error("no zstd frames found");
  process.exit(3);
}

const chunks = [];
let i = 0;
while (i < offsets.length) {
  let ok = false;
  let lastError = null;
  for (let take = 1; take <= 6; take += 1) {
    if (i + take > offsets.length) break;
    const end = i + take < offsets.length ? offsets[i + take] : buf.length;
    try {
      chunks.push(zlib.zstdDecompressSync(buf.subarray(offsets[i], end)));
      i += take;
      ok = true;
      break;
    } catch (err) {
      lastError = err;
    }
  }
  if (!ok) {
    console.error(`failed to decompress frame at offset ${offsets[i]}: ${lastError?.message || "unknown"}`);
    process.exit(4);
  }
}

fs.writeFileSync(dst, Buffer.concat(chunks));
console.log(JSON.stringify({ frames: offsets.length, bytes: Buffer.concat(chunks).length }));
