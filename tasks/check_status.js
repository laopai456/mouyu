const fs = require('fs');
const path = require('path');

console.log('');
console.log('=============================');
console.log('    定时任务状态检查');
console.log('=============================');
console.log('');

const tasksDir = __dirname;
const logsDir = path.join(__dirname, '../logs');
const configPath = path.join(tasksDir, 'config.json');
const logFile = path.join(logsDir, 'scheduler.log');

console.log('1. 检查配置文件...');
if (fs.existsSync(configPath)) {
  const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
  const { hour, minute, second } = config.schedule;
  console.log(`   ✓ 配置文件存在`);
  console.log(`   └─ 定时时间: ${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}:${second.toString().padStart(2, '0')}`);
} else {
  console.log('   ✗ 配置文件不存在');
}

console.log('');
console.log('2. 检查依赖...');
if (fs.existsSync(path.join(tasksDir, 'node_modules', 'node-schedule'))) {
  console.log('   ✓ node-schedule 已安装');
} else {
  console.log('   ✗ node-schedule 未安装');
  console.log('     请运行: npm install');
}

console.log('');
console.log('3. 检查日志目录...');
if (fs.existsSync(logsDir)) {
  console.log('   ✓ 日志目录存在');
} else {
  console.log('   ✗ 日志目录不存在');
  console.log('     首次运行时会自动创建');
}

console.log('');
console.log('4. 检查日志文件...');
if (fs.existsSync(logFile)) {
  console.log('   ✓ 日志文件存在');
  console.log('   └─ 日志内容:');
  
  const content = fs.readFileSync(logFile, 'utf-8');
  const lines = content.split('\n').filter(line => line.trim());
  
  if (lines.length > 0) {
    const lastLines = lines.slice(-10);
    lastLines.forEach(line => {
      console.log('      ', line);
    });
    
    if (lines.length > 10) {
      console.log('      ... (还有更多日志)');
    }
  } else {
    console.log('      (日志为空)');
  }
} else {
  console.log('   ✗ 日志文件不存在');
  console.log('     定时任务可能尚未运行');
}

console.log('');
console.log('=============================');
console.log('    测试运行');
console.log('=============================');
console.log('');

const readline = require('readline');
const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

rl.question('是否立即测试运行一次任务？(y/n): ', (answer) => {
  if (answer.toLowerCase() === 'y') {
    console.log('');
    console.log('正在执行测试...');
    console.log('');
    
    const { exec } = require('child_process');
    const PYTHON_PATH = path.join(__dirname, '../.venv/Scripts/python.exe');
    const DOWNLOADER_PATH = path.join(__dirname, '../tools/tdl_downloader/tdl_downloader_v2.py');
    
    const child = exec(`"${PYTHON_PATH}" "${DOWNLOADER_PATH}"`, (error, stdout, stderr) => {
      if (error) {
        console.log('测试失败:', error.message);
      } else {
        console.log('测试成功!');
        console.log('输出:', stdout.trim());
      }
      rl.close();
    });

    child.stdout.on('data', (data) => {
      console.log('[STDOUT]', data.trim());
    });

    child.stderr.on('data', (data) => {
      console.log('[STDERR]', data.trim());
    });
    
  } else {
    console.log('');
    console.log('测试已取消');
    rl.close();
  }
});