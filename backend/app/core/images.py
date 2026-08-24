import io
from PIL import Image

# Mitigate decompression bombs
Image.MAX_IMAGE_PIXELS = 10_000_000

# Constants
MAX_WIDTH = 2048
MAX_HEIGHT = 2048
MAX_TOTAL_PIXELS = 10_000_000
MAX_BYTES = 5 * 1024 * 1024  # 5MB

ALLOWED_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp"
}

class ImageValidationError(Exception):
    pass

def process_image(data: bytes) -> tuple[str, bytes]:
    """
    Validates and normalizes an image buffer.
    Never trusts client MIME types. Parses magic bytes.
    Enforces pixel and byte limits.
    Returns (server_validated_mime_type, normalized_bytes).
    """
    if len(data) > MAX_BYTES:
        raise ImageValidationError("Image exceeds maximum allowed size (5MB).")

    try:
        # Load image via Pillow (which parses magic bytes)
        with Image.open(io.BytesIO(data)) as img:
            img_format = img.format
            if img_format not in ALLOWED_FORMATS:
                raise ImageValidationError(f"Unsupported image format: {img_format}. Allowed: JPEG, PNG, WEBP.")

            # Image.open only identifies the image. Load() prevents partial file attacks.
            img.load()
            
            # Check dimensions/pixels
            if img.width * img.height > MAX_TOTAL_PIXELS:
                raise ImageValidationError("Image exceeds maximum allowed pixel count.")

            # Resize if necessary (preserve aspect ratio)
            if img.width > MAX_WIDTH or img.height > MAX_HEIGHT:
                img.thumbnail((MAX_WIDTH, MAX_HEIGHT), Image.Resampling.LANCZOS)
                
                # Save normalized back to bytes
                out = io.BytesIO()
                # Use original format or default to JPEG if something is weird
                save_format = img_format if img_format else "JPEG"
                if save_format == "JPEG" and img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(out, format=save_format)
                out_bytes = out.getvalue()
                
                return ALLOWED_FORMATS[save_format], out_bytes

            # If no resize needed, we can return the original bytes (or the cleanly parsed bytes)
            # Returning cleanly parsed bytes ensures no malicious trailing data
            out = io.BytesIO()
            save_format = img_format if img_format else "JPEG"
            if save_format == "JPEG" and img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(out, format=save_format)
            
            return ALLOWED_FORMATS[save_format], out.getvalue()

    except Image.DecompressionBombError:
        raise ImageValidationError("Image decompression bomb detected.")
    except Exception as e:
        if isinstance(e, ImageValidationError):
            raise e
        raise ImageValidationError("Invalid image data.") from e
