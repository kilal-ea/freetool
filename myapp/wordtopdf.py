# wordtopdf.py - النسخة النهائية مع تحسين التحميل

import json
import os
import tempfile
import shutil
from datetime import datetime, timedelta
from django.http import HttpResponse, JsonResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.urls import reverse
import uuid
import threading
import time
from urllib.parse import unquote

from .libreoffice import run_convert, find_converted_file

# محاولة استيراد PathDownloadView من المكتبات المختلفة
PathDownloadView = None
try:
    from django_downloadview import PathDownloadView
    print("✅ [Import] Using django_downloadview.PathDownloadView")
except ImportError:
    try:
        from downloadview import PathDownloadView
        print("✅ [Import] Using downloadview.PathDownloadView")
    except ImportError:
        print("⚠️ [Import] PathDownloadView not available, using function-based view only")
        PathDownloadView = None


class FileCleanupManager:
    """
    Manages automatic cleanup of temporary and downloaded files
    """
    _instance = None
    _cleanup_thread = None
    _running = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_cleanup_manager()
        return cls._instance
    
    def _init_cleanup_manager(self):
        """Initialize cleanup manager"""
        self.files_to_cleanup = []
        self.max_file_age = getattr(settings, 'MAX_FILE_AGE_HOURS', 1)
        self.cleanup_interval = 300  # 5 minutes
        
    def start_cleanup_thread(self):
        """Start background cleanup thread"""
        if not self._cleanup_thread or not self._cleanup_thread.is_alive():
            self._running = True
            self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
            self._cleanup_thread.start()
            print(f"🧹 [Cleanup] Cleanup thread started (interval: {self.cleanup_interval}s)")
    
    def _cleanup_loop(self):
        """Main cleanup loop"""
        while self._running:
            try:
                self._cleanup_old_files()
                self.cleanup_scheduled_files()
            except Exception as e:
                print(f"⚠️ [Cleanup] Error in cleanup loop: {e}")
            time.sleep(self.cleanup_interval)
    
    def _cleanup_old_files(self):
        """Cleanup files older than max age"""
        files_dir = _ensure_files_directory()
        
        cutoff_time = datetime.now() - timedelta(hours=self.max_file_age)
        
        for item in os.listdir(files_dir):
            item_path = os.path.join(files_dir, item)
            try:
                if os.path.isfile(item_path):
                    mtime = datetime.fromtimestamp(os.path.getmtime(item_path))
                    if mtime < cutoff_time:
                        if _is_pdf_path(item_path):
                            print(f"[Cleanup] Skipping PDF file: {item}")
                            continue
                        os.remove(item_path)
                        print(f"🗑️ [Cleanup] Removed old file: {item}")
                elif os.path.isdir(item_path) and item.startswith("temp_"):
                    ctime = datetime.fromtimestamp(os.path.getctime(item_path))
                    if ctime < cutoff_time:
                        if _directory_contains_pdf(item_path):
                            print(f"[Cleanup] Skipping directory with PDF files: {item}")
                            continue
                        shutil.rmtree(item_path)
                        print(f"🗑️ [Cleanup] Removed old directory: {item}")
            except Exception as e:
                print(f"⚠️ [Cleanup] Error removing {item_path}: {e}")
    
    def schedule_file_cleanup(self, file_path, delay_seconds=3600):  # زيادة إلى 60 دقيقة
        """Schedule a file for cleanup after delay"""
        self.files_to_cleanup.append({
            'path': file_path,
            'delete_after': datetime.now() + timedelta(seconds=delay_seconds)
        })
        print(f"⏰ [Cleanup] Scheduled cleanup for: {file_path} (in {delay_seconds}s)")
    
    def cleanup_scheduled_files(self):
        """Cleanup scheduled files"""
        now = datetime.now()
        remaining = []
        
        for file_info in self.files_to_cleanup:
            if now >= file_info['delete_after']:
                try:
                    if os.path.exists(file_info['path']):
                        if os.path.isfile(file_info['path']):
                            if _is_pdf_path(file_info['path']):
                                print(f"[Cleanup] Skipping scheduled PDF cleanup: {file_info['path']}")
                                remaining.append(file_info)
                                continue
                            os.remove(file_info['path'])
                        elif os.path.isdir(file_info['path']):
                            if _directory_contains_pdf(file_info['path']):
                                print(f"[Cleanup] Skipping scheduled directory cleanup with PDFs: {file_info['path']}")
                                remaining.append(file_info)
                                continue
                            shutil.rmtree(file_info['path'])
                        print(f"🗑️ [Cleanup] Cleaned up scheduled: {file_info['path']}")
                except Exception as e:
                    print(f"⚠️ [Cleanup] Error cleaning {file_info['path']}: {e}")
            else:
                remaining.append(file_info)
        
        self.files_to_cleanup = remaining
    
    def stop(self):
        """Stop cleanup thread"""
        self._running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)


