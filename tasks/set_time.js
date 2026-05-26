const fs = require('fs');
const path = require('path');
const readline = require('readline');

const CONFIG_PATH = path.join(__dirname, 'config.json');

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

function loadConfig() {
  try {
    const content = fs.readFileSync(CONFIG_PATH, 'utf-8');
    return JSON.parse(content);
  } catch {
    return {
      schedule: { hour: 0, minute: 0, second: 0 },
      scripts: {
        downloader: '../tools/tdl_downloader/tdl_downloader_v2.py',
        uploader: '../tools/uploader/uploader.py'
      },
      logging: { enabled: true, logFile: '../logs/scheduler.log' }
    };
  }
}

function saveConfig(config) {
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2), 'utf-8');
}

function askHour() {
  rl.question('请输入执行时间（小时，0-23）: ', (hourInput) => {
    const hour = parseInt(hourInput);
    if (isNaN(hour) || hour < 0 || hour > 23) {
      console.log('无效的小时数，请输入 0-23 之间的数字');
      askHour();
      return;
    }
    
    askMinute(hour);
  });
}

function askMinute(hour) {
  rl.question('请输入执行时间（分钟，0-59）: ', (minuteInput) => {
    const minute = parseInt(minuteInput);
    if (isNaN(minute) || minute < 0 || minute > 59) {
      console.log('无效的分钟数，请输入 0-59 之间的数字');
      askMinute(hour);
      return;
    }
    
    askSecond(hour, minute);
  });
}

function askSecond(hour, minute) {
  rl.question('请输入执行时间（秒，0-59，默认0）: ', (secondInput) => {
    const second = secondInput.trim() ? parseInt(secondInput) : 0;
    if (isNaN(second) || second < 0 || second > 59) {
      console.log('无效的秒数，请输入 0-59 之间的数字');
      askSecond(hour, minute);
      return;
    }
    
    const config = loadConfig();
    config.schedule = { hour, minute, second };
    saveConfig(config);
    
    console.log('');
    console.log('=============================');
    console.log('  定时时间设置成功！');
    console.log('=============================');
    console.log(`  每日执行时间: ${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}:${second.toString().padStart(2, '0')}`);
    console.log('=============================');
    console.log('');
    console.log('现在双击 start_scheduler.bat 启动定时任务');
    console.log('');
    
    rl.close();
  });
}

console.log('');
console.log('=============================');
console.log('    设置每日定时任务时间');
console.log('=============================');
console.log('');

const currentConfig = loadConfig();
const { hour, minute, second } = currentConfig.schedule;
console.log(`当前设置: ${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}:${second.toString().padStart(2, '0')}`);
console.log('');

askHour();