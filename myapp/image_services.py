import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from io import BytesIO

from PIL import Image, ImageOps
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser

# ============================================================================
# CONFIGURATION & PATH SETUP
# ============================================================================

# Add ImageMagick to PATH (for Windows)
if os.name == 'nt':  # Windows
    # Your specific ImageMagick installation path
    magick_install_path = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI"
    if os.path.exists(magick_install_path):
        os.environ["PATH"] = magick_install_path + os.pathsep + os.environ.get("PATH", "")
        print(f"✓ Added ImageMagick to PATH: {magick_install_path}")
    else:
        print(f"⚠ ImageMagick not found at: {magick_install_path}")

# ============================================================================
# CONSTANTS
# ============================================================================

# إزالة TIFF من قائمة MIME types
IMAGE_MIME_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "gif": "image/gif",
    # تم إزالة "tiff": "image/tiff"
}

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _output_dir():
    """Get or create output directory for processed images"""
    base_dir = getattr(settings, "MEDIA_ROOT", None)
    if not base_dir:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        base_dir = os.path.join(project_root, "media")

    output_dir = os.path.join(base_dir, "image_tools")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _safe_name(name):
    """Create a safe filename"""
    return os.path.basename(name).replace(" ", "_")


def _download_url(request, file_id):
    """Generate download URL for a file"""
    return request.build_absolute_uri(f"/api/image/download/{file_id}/")


def _save_output_bytes(output_bytes, extension):
    """Save bytes to a file and return file_id"""
    file_id = uuid.uuid4().hex
    ext = extension.lower().lstrip(".")
    path = os.path.join(_output_dir(), f"{file_id}.{ext}")

    with open(path, "wb") as f:
        f.write(output_bytes)

    return file_id