# Initialize cleanup manager
cleanup_manager = FileCleanupManager()


def _is_pdf_path(path):
    return os.path.splitext(str(path))[1].lower() == ".pdf"


def _directory_contains_pdf(path):
    for root, _dirs, files in os.walk(path):
        for name in files:
            if name.lower().endswith(".pdf"):
                return True
    return False


def _get_cors_headers(request):
    """
    Get CORS headers dynamically based on request origin
    """
    origin = request.META.get('HTTP_ORIGIN', '')

    allow_all = getattr(settings, 'CORS_ALLOW_ALL_ORIGINS', False)
    allowed_origins = getattr(settings, 'CORS_ALLOWED_ORIGINS', [
        'http://localhost:3000',
        'http://127.0.0.1:3000',
        'http://localhost:8000',
        'http://127.0.0.1:8000',
    ])

    if allow_all:
        allow_origin = origin or "*"
        return {
            "Access-Control-Allow-Origin": allow_origin,
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS, DELETE",
            "Access-Control-Allow-Headers": "Content-Type, X-Requested-With, Authorization, X-File-Name, X-File-Size",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Expose-Headers": "Content-Disposition, Content-Length, X-File-Name, X-Original-Size, X-Converted-Size, X-Saved-Bytes, X-Compression-Ratio",
            "Access-Control-Max-Age": "86400",
            "Vary": "Origin",
        }

    if origin:
        if origin in allowed_origins:
            return {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS, DELETE",
                "Access-Control-Allow-Headers": "Content-Type, X-Requested-With, Authorization, X-File-Name, X-File-Size",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Expose-Headers": "Content-Disposition, Content-Length, X-File-Name, X-Original-Size, X-Converted-Size, X-Saved-Bytes, X-Compression-Ratio",
                "Access-Control-Max-Age": "86400",
                "Vary": "Origin",
            }
        else:
            print(f"⚠️ [CORS] Origin not allowed: {origin}")
            return {
                "Access-Control-Allow-Origin": "null",
                "Access-Control-Allow-Methods": "",
                "Access-Control-Allow-Headers": "",
                "Vary": "Origin",
            }
    else:
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS, DELETE",
            "Access-Control-Allow-Headers": "Content-Type, X-Requested-With, Authorization, X-File-Name, X-File-Size",
            "Access-Control-Expose-Headers": "Content-Disposition, Content-Length, X-File-Name, X-Original-Size, X-Converted-Size, X-Saved-Bytes, X-Compression-Ratio",
        }


def _ensure_files_directory():
    """
    Create the files directory structure if it doesn't exist
    """
    if hasattr(settings, 'MEDIA_ROOT'):
        files_dir = os.path.join(settings.MEDIA_ROOT, 'word_to_pdf')
    else:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        files_dir = os.path.join(project_root, 'converted', 'word_to_pdf')
    
    os.makedirs(files_dir, exist_ok=True)
    print(f"📁 [Directory] Using directory: {files_dir}")
    
    cleanup_manager.start_cleanup_thread()
    
    return files_dir


