#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = path.resolve(desktopRoot, "..");

function commandOk(command, args = ["--version"]) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    shell: process.platform === "win32",
  });
  return {
    ok: result.status === 0,
    text: `${result.stdout || ""}${result.stderr || ""}`.trim().split(/\r?\n/)[0] || "",
  };
}

function pythonCandidates() {
  if (process.platform === "win32") {
    return [
      path.join(projectRoot, ".venv", "Scripts", "python.exe"),
      path.join(projectRoot, "runtime", "python", "python.exe"),
      "python",
    ];
  }
  return [
    path.join(projectRoot, ".venv", "bin", "python"),
    path.join(projectRoot, "runtime", "python", "bin", "python3"),
    "python3",
    "python",
  ];
}

function existingCommand(command) {
  return !command.includes(path.sep) || fs.existsSync(command);
}

function pythonVersion(command) {
  const script = "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')";
  const result = spawnSync(command, ["-c", script], {
    encoding: "utf8",
    shell: process.platform === "win32" && !command.includes(path.sep),
  });
  if (result.status !== 0) {
    return { ok: false, text: "" };
  }
  const text = (result.stdout || "").trim();
  const match = text.match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!match) {
    return { ok: false, text };
  }
  const major = Number(match[1]);
  const minor = Number(match[2]);
  return {
    ok: major === 3 && minor >= 10 && minor <= 12,
    text: `${text} (${command})`,
  };
}

function resolvePython() {
  let firstFound = null;
  for (const candidate of pythonCandidates()) {
    if (!existingCommand(candidate)) {
      continue;
    }
    const version = pythonVersion(candidate);
    if (!firstFound && version.text) {
      firstFound = version;
    }
    if (version.ok) {
      return version;
    }
  }
  return firstFound || { ok: false, text: "need Python 3.10-3.12" };
}

function printCheck(label, ok, detail = "") {
  const mark = ok ? "OK" : "MISSING";
  const suffix = detail ? ` - ${detail}` : "";
  console.log(`${mark} ${label}${suffix}`);
}

const checks = [];
const serverEntry = path.join(projectRoot, "server", "app.py");

checks.push(["Captain project root", fs.existsSync(serverEntry), serverEntry]);

for (const command of ["node", "npm"]) {
  const result = commandOk(command);
  checks.push([command, result.ok, result.text]);
}

const python = resolvePython();
checks.push(["Python 3.10-3.12", python.ok, python.text]);

for (const command of ["rustc", "cargo"]) {
  const result = commandOk(command);
  checks.push([command, result.ok, result.text]);
}

let failed = false;
for (const [label, ok, detail] of checks) {
  printCheck(label, ok, detail);
  failed = failed || !ok;
}

if (failed) {
  console.log("");
  console.log("Install hints:");
  if (process.platform === "win32") {
    console.log("  powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\install-windows-prereqs.ps1");
    console.log("  Close and reopen PowerShell after installation, then run npm run check again.");
  } else {
    console.log("  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh");
    console.log("  source \"$HOME/.cargo/env\"");
    console.log("  brew install python@3.12");
    console.log("  cd .. && python3.12 -m venv .venv");
    console.log("  .venv/bin/python -m pip install -U pip");
    console.log("  .venv/bin/python -m pip install -e '.[all]'");
  }
  process.exit(1);
}
