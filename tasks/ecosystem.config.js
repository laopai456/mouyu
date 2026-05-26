module.exports = {
  apps: [
    {
      name: 'mouyu-scheduler',
      script: 'scheduler.js',
      cwd: __dirname,
      watch: false,
      ignore_watch: ['node_modules', '.git'],
      instances: 1,
      exec_mode: 'fork',
      max_memory_restart: '1G',
      env: {
        NODE_ENV: 'production'
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: '../logs/scheduler-error.log',
      out_file: '../logs/scheduler-out.log',
      merge_logs: true,
      autorestart: true,
      restart_delay: 5000
    }
  ]
};