def _convert_with_libreoffice(input_path, output_dir):
    """Convert Word to PDF using LibreOffice headless mode"""
    print("🔄 [LibreOffice] Starting conversion...")
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    _, error = run_convert(input_path, output_dir, "pdf")
    
    if error:
        print(f"❌ [LibreOffice] Conversion error: {error}")
        return None

    result = find_converted_file(output_dir, base_name, ["pdf"])
    if result:
        print(f"✅ [LibreOffice] Conversion successful: {result}")
    else:
        print("⚠️ [LibreOffice] Converted file not found")
    return result


def _get_supported_extensions():
    """Get list of supported file extensions by LibreOffice"""
    return [
        '.doc', '.docx', '.dot', '.dotx', '.dotm',
        '.odt', '.rtf', '.txt', '.html', '.htm',
        '.xml', '.wps', '.wpd'
    ]


def _save_converted_file(pdf_data, original_filename, request):
    """
    Save converted PDF to downloads directory with unique ID
    Returns file info with download URL - باستخدام المسار الدائم
    """
    import re
    
    file_id = str(uuid.uuid4())
    original_name_without_ext = os.path.splitext(original_filename)[0]
    
    # تنظيف اسم الملف
    safe_name = original_name_without_ext.replace(' ', '_')
    safe_name = re.sub(r'[^\w\-_.]', '', safe_name)
    safe_name = re.sub(r'_+', '_', safe_name)
    if len(safe_name) > 50:
        safe_name = safe_name[:50]
    safe_name = safe_name.strip('_')
    
    safe_filename = f"{safe_name}_{file_id[:8]}.pdf"
    
    files_dir = _ensure_files_directory()
    pdf_path = os.path.join(files_dir, safe_filename)
    
    print(f"💾 [Save] Saving PDF to: {pdf_path}")
    
    with open(pdf_path, "wb") as f:
        f.write(pdf_data)
    
    # جدولة التنظيف بعد 60 دقيقة
    # PDF cleanup scheduling disabled
    
    # استخدام المسار الدائم الذي لا يحذف الملف بعد التحميل
    download_url = reverse('download_converted_file_persistent', args=[safe_filename])

    if not download_url.startswith('/'):
        download_url = f"/{download_url}"
    if download_url.endswith('/'):
        download_url = download_url.rstrip('/')
    
    if request:
        full_url = request.build_absolute_uri(download_url)
    else:
        base_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
        full_url = f"{base_url.rstrip('/')}{download_url}"
    
    print(f"🔗 [Save] Generated persistent download URL: {full_url}")
    
    return {
        'file_id': file_id,
        'filename': safe_filename,
        'path': pdf_path,
        'download_url': full_url,
        'size': len(pdf_data)
    }


