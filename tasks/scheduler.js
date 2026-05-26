const schedule = require('node-schedule');
const { exec } = require('child_process');
const path = require('path');
const fs = require('fs');

const CONFIG_PATH = path.join(__dirname, 'config.json');

let config = {
  schedule: { hour: 0, minute: 0, second: 0 },
  scripts: {
    downloader: '../tools/tdl_downloader/tdl_downloader_v2.py',
    uploader: '../tools/uploader/uploader.py'
  },
  logging: { enabled: true, logFile: '../logs/scheduler.log' }
};

function loadConfig() {
  try {
    const content = fs.readFileSync(CONFIG_PATH, 'utf-8');
    config = JSON.parse(content);
    console.log('配置加载成功');
  } catch (err) {
    console.log('使用默认配置');
  }
}

function log(message) {
  const timestamp = new Date().toLocaleString('zh-CN');
  const logMsg = `[${timestamp}] ${message}`;
  console.log(logMsg);
  
  if (config.logging.enabled && config.logging.logFile) {
    const logPath = path.join(__dirname, config.logging.logFile);
    fs.appendFileSync(logPath, logMsg + '\n', 'utf-8');
  }
}

const PYTHON_PATH = path.join(__dirname, '../.venv/Scripts/python.exe');
const DOWNLOADER_PATH = path.join(__dirname, '../tools/tdl_downloader/tdl_downloader_v2.py');
const UPLOADER_PATH = path.join(__dirname, '../tools/uploader/uploader.py');

function runScript(scriptPath, extraArgs = '') {
  return new Promise((resolve, reject) => {
    const scriptName = path.basename(scriptPath);
    log(`开始执行: ${scriptName}`);
    
    const command = extraArgs 
      ? `"${PYTHON_PATH}" "${scriptPath}" ${extraArgs}`
      : `"${PYTHON_PATH}" "${scriptPath}"`;
    
    const child = exec(command, { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }, (error, stdout, stderr) => {
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

async function dailyTask() {
  log('=== 开始每日定时任务 ===');
  
  try {
    log('1. 执行下载器...');
    await runScript(DOWNLOADER_PATH, '--auto');
    
    log('2. 执行上传器...');
    await runScript(UPLOADER_PATH);
    
    log('=== 每日定时任务完成 ===');
  } catch (err) {
    log(`每日任务执行失败: ${err.message}`);
  }
}

function startScheduler() {
  loadConfig();
  
  const { hour, minute, second } = config.schedule;
  
  log(`定时任务调度器已启动`);
  log(`每日任务时间: ${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}:${second.toString().padStart(2, '0')}`);
  log('按 Ctrl+C 停止');
  log('');

  const cronExpression = `${second} ${minute} ${hour} * * *`;
  const dailyJob = schedule.scheduleJob(cronExpression, dailyTask);

  process.on('SIGINT', () => {
    log('正在停止定时任务...');
    dailyJob.cancel();
    process.exit(0);
  });

  process.on('SIGTERM', () => {
    log('正在停止定时任务...');
    dailyJob.cancel();
    process.exit(0);
  });
}

startScheduler();