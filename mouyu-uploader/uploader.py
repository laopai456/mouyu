import os
import sys
import time
import json
import hashlib
import logging
import hmac
import base64
import hashlib as sha256
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from qcloud_cos import CosConfig
from qcloud_cos import CosS3Client
import requests

class ImageUploader(FileSystemEventHandler):
    def __init__(self, config):
        self.config = config
        self.env_id = config['env_id']
        self.developer_openid = config['developer_openid']
        self.md5_cache_file = Path(__file__).parent / 'cache' / 'md5_cache.json'
        self.md5_cache = self.load_md5_cache()
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
            config = CosConfig(
                Region=self.region,
                SecretId=self.secret_id,
                SecretKey=self.secret_key
            )
            self.client = CosS3Client(config)
            self.logger.info("COS 客户端初始化成功")
        else:
            self.client = None
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
            self.logger.info(f"检测到新图片: {file_path}")
            time.sleep(self.config['upload_delay'])
            self.upload_image(file_path)
    
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
        try:
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
            else:
                self.logger.error(f"数据库写入失败: {db_result.get('message', '未知错误')}")
                
        except Exception as e:
            self.logger.error(f"处理图片失败 {file_path}: {str(e)}")
    
    def upload_to_cos(self, cloud_path, file_content):
        try:
            if self.client and self.bucket:
                response = self.client.put_object(
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
    
    def sign_tencent_cloud(self, payload, service='scf'):
        algorithm = 'TC3-HMAC-SHA256'
        timestamp = int(time.time())
        date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
        
        http_request_method = 'POST'
        canonical_uri = '/'
        canonical_querystring = ''
        ct = 'application/json'
        canonical_headers = f'content-type:{ct}\nhost:{service}.tencentcloudapi.com\n'
        signed_headers = 'content-type;host'
        
        hashed_request_payload = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        canonical_request = f'{http_request_method}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{hashed_request_payload}'
        
        credential_scope = f'{date}/{service}/tc3_request'
        hashed_canonical_request = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
        string_to_sign = f'{algorithm}\n{timestamp}\n{credential_scope}\n{hashed_canonical_request}'
        
        def hmac_sha256(key, msg):
            return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()
        
        secret_date = hmac_sha256(('TC3' + self.secret_key).encode('utf-8'), date)
        secret_service = hmac_sha256(secret_date, service)
        secret_signing = hmac_sha256(secret_service, 'tc3_request')
        signature = hmac.new(secret_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
        
        authorization = f'{algorithm} Credential={self.secret_id}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}'
        
        return {
            'Authorization': authorization,
            'X-TC-Timestamp': str(timestamp),
            'X-TC-Version': '2018-04-16',
            'X-TC-Action': 'InvokeFunction',
            'X-TC-Region': self.region
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
            
            payload = json.dumps({
                'FunctionName': 'autoUpload',
                'Namespace': self.env_id,
                'Event': json.dumps(event_data, ensure_ascii=False)
            })
            
            headers = self.sign_tencent_cloud(payload, 'scf')
            headers['Content-Type'] = 'application/json'
            headers['Host'] = 'scf.tencentcloudapi.com'
            
            response = requests.post(
                'https://scf.tencentcloudapi.com/',
                headers=headers,
                data=payload,
                timeout=30
            )
            
            result = response.json()
            
            if result.get('Response', {}).get('Error'):
                error = result['Response']['Error']
                self.logger.error(f"API 错误: {error}")
                return {'success': False, 'message': error.get('Message', 'Unknown error')}
            
            self.logger.info(f"云函数调用成功: {result.get('Response', {}).get('Result', '')}")
            return {'success': True}
            
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
