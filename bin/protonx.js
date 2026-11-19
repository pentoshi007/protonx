#!/usr/bin/env node
'use strict';

const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const readline = require('readline');

const PACKAGE_ROOT = path.join(__dirname, '..');
const VERSION = require('../package.json').version;
const MAC_INSTALL = 'curl -fsSL https://raw.githubusercontent.com/pentoshi007/protonx/main/get.sh | bash';

function unixTarget(installer) {
  const libexec = '/usr/local/libexec/protonx';
  return {
    versionFile: path.join(libexec, 'VERSION'),
    command: path.join(libexec, 'venv', 'bin', 'python'),
    args: [path.join(libexec, 'protonx')],
    installer,
  };
}

function windowsTarget() {
  const root = path.join(process.env.LOCALAPPDATA || '', 'protonx');
  const script = path.join(PACKAGE_ROOT, 'cli', 'install-windows.ps1');
  return {
    versionFile: path.join(root, 'VERSION'),
    command: path.join(root, 'venv', 'Scripts', 'python.exe'),
    args: [path.join(root, 'engine', 'protonx')],
    installer: { command: 'powershell.exe', args: ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script] },
  };
}

function target() {
  switch (process.platform) {
    case 'linux':
      return unixTarget({ command: 'bash', args: [path.join(PACKAGE_ROOT, 'cli', 'install-linux.sh')] });
    case 'darwin':
      return unixTarget(null);
    case 'win32':
      return windowsTarget();
    default:
      return null;
  }
}

function installedVersion(where) {
  try {
    return fs.readFileSync(where.versionFile, 'utf8').trim();
  } catch {
    return null;
  }
}

function older(installed, wanted) {
  const a = installed.split('.').map(Number);
  const b = wanted.split('.').map(Number);
  for (let index = 0; index < 3; index += 1) {
    if ((a[index] || 0) !== (b[index] || 0)) return (a[index] || 0) < (b[index] || 0);
  }
  return false;
}

function ask(question) {
  const prompt = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => {
    prompt.question(question, (answer) => {
      prompt.close();
      resolve(!/^n/i.test(answer.trim()));
    });
  });
}

function runInstaller(where) {
  const result = spawnSync(where.installer.command, where.installer.args, { stdio: 'inherit' });
  if (result.error) throw result.error;
  return result.status === 0;
}

async function ensureEngine(where, forced) {
  const installed = installedVersion(where);
  const current = installed && fs.existsSync(where.command) && !older(installed, VERSION);
  if (current && !forced) return true;
  if (!where.installer) {
    if (installed) return true;
    console.error(`On macOS the protonx CLI ships with the ProtonX app. Install both with:\n  ${MAC_INSTALL}`);
    return false;
  }
  const reason = installed ? `protonx needs to update its engine from ${installed} to ${VERSION}.` : 'protonx needs a one-time setup on this machine.';
  const needs = process.platform === 'linux'
    ? 'This installs a small root helper (systemd service) that starts and stops the WireGuard tunnel, and asks for your sudo password.'
    : 'This installs a private Python environment and, if missing, WireGuard for Windows.';
  if (!forced) {
    if (!process.stdin.isTTY) {
      console.error(`${reason} Run "protonx setup" in a terminal first.`);
      return false;
    }
    console.log(`${reason}\n${needs}`);
    if (!(await ask('Continue? [Y/n] '))) return false;
  }
  return runInstaller(where);
}

function launch(where, args) {
  const child = spawn(where.command, [...where.args, ...args], { stdio: 'inherit' });
  process.on('SIGINT', () => {});
  process.on('SIGTERM', () => child.kill('SIGTERM'));
  child.on('error', (error) => {
    console.error(`protonx: could not start the engine: ${error.message}`);
    process.exit(1);
  });
  child.on('exit', (code, signal) => process.exit(signal ? 128 + (os.constants.signals[signal] || 1) : code ?? 1));
}

async function main() {
  const where = target();
  if (!where) {
    console.error(`protonx does not support ${process.platform}.`);
    process.exit(1);
  }
  const args = process.argv.slice(2);
  const setup = args[0] === 'setup';
  if (!(await ensureEngine(where, setup))) process.exit(1);
  if (setup) process.exit(0);
  launch(where, args);
}

main().catch((error) => {
  console.error(`protonx: ${error.message}`);
  process.exit(1);
});
