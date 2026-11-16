import io
import logging
import urllib.parse
import uuid
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

logger = logging.getLogger(__name__)


class MinioSnapshotService:
    """Service untuk mengunggah dan mengelola snapshot gambar halaman PDF ke MinIO."""

    def __init__(self) -> None:
        self._client: Minio | None = None
        self._initialized_bucket: bool = False

    def _get_client(self) -> Minio | None:
        if not settings.MINIO_ENABLED:
            return None

        if self._client is None:
            if not settings.MINIO_ENDPOINT or not settings.MINIO_ACCESS_KEY:
                logger.warning("MinIO endpoint atau access key belum dikonfigurasi.")
                return None

            self._client = Minio(
                endpoint=settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
                region=settings.MINIO_REGION,
            )
        return self._client

    def _ensure_bucket(self, client: Minio) -> None:
        if self._initialized_bucket:
            return

        bucket = settings.normalized_minio_bucket
        try:
            if not client.bucket_exists(bucket):
                logger.info("Membuat bucket MinIO private: %s...", bucket)
                client.make_bucket(bucket)

            # Bucket dibiarkan private (tanpa anonymous read) untuk menjaga keamanan dokumen perusahaan
            self._initialized_bucket = True
        except S3Error as exc:
            logger.warning("MinIO bucket check: %s", exc)
            self._initialized_bucket = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal memastikan bucket MinIO %s: %s", bucket, exc)

    def upload_page_snapshot(
        self,
        knowledge_id: uuid.UUID,
        document_id: uuid.UUID,
        page_number: int,
        image_bytes: bytes,
    ) -> str | None:
        """Mengunggah snapshot gambar halaman PDF ke MinIO (private) dan mengembalikan object_name."""
        client = self._get_client()
        if client is None:
            return None

        self._ensure_bucket(client)
        bucket = settings.normalized_minio_bucket
        prefix = settings.MINIO_FOLDER_PREFIX.strip("/")
        object_name = (
            f"{prefix}/{knowledge_id}/{document_id}/page_{page_number}.png"
            if prefix
            else f"{knowledge_id}/{document_id}/page_{page_number}.png"
        )

        try:
            client.put_object(
                bucket_name=bucket,
                object_name=object_name,
                data=io.BytesIO(image_bytes),
                length=len(image_bytes),
                content_type="image/png",
            )
            return object_name
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Gagal mengunggah snapshot halaman %d (%s) ke MinIO: %s",
                page_number,
                document_id,
                exc,
            )
            return None

    def extract_object_name(self, object_name_or_url: str) -> str:
        """Mengekstrak object name dari URL MinIO atau mengembalikannya jika sudah berupa path."""
        bucket = settings.normalized_minio_bucket
        if "://" in object_name_or_url:
            parsed = urllib.parse.urlparse(object_name_or_url)
            path = parsed.path.lstrip("/")
            if path.startswith(f"{bucket}/"):
                return path[len(bucket) + 1 :]
            return path
        return object_name_or_url.lstrip("/")

    def get_presigned_url(
        self,
        object_name_or_url: str | None,
        expires_seconds: int | None = None,
    ) -> str | None:
        """Membuat Presigned URL bertanda tangan (HMAC-SHA256) sementara untuk akses aman ke objek private."""
        if not object_name_or_url:
            return None

        client = self._get_client()
        if client is None:
            return None

        bucket = settings.normalized_minio_bucket
        object_name = self.extract_object_name(object_name_or_url)
        if not object_name:
            return None

        expiry = timedelta(seconds=expires_seconds or settings.MINIO_PRESIGNED_EXPIRY_SECONDS)
        try:
            return client.presigned_get_object(bucket, object_name, expires=expiry)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Gagal membuat presigned URL untuk objek %s di MinIO: %s",
                object_name,
                exc,
            )
            return None

    def delete_document_snapshots(
        self, knowledge_id: uuid.UUID, document_id: uuid.UUID
    ) -> None:
        """Menghapus seluruh file snapshot gambar suatu dokumen dari MinIO."""
        client = self._get_client()
        if client is None:
            return

        bucket = settings.normalized_minio_bucket
        prefix = settings.MINIO_FOLDER_PREFIX.strip("/")
        folder = (
            f"{prefix}/{knowledge_id}/{document_id}/"
            if prefix
            else f"{knowledge_id}/{document_id}/"
        )

        try:
            objects = client.list_objects(bucket, prefix=folder, recursive=True)
            for obj in objects:
                client.remove_object(bucket, obj.object_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal menghapus snapshot MinIO untuk dokumen %s: %s", document_id, exc)

    def delete_knowledge_snapshots(self, knowledge_id: uuid.UUID) -> None:
        """Menghapus seluruh file snapshot gambar suatu knowledge dari MinIO."""
        client = self._get_client()
        if client is None:
            return

        bucket = settings.normalized_minio_bucket
        prefix = settings.MINIO_FOLDER_PREFIX.strip("/")
        folder = (
            f"{prefix}/{knowledge_id}/"
            if prefix
            else f"{knowledge_id}/"
        )

        try:
            objects = client.list_objects(bucket, prefix=folder, recursive=True)
            for obj in objects:
                client.remove_object(bucket, obj.object_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal menghapus snapshot MinIO untuk knowledge %s: %s", knowledge_id, exc)


minio_service = MinioSnapshotService()