def convert_word_to_pdf(request):
    """Convert a Word document to PDF and return download URL"""
    print("=" * 60)
    print("🚀 [API] Starting Word to PDF conversion")
    print("=" * 60)
    
    cors_headers = _get_cors_headers(request)
    
    if request.method == "OPTIONS":
        print("✅ [API] Handling OPTIONS request")
        response = HttpResponse()
        for key, value in cors_headers.items():
            response[key] = value
        return response
    
    if request.method != "POST":
        print("❌ [API] Error: Only POST method allowed")
        response = JsonResponse({"error": "Method not allowed"}, status=405)
        for key, value in cors_headers.items():
            response[key] = value
        return response

    word_file = request.FILES.get("word_file")
    if not word_file:
        print("❌ [API] Error: No file uploaded")
        response = JsonResponse({"error": "No file uploaded"}, status=400)
        for key, value in cors_headers.items():
            response[key] = value
        return response

    file_ext = os.path.splitext(word_file.name)[1].lower()
    supported_extensions = _get_supported_extensions()
    
    if file_ext not in supported_extensions:
        print(f"❌ [API] Unsupported extension: {file_ext}")
        response = JsonResponse({
            "error": f"Unsupported format. Supported: {', '.join(supported_extensions)}"
        }, status=400)
        for key, value in cors_headers.items():
            response[key] = value
        return response

    try:
        settings_data = request.POST.get("pdf_settings", "{}")
        try:
            pdf_settings = json.loads(settings_data)
        except:
            pdf_settings = {}

        files_dir = _ensure_files_directory()
        temp_dir = os.path.join(files_dir, f"temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}")
        os.makedirs(temp_dir, exist_ok=True)
        
        cleanup_manager.schedule_file_cleanup(temp_dir, delay_seconds=7200)
        
        word_path = os.path.join(temp_dir, word_file.name)
        with open(word_path, "wb") as f:
            for chunk in word_file.chunks():
                f.write(chunk)

        # Try LibreOffice first
        pdf_path = _convert_with_libreoffice(word_path, temp_dir)
        
        # If LibreOffice fails, try Python fallback
        if not pdf_path or not os.path.exists(pdf_path):
            print("⚠️ [API] LibreOffice conversion failed, trying Python fallback...")
            
            try:
                # Try to import required libraries
                try:
                    from docx import Document
                    from reportlab.lib.pagesizes import A4, LETTER, landscape, portrait
                    from reportlab.lib.utils import simpleSplit
                    from reportlab.pdfgen import canvas
                except ImportError as e:
                    print(f"❌ [Fallback] Libraries missing: {e}")
                    raise Exception("Python fallback requires docx and reportlab. Please install: pip install python-docx reportlab")
                
                pdf_path = os.path.join(temp_dir, f"{os.path.splitext(word_file.name)[0]}.pdf")
                
                def _get_page_size(settings):
                    page_size = settings.get("pageSize", "A4")
                    orientation = settings.get("orientation", "portrait")
                    
                    if page_size == "Letter":
                        pdf_page_size = LETTER
                    elif page_size == "A3":
                        pdf_page_size = (297 * 2.83465, 420 * 2.83465)
                    else:
                        pdf_page_size = A4
                    
                    return landscape(pdf_page_size) if orientation == "landscape" else portrait(pdf_page_size)
                
                doc = Document(word_path)
                page_size = _get_page_size(pdf_settings)
                
                c = canvas.Canvas(pdf_path, pagesize=page_size)
                c.setFont("Helvetica", 12)
                
                margin_left = 50
                margin_top = 50
                line_height = 16.2
                y = page_size[1] - margin_top
                max_width = page_size[0] - (2 * margin_left)
                
                for paragraph in doc.paragraphs:
                    text = paragraph.text or ""
                    if text.strip():
                        lines = simpleSplit(text, "Helvetica", 12, max_width)
                        for line in lines:
                            if y <= 50:
                                c.showPage()
                                c.setFont("Helvetica", 12)
                                y = page_size[1] - margin_top
                            c.drawString(margin_left, y, line)
                            y -= line_height
                    else:
                        y -= line_height
                
                c.save()
                print("✅ [Fallback] PDF created successfully")
                
            except Exception as e:
                print(f"❌ [Fallback] Error: {str(e)}")
                response = JsonResponse({"error": f"Conversion failed: {str(e)}"}, status=500)
                for key, value in cors_headers.items():
                    response[key] = value
                return response

        # Read the converted PDF
        try:
            with open(pdf_path, "rb") as f:
                pdf_data = f.read()
        except Exception as e:
            print(f"❌ [Reading] Error: {str(e)}")
            response = JsonResponse({"error": f"Failed to read PDF: {str(e)}"}, status=500)
            for key, value in cors_headers.items():
                response[key] = value
            return response

        # Save the PDF to the downloads directory
        file_info = _save_converted_file(pdf_data, word_file.name, request)
        
        original_size = word_file.size
        converted_size = len(pdf_data)
        saved = max(0, original_size - converted_size)
        compression_ratio = f"{converted_size/original_size*100:.1f}%" if original_size > 0 else "0.0%"
        
        print("\n" + "=" * 60)
        print("✅ CONVERSION COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        print(f"📄 Original file: {word_file.name} ({original_size} bytes)")
        print(f"📄 Converted file: {file_info['filename']} ({converted_size} bytes)")
        print(f"🔗 DOWNLOAD URL: {file_info['download_url']}")
        print("=" * 60 + "\n")
        
        response_data = {
            "success": True,
            "message": "File converted successfully",
            "download_url": file_info['download_url'],
            "filename": file_info['filename'],
            "file_id": file_info['file_id'],
            "original_name": word_file.name,
            "original_size": original_size,
            "converted_size": converted_size,
            "saved_bytes": saved,
            "compression_ratio": compression_ratio,
            "auto_cleanup": True,
            "cleanup_in": "60 minutes",
            "expires_in": "60 minutes"
        }
        
        response = JsonResponse(response_data)
        for key, value in cors_headers.items():
            response[key] = value
        return response

    except Exception as e:
        print(f"❌ [API] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        response = JsonResponse({"error": f"Conversion failed: {str(e)}"}, status=500)
        for key, value in cors_headers.items():
            response[key] = value
        return response


def download_converted_file_persistent(request, filename):
    """
    Serve converted PDF file for download WITHOUT auto-deletion after download
    الملفات تبقى متاحة لمدة 60 دقيقة بغض النظر عن عدد مرات التحميل
    """
    print(f"📥 [Download Persistent] Request for: {filename}")
    
    # تصحيح اسم الملف
    filename = filename.rstrip('/')
    
    if not filename.endswith('.pdf'):
        filename = f"{filename}.pdf"
        print(f"📥 [Download Persistent] Added .pdf extension: {filename}")
    
    from urllib.parse import unquote
    filename = unquote(filename)
    filename = os.path.basename(filename)

    files_dir = _ensure_files_directory()
    file_path = os.path.join(files_dir, filename)

    cors_headers = _get_cors_headers(request)
    
    if request.method == "OPTIONS":
        response = HttpResponse()
        for key, value in cors_headers.items():
            response[key] = value
        return response

    if not os.path.exists(file_path):
        print(f"⚠️ [Download Persistent] File not found: {file_path}")
        
        # البحث عن الملف بدون .pdf
        filename_without_pdf = filename[:-4] if filename.endswith('.pdf') else filename
        alternative_path = os.path.join(files_dir, filename_without_pdf)
        
        if os.path.exists(alternative_path):
            file_path = alternative_path
            print(f"📥 [Download Persistent] Found alternative file: {file_path}")
        else:
            response = JsonResponse({
                "error": "File not found or expired",
                "message": "The file may have expired. Please convert again.",
                "expired": True
            }, status=404)
            for key, value in cors_headers.items():
                response[key] = value
            return response

    try:
        # فتح الملف
        file_handle = open(file_path, "rb")
        
        # إنشاء استجابة
        response = FileResponse(
            file_handle,
            content_type="application/pdf",
            as_attachment=True,
            filename=os.path.basename(file_path),
        )
        
        # إضافة الرؤوس
        file_size = os.path.getsize(file_path)
        response["Content-Length"] = file_size
        response["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Length, X-Expires-In"
        response["X-Expires-In"] = "60 minutes"
        response["Cache-Control"] = "public, max-age=3600"
        
        # إضافة رؤوس CORS
        for key, value in cors_headers.items():
            response[key] = value
        
        # إغلاق الملف بعد الانتهاء
        response.close = file_handle.close
        
        print(f"✅ [Download Persistent] Serving file: {file_path} ({file_size} bytes)")
        print(f"⏰ [Download Persistent] File will be available for 60 minutes")
        return response
        
    except Exception as e:
        print(f"❌ [Download Persistent] Error serving file: {e}")
        response = JsonResponse({"error": f"Error serving file: {str(e)}"}, status=500)
        for key, value in cors_headers.items():
            response[key] = value
        return response


def download_converted_file(request, filename):
    """Redirect to persistent download"""
    print(f"📥 [Download Legacy] Redirecting to persistent download for: {filename}")
    return download_converted_file_persistent(request, filename)


def check_file_exists(request, filename):
    """Check if a file exists without downloading it"""
    print(f"🔍 [Check File] Checking existence for: {filename}")
    
    filename = filename.rstrip('/')
    if not filename.endswith('.pdf'):
        filename = f"{filename}.pdf"
    
    from urllib.parse import unquote
    filename = unquote(filename)
    filename = os.path.basename(filename)

    files_dir = _ensure_files_directory()
    file_path = os.path.join(files_dir, filename)

    cors_headers = _get_cors_headers(request)
    
    if request.method == "OPTIONS":
        response = HttpResponse()
        for key, value in cors_headers.items():
            response[key] = value
        return response

    if os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
        file_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
        expires_at = file_modified + timedelta(hours=1)
        
        response_data = {
            "exists": True,
            "filename": filename,
            "size": file_size,
            "expires_at": expires_at.isoformat(),
            "minutes_remaining": max(0, int((expires_at - datetime.now()).total_seconds() / 60))
        }
        response = JsonResponse(response_data)
    else:
        response = JsonResponse({"exists": False}, status=404)
    
    for key, value in cors_headers.items():
        response[key] = value
    return response



def list_converted_files(request):
    """List all converted PDF files (for debugging)"""
    cors_headers = _get_cors_headers(request)
    
    if request.method == "OPTIONS":
        response = HttpResponse()
        for key, value in cors_headers.items():
            response[key] = value
        return response
    
    files_dir = _ensure_files_directory()
    files = []
    
    try:
        now = datetime.now()
        for f in os.listdir(files_dir):
            if f.endswith('.pdf'):
                file_path = os.path.join(files_dir, f)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    expires_at = mtime + timedelta(hours=1)
                    minutes_remaining = max(0, int((expires_at - now).total_seconds() / 60))
                    
                    files.append({
                        'filename': f,
                        'size': os.path.getsize(file_path),
                        'created': mtime.isoformat(),
                        'expires_at': expires_at.isoformat(),
                        'minutes_remaining': minutes_remaining,
                        'url': request.build_absolute_uri(
                            reverse('download_converted_file_persistent', args=[f])
                        )
                    })
                except Exception as e:
                    print(f"⚠️ [List] Error processing file {f}: {e}")
    except Exception as e:
        print(f"⚠️ [List] Error listing directory: {e}")
    
    response = JsonResponse({
        'files': files,
        'count': len(files),
        'directory': files_dir
    })
    for key, value in cors_headers.items():
        response[key] = value
    return response


# django-downloadview based download (اختياري)
if PathDownloadView:
    class WordToPdfDownloadView(PathDownloadView):
        attachment = True
        content_type = "application/pdf"

        def get_path(self):
            filename = self.kwargs.get("filename", "")
            filename = filename.rstrip("/")
            filename = unquote(filename)
            if not filename.endswith(".pdf"):
                filename = f"{filename}.pdf"
            filename = os.path.basename(filename)
            files_dir = _ensure_files_directory()
            return os.path.join(files_dir, filename)

        def get(self, request, *args, **kwargs):
            response = super().get(request, *args, **kwargs)
            cors_headers = _get_cors_headers(request)
            for key, value in cors_headers.items():
                response[key] = value
            return response
            
        def head(self, request, *args, **kwargs):
            """Handle HEAD requests"""
            response = super().head(request, *args, **kwargs)
            cors_headers = _get_cors_headers(request)
            for key, value in cors_headers.items():
                response[key] = value
            return response