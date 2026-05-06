const esbuild = require("esbuild");
const path = require("path");
const { spawn } = require("child_process");

const production = process.argv.includes("--production");
const watch = process.argv.includes("--watch");

const docsFrontend = path.resolve(
  __dirname,
  "../agent_actions/tooling/docs/frontend",
);

// Resolve `@/*` to the docs frontend so we can reuse data-card components.
// Tries extensions in order (matches esbuild's default resolveExtensions).
const fs = require("fs");
const exts = [".tsx", ".ts", ".jsx", ".js", ".css"];

const aliasPlugin = {
  name: "alias-docs-frontend",
  setup(build) {
    build.onResolve({ filter: /^@\// }, (args) => {
      const base = path.join(docsFrontend, args.path.slice(2));
      // exact match first
      if (fs.existsSync(base) && fs.statSync(base).isFile()) {
        return { path: base };
      }
      // try with extensions
      for (const ext of exts) {
        const candidate = base + ext;
        if (fs.existsSync(candidate)) return { path: candidate };
      }
      // try as directory with index.*
      for (const ext of exts) {
        const candidate = path.join(base, "index" + ext);
        if (fs.existsSync(candidate)) return { path: candidate };
      }
      return {
        errors: [{ text: `Cannot resolve alias: ${args.path}` }],
      };
    });
  },
};

async function buildExtension() {
  return esbuild.context({
    entryPoints: ["src/extension.ts"],
    bundle: true,
    format: "cjs",
    platform: "node",
    target: "ES2020",
    outfile: "out/extension.js",
    external: ["vscode"],
    sourcemap: !production,
    minify: production,
    logLevel: "info",
  });
}

// Force a single instance of React/ReactDOM so imports from the docs frontend
// resolve to the extension's node_modules. Two Reacts in one bundle break hook
// lookup ("Cannot read properties of null (reading 'useState')").
const reactSingletonAliases = {
  react: path.resolve(__dirname, "node_modules/react"),
  "react/jsx-runtime": path.resolve(
    __dirname,
    "node_modules/react/jsx-runtime.js",
  ),
  "react/jsx-dev-runtime": path.resolve(
    __dirname,
    "node_modules/react/jsx-dev-runtime.js",
  ),
  "react-dom": path.resolve(__dirname, "node_modules/react-dom"),
  "react-dom/client": path.resolve(
    __dirname,
    "node_modules/react-dom/client.js",
  ),
};

async function buildWebview() {
  return esbuild.context({
    entryPoints: ["src/webview/main.tsx"],
    bundle: true,
    format: "iife",
    platform: "browser",
    target: "ES2020",
    outfile: "out/webview.js",
    alias: reactSingletonAliases,
    sourcemap: !production,
    minify: production,
    logLevel: "info",
    jsx: "automatic",
    define: {
      "process.env.NODE_ENV": production ? '"production"' : '"development"',
    },
    banner: {
      // Shim Node globals that some transitive deps (react-markdown, remark-gfm,
      // micromark) reference. These are unbounded globals in the bundle if not shimmed.
      js: [
        `var process=(typeof globalThis!=='undefined'&&globalThis.process)||{env:{NODE_ENV:${production ? '"production"' : '"development"'}},platform:"browser",browser:true,cwd:function(){return"/"},versions:{},nextTick:function(cb){Promise.resolve().then(cb)},emit:function(){}};`,
        `var global=(typeof globalThis!=='undefined')?globalThis:self;`,
        `var setImmediate=(typeof globalThis!=='undefined'&&globalThis.setImmediate)||function(cb){return setTimeout(cb,0)};`,
        `var clearImmediate=(typeof globalThis!=='undefined'&&globalThis.clearImmediate)||function(id){clearTimeout(id)};`,
      ].join(""),
    },
    plugins: [aliasPlugin],
  });
}

function buildCss() {
  return new Promise((resolve, reject) => {
    const args = [
      "tailwindcss",
      "-i",
      "src/webview/webview.css",
      "-o",
      "out/webview.css",
      "-c",
      "tailwind.config.js",
    ];
    if (!production) args.push("--minify=false");
    if (production) args.push("--minify");
    if (watch) args.push("--watch");

    const proc = spawn("npx", args, {
      stdio: "inherit",
      cwd: __dirname,
    });

    if (watch) {
      // Watch mode never resolves; let it run in the background
      proc.on("exit", (code) => {
        if (code !== 0) reject(new Error(`tailwind exited ${code}`));
      });
      // resolve immediately so the rest of the build proceeds
      resolve();
      return;
    }

    proc.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`tailwind exited ${code}`));
    });
  });
}

async function main() {
  const [extCtx, webCtx] = await Promise.all([
    buildExtension(),
    buildWebview(),
  ]);

  if (watch) {
    await Promise.all([extCtx.watch(), webCtx.watch(), buildCss()]);
    console.log("[esbuild] watching for changes...");
  } else {
    await Promise.all([extCtx.rebuild(), webCtx.rebuild(), buildCss()]);
    await extCtx.dispose();
    await webCtx.dispose();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
