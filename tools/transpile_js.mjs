import babel from "@babel/core";
import presetEnv from "@babel/preset-env";

const chunks = [];
for await (const chunk of process.stdin) {
  chunks.push(chunk);
}

try {
  const input = JSON.parse(chunks.join(""));
  const result = babel.transformSync(input.source, {
    presets: [[presetEnv, {
      targets: { safari: `${input.ios_major}.0` },
      useBuiltIns: false,
      modules: false,
    }]],
    sourceType: "unambiguous",
  });
  process.stdout.write(JSON.stringify({ code: result.code }));
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