def _find_magick_command():
    """Find ImageMagick executable with multiple fallback options"""
    
    # Common ImageMagick executable names
    candidates = [
        "magick",           # ImageMagick 7+
        "convert",          # ImageMagick 6 and older
        "imagemagick",      # Some installations
        "magick.exe",       # Windows
        "convert.exe",      # Windows
    ]
    
    # Check if in PATH
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            print(f"✓ Found ImageMagick: {resolved}")
            return resolved
    
    # Common installation paths for Windows
    if os.name == 'nt':  # Windows
        # Common ImageMagick installation paths
        program_files = [
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
        ]
        
        for pf in program_files:
            # Look for ImageMagick directories
            if os.path.exists(pf):
                for item in os.listdir(pf):
                    if item.startswith("ImageMagick"):
                        magick_exe = os.path.join(pf, item, "magick.exe")
                        convert_exe = os.path.join(pf, item, "convert.exe")
                        
                        if os.path.exists(magick_exe):
                            print(f"✓ Found ImageMagick at: {magick_exe}")
                            return magick_exe
                        elif os.path.exists(convert_exe):
                            print(f"✓ Found ImageMagick at: {convert_exe}")
                            return convert_exe
        
        # Specific paths as fallback
        common_paths = [
            r"C:\Program Files\ImageMagick-7.1.2-13-Q16-HDRI-x64-dll\magick.exe",
            r"C:\Program Files\ImageMagick-7.1.2-13-Q16-HDRI-x64-dll\convert.exe",
            r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe",
            r"C:\Program Files\ImageMagick-7.0.10-Q16\magick.exe",
            r"C:\Program Files\ImageMagick-6.9.11-Q16\convert.exe",
            r"C:\Program Files (x86)\ImageMagick-6.9.3-Q16\convert.exe",
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                print(f"✓ Found ImageMagick at: {path}")
                return path
    
    # Common paths for Linux/Mac
    common_paths = [
        "/usr/bin/convert",
        "/usr/local/bin/convert",
        "/opt/local/bin/convert",
        "/usr/bin/magick",
        "/usr/local/bin/magick",
        "/opt/local/bin/magick",
    ]
    
    for path in common_paths:
        if os.path.exists(path):
            print(f"✓ Found ImageMagick at: {path}")
            return path
    
    print("✗ ImageMagick not found")
    return None


def _run_magick_convert(
    input_path,
    output_path,
    output_ext,
    quality,
    resize_enabled,
    width,
    height,
    maintain_aspect_ratio,
):
    """Run ImageMagick conversion with proper error handling"""
    
    magick = _find_magick_command()
    if not magick:
        return "ImageMagick not found. Please install ImageMagick and ensure it's in PATH."

    # Build the command
    args = [magick, input_path, "-auto-orient"]

    # Add resize parameters if enabled
    if resize_enabled and width > 0 and height > 0:
        geometry = f"{width}x{height}"
        if maintain_aspect_ratio:
            geometry = f"{geometry}>"  # Only shrink if larger
        else:
            geometry = f"{geometry}!"  # Force exact size
        args.extend(["-resize", geometry])

    # Add quality/compression settings based on output format
    output_ext = output_ext.lower()
    if output_ext in {"jpg", "jpeg", "webp"}:
        args.extend(["-quality", str(quality)])
    elif output_ext == "png":
        # Convert quality (0-100) to PNG compression level (0-9)
        png_compression = max(0, min(9, int(round((100 - quality) / 11))))
        args.extend(["-define", f"png:compression-level={png_compression}"])
    # تم إزالة قسم TIFF

    # Add output path
    args.append(output_path)

    # Log the command for debugging
    print(f"Running ImageMagick command: {' '.join(args)}")

    # Execute the command
    try:
        result = subprocess.run(
            args, 
            capture_output=True, 
            text=True, 
            timeout=120,
            env=os.environ.copy()  # Pass current environment
        )
    except subprocess.TimeoutExpired:
        return "ImageMagick conversion timed out after 120 seconds."
    except FileNotFoundError:
        return f"ImageMagick executable not found: {magick}"
    except PermissionError:
        return f"Permission denied when trying to execute: {magick}"
    except Exception as exc:
        return f"ImageMagick conversion error: {str(exc)}"

    # Check for errors
    if result.returncode != 0:
        error_msg = result.stderr or result.stdout or "Unknown error"
        return f"ImageMagick conversion failed: {error_msg.strip()}"

    # تحقق من وجود ملف الإخراج
    if not os.path.exists(output_path):
        return "Converted output not found after conversion."

    return None  # No error


def _normalize_output_format(raw_format):
    """Normalize output format string"""
    fmt = (raw_format or "png").lower().strip().lstrip(".")
    if fmt == "jpg":
        fmt = "jpeg"
    
    # التحقق من أن التنسيق مدعوم (TIFF لم يعد مدعوماً)
    if fmt not in IMAGE_MIME_TYPES:
        return None
    
    return fmt


def _compress_level_to_quality(compression_level):
    """Convert compression level (10-90) to quality (10-95)"""
    level = max(10, min(90, compression_level))
    return max(10, min(95, 100 - level))


# ============================================================================
# DEBUG VIEW
# ============================================================================

@api_view(["GET"])
def debug_imagemagick(request):
    """Debug endpoint to check ImageMagick installation"""
    results = {
        "success": True,
        "os_name": os.name,
        "os_details": {
            "name": os.name,
            "platform": os.sys.platform,
            "cwd": os.getcwd(),
        },
        "path_environment": os.environ.get("PATH", "").split(os.pathsep),
        "magick_search_results": [],
        "specific_path_check": {},
        "version_test": None,
        # تم إزالة tiff_support
    }
    
    # Test each candidate
    candidates = ["magick", "convert", "magick.exe", "convert.exe"]
    for candidate in candidates:
        path = shutil.which(candidate)
        results["magick_search_results"].append({
            "candidate": candidate,
            "found": path is not None,
            "path": path
        })
    
    # Check specific installation path
    specific_path = r"C:\Program Files\ImageMagick-7.1.2-13-Q16-HDRI-x64-dll\magick.exe"
    results["specific_path_check"]["path"] = specific_path
    results["specific_path_check"]["exists"] = os.path.exists(specific_path)
    
    if results["specific_path_check"]["exists"]:
        # Try to run a simple command
        try:
            result = subprocess.run(
                [specific_path, "--version"], 
                capture_output=True, 
                text=True, 
                timeout=5,
                env=os.environ.copy()
            )
            results["version_test"] = {
                "success": result.returncode == 0,
                "output": result.stdout[:500] if result.stdout else result.stderr[:500]
            }
            
        except Exception as e:
            results["version_test"] = {
                "success": False,
                "error": str(e)
            }
    
    # Also check using our find function
    magick_cmd = _find_magick_command()
    results["find_magick_command_result"] = magick_cmd
    
    return JsonResponse(results)


# ============================================================================
# MAIN VIEWS
# ============================================================================

@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def convert_image_with_imagemagick(request):
    """
    Convert image using ImageMagick with fallback to PIL if ImageMagick is not available
    """
    # Get the image file
    image_file = request.FILES.get("image_file") or request.FILES.get("file")
    if not image_file:
        return JsonResponse({"success": False, "error": "No image file provided."}, status=400)

    # Parse parameters
    keep_original_format = str(request.POST.get("keep_original_format", "false")).lower() == "true"
    
    # Determine output format
    output_format_raw = request.POST.get("output_format") or "png"
    
    if keep_original_format:
        # Extract original format from filename
        original_ext = image_file.name.split('.')[-1].lower() if '.' in image_file.name else 'png'
        if original_ext == 'jpg':
            original_ext = 'jpeg'
        output_format = _normalize_output_format(original_ext)
    else:
        output_format = _normalize_output_format(output_format_raw)
    
    if not output_format:
        return JsonResponse({"success": False, "error": "Unsupported output format."}, status=400)

    # Parse quality parameter
    try:
        quality = int(request.POST.get("quality", "85"))
    except ValueError:
        quality = 85
    quality = max(10, min(100, quality))

    # Parse resize parameters
    resize_enabled = str(request.POST.get("resize_enabled", "false")).lower() == "true"
    
    try:
        width = int(request.POST.get("width", "0"))
    except ValueError:
        width = 0
    
    try:
        height = int(request.POST.get("height", "0"))
    except ValueError:
        height = 0

    maintain_aspect_ratio = str(request.POST.get("maintain_aspect_ratio", "true")).lower() == "true"

    # Check if ImageMagick is available, fall back to PIL if not
    if not _find_magick_command():
        print("⚠ ImageMagick not found, falling back to PIL for conversion")
        
        # Create a modified request for the PIL function
        request.POST._mutable = True
        request.POST["output_format"] = output_format
        request.POST["compression_level"] = str(100 - quality)
        request.POST["keep_metadata"] = "true"
        request.POST["resize_enabled"] = str(resize_enabled).lower()
        request.POST["max_width"] = str(width)
        request.POST["max_height"] = str(height)
        request.POST["maintain_aspect_ratio"] = str(maintain_aspect_ratio).lower()
        request.POST["keep_original_format"] = str(keep_original_format).lower()
        request.POST._mutable = False
        
        return compress_image_with_pillow(request)

    # Proceed with ImageMagick conversion
    original_size = image_file.size
    input_name = _safe_name(image_file.name)
    base_name = os.path.splitext(input_name)[0]

    # Create temporary directory for processing
    with tempfile.TemporaryDirectory() as tmp_dir:
        input_path = os.path.join(tmp_dir, input_name)
        output_path = os.path.join(tmp_dir, f"{base_name}.{output_format}")

        # Save uploaded file
        with open(input_path, "wb") as f:
            for chunk in image_file.chunks():
                f.write(chunk)

        # Run ImageMagick conversion
        error = _run_magick_convert(
            input_path,
            output_path,
            output_format,
            quality,
            resize_enabled,
            width,
            height,
            maintain_aspect_ratio,
        )
        
        if error:
            return JsonResponse({"success": False, "error": error}, status=500)

        # Verify output was created
        if not os.path.exists(output_path):
            return JsonResponse({"success": False, "error": "Converted output not found."}, status=500)

        # Read the output
        with open(output_path, "rb") as f:
            output_bytes = f.read()

    # Calculate statistics
    converted_size = len(output_bytes)
    saved_bytes = max(0, original_size - converted_size)
    compression_ratio = (1 - (converted_size / original_size)) * 100 if original_size > 0 else 0

    # Save output
    file_id = _save_output_bytes(output_bytes, output_format)

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if keep_original_format:
        filename = f"{base_name}_resized_{timestamp}.{output_format}"
    else:
        filename = f"{base_name}_converted_{timestamp}.{output_format}"

    return JsonResponse({
        "success": True,
        "file_id": file_id,
        "filename": filename,
        "original_name": image_file.name,
        "original_size": original_size,
        "converted_size": converted_size,
        "saved_bytes": saved_bytes,
        "compression_ratio": round(compression_ratio, 2),
        "download_url": _download_url(request, file_id),
        "output_format": output_format,
        "method": "imagemagick",
        "keep_original_format": keep_original_format
    })


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def compress_image_with_pillow(request):
    """
    Compress image using Pillow (PIL) with advanced optimization options
    """
    # Get the image file
    image_file = request.FILES.get("image_file") or request.FILES.get("file")
    if not image_file:
        return JsonResponse({"success": False, "error": "No image file provided."}, status=400)

    # Parse parameters
    keep_original_format = str(request.POST.get("keep_original_format", "false")).lower() == "true"
    
    try:
        compression_level = int(request.POST.get("compression_level", "70"))
    except ValueError:
        compression_level = 70

    keep_metadata = str(request.POST.get("keep_metadata", "true")).lower() == "true"
    resize_enabled = str(request.POST.get("resize_enabled", "false")).lower() == "true"
    maintain_aspect_ratio = str(request.POST.get("maintain_aspect_ratio", "true")).lower() == "true"

    try:
        max_width = int(request.POST.get("max_width", "1920"))
    except ValueError:
        max_width = 1920
        
    try:
        max_height = int(request.POST.get("max_height", "100000"))
    except ValueError:
        max_height = 100000

    output_format_raw = request.POST.get("output_format") or "same"
    
    # Additional optimization options
    use_progressive = str(request.POST.get("use_progressive", "true")).lower() == "true"
    optimize_colors = str(request.POST.get("optimize_colors", "true")).lower() == "true"
    strip_metadata = str(request.POST.get("strip_metadata", "false")).lower() == "true"

    # Determine input and output formats
    input_name = _safe_name(image_file.name)
    input_ext = os.path.splitext(input_name)[1].lower().lstrip(".")
    if input_ext == "jpg":
        input_ext = "jpeg"

    if keep_original_format:
        output_format = input_ext if input_ext in IMAGE_MIME_TYPES else "jpeg"
    elif output_format_raw in {"same", ""}:
        output_format = input_ext if input_ext in IMAGE_MIME_TYPES else "jpeg"
    else:
        output_format = _normalize_output_format(output_format_raw)
        if not output_format:
            return JsonResponse({"success": False, "error": "Unsupported output format."}, status=400)

    original_size = image_file.size
    quality = _compress_level_to_quality(compression_level)

    # Open and process image with PIL
    try:
        image = Image.open(image_file)
        image = ImageOps.exif_transpose(image)  # Handle orientation
    except Exception as exc:
        error_msg = f"Invalid image file: {exc}"
        return JsonResponse({"success": False, "error": error_msg}, status=400)

    original_width, original_height = image.size

    # Smart resizing with quality preservation
    if resize_enabled:
        if maintain_aspect_ratio:
            # Calculate optimal ratio while maintaining quality
            width_ratio = max_width / original_width if original_width > max_width else 1
            height_ratio = max_height / original_height if original_height > max_height else 1
            ratio = min(width_ratio, height_ratio)
            
            if ratio < 1:  # Only resize if necessary
                new_width = max(1, int(original_width * ratio))
                new_height = max(1, int(original_height * ratio))
                
                # Use better resampling for different scaling factors
                if ratio < 0.5:
                    resample_filter = Image.Resampling.LANCZOS  # Best quality for large reduction
                else:
                    resample_filter = Image.Resampling.BICUBIC  # Faster for small changes
                    
                image = image.resize((new_width, new_height), resample_filter)
        else:
            # Force exact dimensions
            if original_width > max_width or original_height > max_height:
                image = image.resize((max_width, max_height), Image.Resampling.LANCZOS)

    # Prepare save arguments based on output format
    save_kwargs = {}
    
    if output_format == "jpeg":
        # Convert to RGB if necessary
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        
        # JPEG optimization settings
        save_kwargs.update({
            "quality": quality,
            "optimize": True,
            "progressive": use_progressive,
            "subsampling": 0 if quality > 90 else -1,  # 0 = 4:4:4 best color quality
        })
    elif output_format == "webp":
        if image.mode not in ("RGB", "RGBA", "L"):
            image = image.convert("RGB")
        save_kwargs.update({
            "quality": quality,
            "method": 6,
        })
    elif output_format == "png":
        # PNG optimization
        if optimize_colors and image.mode == "RGBA":
            save_kwargs.update({
                "optimize": True,
                "compress_level": max(0, min(9, int(round((100 - compression_level) / 10)))),
            })
        else:
            png_level = max(0, min(9, int(round(compression_level / 10))))
            save_kwargs.update({
                "optimize": True,
                "compress_level": png_level,
            })

    # Handle metadata
    if keep_metadata and not strip_metadata:
        exif = image.info.get("exif")
        if exif and output_format in {"jpeg", "webp"}:
            save_kwargs["exif"] = exif
    elif strip_metadata:
        image.info.clear()

    # Save to buffer
    output_buffer = BytesIO()
    try:
        for attempt in range(2):
            try:
                image.save(output_buffer, format=output_format.upper(), **save_kwargs)
                break
            except Exception as e:
                if attempt == 0 and "exif" in save_kwargs:
                    save_kwargs.pop("exif", None)
                else:
                    raise e
    except Exception as exc:
        error_msg = f"Compression failed: {exc}"
        return JsonResponse({"success": False, "error": error_msg}, status=500)

    output_bytes = output_buffer.getvalue()
    converted_size = len(output_bytes)
    saved_bytes = max(0, original_size - converted_size)
    compression_ratio = (1 - (converted_size / original_size)) * 100 if original_size > 0 else 0
    
    # Save output
    file_id = _save_output_bytes(output_bytes, output_format)

    # Generate filename
    base_name = os.path.splitext(input_name)[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if keep_original_format:
        filename = f"{base_name}_resized_{timestamp}.{output_format}"
    else:
        filename = f"{base_name}_converted_{timestamp}.{output_format}"

    return JsonResponse({
        "success": True,
        "file_id": file_id,
        "filename": filename,
        "original_name": image_file.name,
        "original_size": original_size,
        "converted_size": converted_size,
        "saved_bytes": saved_bytes,
        "compression_ratio": round(compression_ratio, 2),
        "download_url": _download_url(request, file_id),
        "output_format": output_format,
        "compression_level": compression_level,
        "method": "pillow",
        "keep_original_format": keep_original_format,
        "quality_optimizations": {
            "progressive": use_progressive,
            "optimized_colors": optimize_colors,
            "metadata_kept": keep_metadata and not strip_metadata,
        }
    })

@api_view(["GET"])
def download_image_file_once(request, file_id):
    """
    Download a processed file once and delete it after download
    """
    storage_dir = _output_dir()

    # Find the file with any extension
    target_path = None
    target_ext = None
    for ext in IMAGE_MIME_TYPES.keys():
        candidate = os.path.join(storage_dir, f"{file_id}.{ext}")
        if os.path.exists(candidate):
            target_path = candidate
            target_ext = ext
            break

    if not target_path:
        return JsonResponse({
            "success": False, 
            "error": "File not found or already downloaded."
        }, status=404)

    # Generate filename
    filename = f"image_{file_id[:8]}.{target_ext}"

    # Read and delete file
    try:
        with open(target_path, "rb") as f:
            payload = f.read()
        
        os.remove(target_path)
            
    except Exception as exc:
        error_msg = f"Failed to serve file: {exc}"
        return JsonResponse({
            "success": False, 
            "error": error_msg
        }, status=500)

    # Create response
    response = HttpResponse(payload, content_type=IMAGE_MIME_TYPES[target_ext])
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Content-Length"] = str(len(payload))
    response["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Length"
    
    return response

