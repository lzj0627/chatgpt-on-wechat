import requests
import os
from config import conf


class CloudFlareR2:
    
    R2_ENDPOINT = "https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets/{bucket_name}/objects"
    
    def __init__(self) -> None:
        cf_id = conf().get("cloud_flare_id")
        bucket_name = conf().get("r2_bucket_name")
        cf_api_key = conf().get("cf_api_key")
        if conf().get('r2_base_url', '').endswith('/'):
            self.R2_BASE_URL = conf().get('r2_base_url')
        else:
            self.R2_BASE_URL = conf().get('r2_base_url') + '/'
        if cf_id:
            self.ACCOUNT_ID = cf_id
        # 你的R2存储桶名称
        if bucket_name:
            self.BUCKET_NAME = bucket_name
        # 你的Cloudflare API令牌
        if cf_api_key:
            self.API_TOKEN = cf_api_key
        
    def is_valid(self):
        valid_dict = {
            "cloud_flare_id": "ACCOUNT_ID",
            "r2_bucket_name": "BUCKET_NAME",
            "cf_api_key": "API_TOKEN",
            "r2_base_url": "R2_BASE_URL"
        }
        for v in valid_dict.values():
            if not getattr(self, v, None):
                return False
        return True
    
    def to_r2(self, file_path=''):
        url = self.R2_ENDPOINT.format(account_id=self.ACCOUNT_ID, bucket_name=self.BUCKET_NAME)
        with open(file_path, 'rb') as file:
            file_content = file.read()
        # 设置请求头
        headers = {
            "Authorization": f"Bearer {self.API_TOKEN}",
            "Tus-Resumable": "1.0.0",
        }
        file_name = file_path.rsplit(os.sep, 1)[-1]
        # 发送PUT请求上传文件
        response = requests.put(
            f"{url}/{file_name}",  # 文件在R2中的路径
            headers=headers,
            data=file_content
        )
        if response.status_code == 200:
            return self.R2_BASE_URL + file_name
        else:
            print(f"文件上传失败: {response.status_code} {response.text}")