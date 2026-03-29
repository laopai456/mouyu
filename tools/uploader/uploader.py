import os
import sys
import time
import json
import hashlib
import logging
import threading
from datetime import datetime
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from qcloud_cos import CosConfig
from qcloud_cos import CosS3Client
from tencentcloud.common import credential
from tencentcloud.scf.v20180416 import scf_client, models

class ImageUploader(FileSystemEventHandler):
    def __init__(self, config):
        self.config = config
        self.env_id = config['env_id']
        self.developer_openid = config['developer_openid']
        self.md5_cache_file = Path(__file__).parent / 'cache' / 'md5_cache.json'
        self.md5_cache = self.load_md5_cache()
        self.processing_files = set()
        self.processing_lock = threading.Lock()
        self.setup_logging()
        self.setup_cos_client()
        
    def setup_logging(self):
        log_dir = Path(__file__).parent / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / 'upload.log', encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def setup_cos_client(self):
        cos_config = self.config.get('cos', {})
        self.bucket = cos_config.get('bucket', '')
        self.region = cos_config.get('region', 'ap-shanghai')
        
        self.secret_id = os.environ.get('TENCENT_SECRET_ID') or cos_config.get('secret_id', '')
        self.secret_key = os.environ.get('TENCENT_SECRET_KEY') or cos_config.get('secret_key', '')
        
        if self.secret_id and self.secret_key:
            cos_conf = CosConfig(
                Region=self.region,
                SecretId=self.secret_id,
                SecretKey=self.secret_key
            )
            self.cos_client = CosS3Client(cos_conf)
            self.logger.info("COS 客户端初始化成功")
            
            scf_cred = credential.Credential(self.secret_id, self.secret_key)
            self.scf_client = scf_client.ScfClient(scf_cred, self.region)
            self.logger.info("SCF 客户端初始化成功")
        else:
            self.cos_client = None
            self.scf_client = None
            self.logger.warning("未配置 COS 密钥，请设置环境变量 TENCENT_SECRET_ID 和 TENCENT_SECRET_KEY")
            self.logger.warning("或在 config.json 中配置 secret_id 和 secret_key")
        
    def load_md5_cache(self):
        if self.md5_cache_file.exists():
            try:
                with open(self.md5_cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_md5_cache(self):
        self.md5_cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.md5_cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.md5_cache, f, ensure_ascii=False, indent=2)
    
    def on_created(self, event):
        if event.is_directory:
            return
        
        file_path = event.src_path
        if self.is_image(file_path):
            with self.processing_lock:
                if file_path in self.processing_files:
                    self.logger.info(f"文件正在处理中，跳过: {file_path}")
                    return
                self.processing_files.add(file_path)
            
            self.logger.info(f"检测到新图片: {file_path}")
            threading.Thread(target=self._upload_with_delay, args=(file_path,), daemon=True).start()
    
    def _upload_with_delay(self, file_path):
        time.sleep(self.config['upload_delay'])
        self.upload_image(file_path)
        with self.processing_lock:
            self.processing_files.discard(file_path)
    
    def is_image(self, file_path):
        ext = Path(file_path).suffix.lower().lstrip('.')
        return ext in self.config['file_types']
    
    def calculate_md5(self, file_path):
        hash_md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    def upload_image(self, file_path):
        max_retries = self.config.get('max_retry', 3)
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                if not os.path.exists(file_path):
                    if attempt < max_retries - 1:
                        self.logger.warning(f"文件不存在，{retry_delay}秒后重试 ({attempt + 1}/{max_retries}): {file_path}")
                        time.sleep(retry_delay)
                        continue
                    else:
                        self.logger.warning(f"文件不存在，跳过: {file_path}")
                        return
                
                if not os.path.isfile(file_path):
                    if attempt < max_retries - 1:
                        self.logger.warning(f"不是有效文件，{retry_delay}秒后重试 ({attempt + 1}/{max_retries}): {file_path}")
                        time.sleep(retry_delay)
                        continue
                    else:
                        self.logger.warning(f"不是有效文件，跳过: {file_path}")
                        return
                
                try:
                    with open(file_path, 'rb') as f:
                        f.read(1)
                except IOError as e:
                    if attempt < max_retries - 1:
                        self.logger.warning(f"文件被占用，{retry_delay}秒后重试 ({attempt + 1}/{max_retries}): {file_path}")
                        time.sleep(retry_delay)
                        continue
                    else:
                        self.logger.warning(f"文件被占用或无法访问，跳过: {file_path} - {e}")
                        return
            
            except Exception as outer_e:
                if attempt < max_retries - 1:
                    self.logger.warning(f"发生错误，{retry_delay}秒后重试 ({attempt + 1}/{max_retries}): {outer_e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    self.logger.error(f"处理图片失败 {file_path}: {str(outer_e)}")
                    return
            
            md5 = self.calculate_md5(file_path)
            
            if md5 in self.md5_cache:
                self.logger.info(f"重复图片，跳过: {file_path}")
                return
            
            self.logger.info(f"开始上传: {file_path}")
            
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            file_name = Path(file_path).name
            now = datetime.now()
            year_month = f"{now.year}-{str(now.month).zfill(2)}"
            cloud_path = f"memes/{year_month}/{int(now.timestamp() * 1000)}_{file_name}"
            
            upload_result = self.upload_to_cos(cloud_path, file_content)
            
            if not upload_result['success']:
                self.logger.error(f"上传失败: {upload_result.get('message', '未知错误')}")
                return
            
            file_id = upload_result['file_id']
            self.logger.info(f"上传成功: {file_id}")
            
            db_result = self.write_to_database(file_id, md5)
            
            if db_result['success']:
                self.md5_cache[md5] = {
                    'file_id': file_id,
                    'upload_time': now.isoformat(),
                    'file_path': file_path
                }
                self.save_md5_cache()
                self.logger.info(f"数据库写入成功，图片已添加到待审核列表")
                
                delete_after_upload = self.config.get('delete_after_upload', False)
                if delete_after_upload:
                    try:
                        os.remove(file_path)
                        self.logger.info(f"已清理本地文件: {file_path}")
                    except Exception as e:
                        self.logger.error(f"清理本地文件失败: {e}")
            else:
                self.logger.error(f"数据库写入失败: {db_result.get('message', '未知错误')}")
            
            return
        
        self.logger.error(f"达到最大重试次数，上传失败: {file_path}")
    
    def upload_to_cos(self, cloud_path, file_content):
        try:
            if self.cos_client and self.bucket:
                response = self.cos_client.put_object(
                    Bucket=self.bucket,
                    Body=file_content,
                    Key=cloud_path
                )
                
                file_id = f"cloud://{self.env_id}.{self.bucket}/{cloud_path}"
                
                return {
                    'success': True,
                    'file_id': file_id
                }
            else:
                file_id = f"cloud://{self.env_id}.simulated/{cloud_path}"
                return {
                    'success': True,
                    'file_id': file_id
                }
        except Exception as e:
            return {
                'success': False,
                'message': str(e)
            }
    
    def write_to_database(self, file_id, md5):
        try:
            now = datetime.now()
            today = now.strftime('%Y-%m-%d')
            year_month = f"{now.year}-{str(now.month).zfill(2)}"
            month = now.month
            
            event_data = {
                'action': 'addImage',
                'fileID': file_id,
                'md5': md5,
                'date': today,
                'yearMonth': year_month,
                'month': month
            }
            
            req = models.InvokeRequest()
            req.FunctionName = 'autoUpload'
            req.Namespace = self.env_id
            req.ClientContext = json.dumps(event_data, ensure_ascii=False)
            
            resp = self.scf_client.Invoke(req)
            ret_msg = json.loads(resp.Result.RetMsg)
            
            if ret_msg.get('success'):
                self.logger.info(f"云函数调用成功: {ret_msg.get('msg', '')}")
                return {'success': True}
            else:
                self.logger.error(f"云函数调用失败: {ret_msg.get('msg', '未知错误')}")
                return {'success': False, 'message': ret_msg.get('msg', 'Unknown error')}
            
        except Exception as e:
            self.logger.error(f"写入数据库异常: {str(e)}")
            return {'success': False, 'message': str(e)}

def main():
    config_file = Path(__file__).parent / 'config.json'
    
    if not config_file.exists():
        print("错误: 配置文件 config.json 不存在")
        input("按回车键退出...")
        return
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception as e:
        print(f"错误: 读取配置文件失败 - {e}")
        input("按回车键退出...")
        return
    
    print("="*50)
    print("自动上传工具启动中...")
    print("="*50)
    print(f"环境 ID: {config['env_id']}")
    print(f"开发者 OpenID: {config['developer_openid']}")
    print()
    
    event_handler = ImageUploader(config)
    observer = Observer()
    
    has_valid_folder = False
    for folder in config['watch_folders']:
        if folder['enabled']:
            watch_path = folder['path']
            print(f"检查文件夹: {watch_path}")
            if os.path.exists(watch_path):
                observer.schedule(event_handler, watch_path, recursive=True)
                print(f"  ✓ 已添加监控")
                has_valid_folder = True
            else:
                print(f"  ✗ 文件夹不存在")
    
    print()
    
    if not has_valid_folder:
        print("错误: 没有有效的监控文件夹")
        input("按回车键退出...")
        return
    
    observer.start()
    
    print("="*50)
    print("扫描现有图片...")
    print("="*50)
    
    for folder in config['watch_folders']:
        if folder['enabled']:
            watch_path = folder['path']
            if os.path.exists(watch_path):
                print(f"\n扫描文件夹: {watch_path}")
                image_count = 0
                for root, dirs, files in os.walk(watch_path):
                    for file in files:
                        if event_handler.is_image(file):
                            file_path = os.path.join(root, file)
                            event_handler.upload_image(file_path)
                            image_count += 1
                print(f"  共找到 {image_count} 张图片")
    
    print("\n" + "="*50)
    print("✓ 自动上传工具已启动")
    print("="*50)
    print("监控中... (按 Ctrl+C 停止)")
    print("="*50)
    print()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在停止...")
        observer.stop()
    
    observer.join()
    print("已停止")
    input("按回车键退出...")

if __name__ == "__main__":
    main()
