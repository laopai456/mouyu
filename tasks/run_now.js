const { exec } = require('child_process');
const path = require('path');
const fs = require('fs');

const PYTHON_PATH = path.join(__dirname, '../.venv/Scripts/python.exe');
const DOWNLOADER_PATH = path.join(__dirname, '../tools/tdl_downloader/tdl_downloader_v2.py');
const UPLOADER_PATH = path.join(__dirname, '../tools/uploader/uploader.py');
const LOG_FILE = path.join(__dirname, '../logs/scheduler.log');

function log(message) {
  const timestamp = new Date().toLocaleString('zh-CN');
  const logMsg = `[${timestamp}] ${message}`;
  console.log(logMsg);
  fs.appendFileSync(LOG_FILE, logMsg + '\n', 'utf-8');
}

function runScript(scriptPath, extraArgs = '') {
  return new Promise((resolve, reject) => {
    const scriptName = path.basename(scriptPath);
    log(`开始执行: ${scriptName}`);
    
    const command = extraArgs 
      ? `"${PYTHON_PATH}" "${scriptPath}" ${extraArgs}`
      : `"${PYTHON_PATH}" "${scriptPath}"`;
    
    const child = exec(command, (error, stdout, stderr) => {
      if (error) {
        log(`执行失败 [${scriptName}]: ${error.message}`);
        reject(error);
      } else {
        log(`执行成功 [${scriptName}]`);
        resolve(stdout);
      }
    });

    child.stdout.on('data', (data) => {
      const lines = data.trim().split('\n');
      lines.forEach(line => {
        if (line.trim()) log(`[${scriptName}] ${line.trim()}`);
      });
    });

    child.stderr.on('data', (data) => {
      const lines = data.trim().split('\n');
      lines.forEach(line => {
        if (line.trim()) log(`[${scriptName} ERROR] ${line.trim()}`);
      });
    });
  });
}

async function main() {
  log('=== 手动触发任务 ===');
  
  try {
    log('1. 执行下载器...');
    await runScript(DOWNLOADER_PATH, '--auto');
    
    log('2. 执行上传器...');
    await runScript(UPLOADER_PATH);
    
    log('=== 任务完成 ===');
  } catch (err) {
    log(`任务执行失败: ${err.message}`);
  }
}

main();