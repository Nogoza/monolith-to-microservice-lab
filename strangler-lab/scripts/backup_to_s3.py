import os
import subprocess
import datetime
from pathlib import Path
import boto3
from botocore.client import Config

# 1. Konfigürasyonu .env veya ortam değişkenlerinden oku
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

config = {}
if ENV_FILE.exists():
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()

S3_ENDPOINT = config.get("S3_ENDPOINT_URL", os.getenv("S3_ENDPOINT_URL", "https://pvos-tr-ist-01.portvmind.com"))
S3_ACCESS_KEY = config.get("S3_ACCESS_KEY", os.getenv("S3_ACCESS_KEY"))
S3_SECRET_KEY = config.get("S3_SECRET_KEY", os.getenv("S3_SECRET_KEY"))
S3_BUCKET = config.get("S3_BUCKET_NAME", os.getenv("S3_BUCKET_NAME", "django-db-backups"))
S3_REGION = config.get("S3_REGION", os.getenv("S3_REGION", "tr-ist-01"))

# 2. Yerel yedek klasörü hazırla
BACKUP_DIR = BASE_DIR / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup_filename = f"storefront_backup_{timestamp}.dump"
backup_filepath = BACKUP_DIR / backup_filename

print("==================================================")
print("🚀 PortvMind Cloud - PostgreSQL Yedekleme Başlıyor")
print("==================================================")

# 3. Docker içindeki PostgreSQL'den pg_dump ile yedek al
print(f"📦 [1/3] Veritabanı yedeği alınıyor -> {backup_filename}...")
cmd = [
    "docker", "exec", "strangler-lab-db-1",
    "pg_dump", "-U", "storefront", "-d", "storefront", "-Fc"
]

try:
    with open(backup_filepath, "wb") as f:
        subprocess.run(cmd, stdout=f, check=True)
    file_size_mb = backup_filepath.stat().st_size / (1024 * 1024)
    print(f"✅ [1/3] Yedek başarıyla alındı! Boyut: {file_size_mb:.2f} MB")
except Exception as e:
    print(f"❌ HATA: pg_dump başarısız oldu: {e}")
    exit(1)

# 4. vMind S3 Object Storage'a bağlan ve yükle
print(f"☁️ [2/3] PortvMind S3 ({S3_BUCKET}) kovasına yükleniyor...")
s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    region_name=S3_REGION,
    config=Config(s3={"addressing_style": "path"})
)

try:
    s3.upload_file(str(backup_filepath), S3_BUCKET, backup_filename)
    print(f"✅ [2/3] Dosya başarıyla yüklendi: s3://{S3_BUCKET}/{backup_filename}")
except Exception as e:
    print(f"❌ HATA: S3 yükleme başarısız: {e}")
    exit(1)

# 5. Kova içindeki nesneleri listele ve doğrula
print("🔍 [3/3] Kova içeriği doğrulanıyor...")
response = s3.list_objects_v2(Bucket=S3_BUCKET)
if "Contents" in response:
    print(f"🎉 Buluttaki Toplam Yedek Sayısı: {len(response['Contents'])}")
    for obj in response["Contents"]:
        print(f"   - {obj['Key']} ({obj['Size'] / (1024*1024):.2f} MB - {obj['LastModified']})")

print("==================================================")
print("🎉 YEDEKLEME BAŞARIYLA TAMAMLANDI!")
print("==================================================")