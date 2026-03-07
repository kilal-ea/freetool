import os
from datetime import datetime
import numpy as np
from PIL import Image
import cv2
import onnxruntime as ort
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from rest_framework.decorators import api_view
from rest_framework.response import Response
import uuid
import io
import traceback
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import permission_classes

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
import json
import logging
from .models import PageStatus
User = get_user_model() # Get the custom user model
MODEL_PATH = os.path.join(os.path.dirname(__file__), '../U-2-Net/onnx/model.onnx')

def home(request):
    if request.user.is_authenticated:
        return redirect("back_test")

    error_code = None
    next_url = request.GET.get("next") or ""
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        if not username or not password:
            error_code = "MISSING_CREDENTIALS"
        else:
            user = authenticate(request, username=username, password=password)
            if user is None:
                error_code = "INVALID_CREDENTIALS"
            else:
                login(request, user)
                posted_next_url = request.POST.get("next") or request.GET.get("next")
                return redirect(posted_next_url or "back_test")

    return render(request, "home.html", {"error_code": error_code, "next_url": next_url})

def load_model():
    try:
        # تحميل النموذج مع تحسينات للأداء
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        
        # استخدام CPU (تغيير إلى CUDAExecutionProvider إذا كان لديك GPU)
        providers = ['CPUExecutionProvider']
        
        session = ort.InferenceSession(
            MODEL_PATH,
            sess_options=options,
            providers=providers
        )
        print("✅ Model loaded successfully")
        return session
    except Exception as e:
        print(f"❌ Error loading model: {e}")
        print(f"Model path: {MODEL_PATH}")
        print(f"Model exists: {os.path.exists(MODEL_PATH)}")
        return None

# تحميل النموذج عند بدء التشغيل
model_session = load_model()

def ensure_rgb_image(image_bytes):
    """
    تحويل أي صورة إلى RGB format مع الحفاظ على الألوان
    يستخدم PIL للحفاظ على دقة الألوان
    """
    try:
        # استخدام PIL لقراءة الصورة مع الحفاظ على البيانات الوصفية
        image = Image.open(io.BytesIO(image_bytes))
        
        # حفظ معلومات الصورة الأصلية
        original_format = image.format
        original_mode = image.mode
        original_size = image.size
        
        print(f"📊 Original image info: format={original_format}, mode={original_mode}, size={original_size}")
        
        # تحويل الصورة إلى RGB
        if image.mode == 'RGBA':
            # للصور ذات قناة ألفا: إنشاء خلفية بيضاء
            background = Image.new('RGB', image.size, (255, 255, 255))
            # لصق الصورة مع قناع ألفا
            background.paste(image, mask=image.split()[3])
            image = background
        elif image.mode == 'LA':
            # للصور ذات التدرج الرمادي مع ألفا
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image.convert('RGBA'), mask=image.split()[1])
            image = background
        elif image.mode == 'P':
            # للصور الملونة المفهرسة
            if 'transparency' in image.info:
                image = image.convert('RGBA')
                background = Image.new('RGB', image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[3])
                image = background
            else:
                image = image.convert('RGB')
        elif image.mode == 'L':
            # للصور ذات التدرج الرمادي
            image = image.convert('RGB')
        elif image.mode == 'CMYK':
            # للصور CMYK (مثل بعض صور JPEG)
            image = image.convert('RGB')
        elif image.mode != 'RGB':
            # أي صيغة أخرى
            image = image.convert('RGB')
        
        # تحويل إلى numpy array
        image_np = np.array(image)
        
        # التأكد من أن الصورة تحتوي على 3 قنوات
        if len(image_np.shape) == 2:
            # تدرج رمادي -> RGB
            image_np = np.stack([image_np, image_np, image_np], axis=2)
        
        print(f"✅ Converted to RGB: shape={image_np.shape}, dtype={image_np.dtype}")
        return image_np, original_format
        
    except Exception as e:
        print(f"❌ Error in ensure_rgb_image (PIL): {e}")
        
        # محاولة استخدام OpenCV كبديل
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            # قراءة الصورة مع جميع القنوات
            image_np = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
            
            if image_np is None:
                raise ValueError("OpenCV failed to decode image")
            
            print(f"📊 OpenCV decoded image: shape={image_np.shape}, dtype={image_np.dtype}")
            
            # تحويل إلى RGB حسب عدد القنوات
            if len(image_np.shape) == 2:
                # تدرج رمادي -> RGB
                image_np = cv2.cvtColor(image_np, cv2.COLOR_GRAY2RGB)
            elif image_np.shape[2] == 4:
                # BGRA أو RGBA -> RGB
                # تحويل BGR إلى RGB أولاً إذا لزم الأمر
                if image_np[0, 0, 0] > image_np[0, 0, 2]:  # B > R، إذن هي BGR
                    b, g, r, a = cv2.split(image_np)
                    image_np = cv2.merge([r, g, b])
                # تطبيق قناة ألفا على خلفية بيضاء
                alpha = image_np[:, :, 3] / 255.0
                result = np.zeros((image_np.shape[0], image_np.shape[1], 3), dtype=np.uint8)
                for c in range(3):
                    result[:, :, c] = image_np[:, :, c] * alpha + 255 * (1 - alpha)
                image_np = result.astype(np.uint8)
            elif image_np.shape[2] == 3:
                # BGR -> RGB
                image_np = cv2.cvtColor(image_np, cv2.COLOR_BGR2RGB)
            
            print(f"✅ OpenCV converted to RGB: shape={image_np.shape}")
            return image_np, "JPEG"
            
        except Exception as cv2_error:
            print(f"❌ OpenCV fallback failed: {cv2_error}")
            raise ValueError(f"Cannot process image: {e}")

def preprocess_image(image_np, target_size=320):
    """معالجة الصورة قبل إدخالها للنموذج"""
    try:
        # الحفاظ على الأبعاد الأصلية
        original_h, original_w = image_np.shape[:2]
        
        print(f"📐 Original dimensions: {original_w}x{original_h}")
        
        # تغيير الحجم مع الحفاظ على النسبة
        scale = target_size / max(original_h, original_w)
        new_h, new_w = int(original_h * scale), int(original_w * scale)
        
        print(f"📐 Resized to: {new_w}x{new_h} (scale={scale:.3f})")
        
        resized = cv2.resize(image_np, (new_w, new_h), interpolation=cv2.INTER_AREA)
        
        # تعبئة الصورة لمطابقة حجم الإدخال للنموذج
        pad_h = target_size - new_h
        pad_w = target_size - new_w
        padded = np.pad(resized, ((0, pad_h), (0, pad_w), (0, 0)), mode='constant', constant_values=0)
        
        # تطبيع الصورة مع التأكد من استخدام float32
        input_data = padded.astype(np.float32) / 255.0
        
        # معاملات التطبيع (لنموذج U-2-Net المدرب على ImageNet)
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        
        input_data = (input_data - mean) / std
        input_data = np.transpose(input_data, (2, 0, 1))  # تغيير إلى (C, H, W)
        input_data = np.expand_dims(input_data, axis=0)  # إضافة بُعد الدفعة
        
        print(f"✅ Preprocessed: input shape={input_data.shape}, dtype={input_data.dtype}")
        return input_data, original_h, original_w, new_h, new_w
        
    except Exception as e:
        print(f"❌ Error in preprocess_image: {e}")
        raise e

def postprocess_mask(mask, original_w, original_h, new_h, new_w):
    """معالجة القناع بعد التنبؤ"""
    try:
        # استخراج القناع الفعلي (إزالة الحشو)
        mask = mask[0, 0, :new_h, :new_w]
        
        # تغيير حجم القناع إلى الأبعاد الأصلية
        mask = cv2.resize(mask, (original_w, original_h), interpolation=cv2.INTER_CUBIC)
        
        # تطبيع القناع بين 0 و1
        mask = np.clip(mask, 0, 1)
        
        # تحويل إلى 0-255
        mask_uint8 = (mask * 255).astype(np.uint8)
        
        # تطبيق threshold مع Otsu للفصل التلقائي
        _, binary_mask = cv2.threshold(mask_uint8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # تحسين القناع باستخدام العمليات المورفولوجية
        kernel = np.ones((3, 3), np.uint8)
        
        # إغلاق الفجوات الصغيرة داخل الكائن
        binary_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        
        # إزالة الضوضاء الصغيرة خارج الكائن
        binary_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_OPEN, kernel, iterations=1)
        
        # تطبيق Gaussian blur لتليين الحواف
        binary_mask = cv2.GaussianBlur(binary_mask, (5, 5), 0)
        
        # تطبيق threshold نهائي
        _, binary_mask = cv2.threshold(binary_mask, 127, 255, cv2.THRESH_BINARY)
        
        # تأكد من أن الخلفية سوداء والمقدمة بيضاء
        if np.mean(binary_mask[:10, :10]) > 127:  # إذا كانت الزاوية اليسرى العليا فاتحة
            binary_mask = 255 - binary_mask  # عكس القناع
        
        print(f"✅ Mask processed: shape={binary_mask.shape}, foreground pixels={np.sum(binary_mask > 0)}")
        return binary_mask
        
    except Exception as e:
        print(f"❌ Error in postprocess_mask: {e}")
        raise e

def create_transparent_image(rgb_image, mask):
    """إنشاء صورة شفافة من صورة RGB وقناع"""
    try:
        # تأكد من أن الصورة RGB في نطاق 0-255
        if rgb_image.dtype != np.uint8:
            rgb_image = np.clip(rgb_image, 0, 255).astype(np.uint8)
        
        # تأكد من أن الصورة بها 3 قنوات
        if len(rgb_image.shape) == 2:
            rgb_image = np.stack([rgb_image, rgb_image, rgb_image], axis=2)
        
        # إنشاء صورة RGBA
        rgba_image = np.zeros((rgb_image.shape[0], rgb_image.shape[1], 4), dtype=np.uint8)
        
        # نسخ قنوات RGB
        rgba_image[:, :, 0:3] = rgb_image
        
        # تطبيق القناع على قناة ألفا
        rgba_image[:, :, 3] = mask
        
        # تحسين حواف ألفا
        alpha = rgba_image[:, :, 3]
        
        # تطبيق تنعيم خفيف على الحواف
        if alpha.max() > 0:
            # إنشاء قناع للحواف
            edges = cv2.Canny(alpha, 30, 100)
            
            if edges.max() > 0:
                # توسيع الحواف قليلاً
                edges = cv2.dilate(edges, np.ones((2, 2), np.uint8), iterations=1)
                
                # تطبيق Gaussian blur على المناطق القريبة من الحواف
                alpha_blurred = cv2.GaussianBlur(alpha, (3, 3), 0.5)
                
                # دمج القناع الأصلي مع المناطق المتنعمة
                alpha_combined = alpha.copy()
                alpha_combined[edges > 0] = alpha_blurred[edges > 0]
                
                # تطبيق threshold للحفاظ على التباين
                _, alpha_final = cv2.threshold(alpha_combined, 10, 255, cv2.THRESH_BINARY)
                rgba_image[:, :, 3] = alpha_final
        
        print(f"✅ Transparent image created: shape={rgba_image.shape}")
        return rgba_image
        
    except Exception as e:
        print(f"❌ Error in create_transparent_image: {e}")
        raise e

def remove_background_u2net(image_file):
    """إزالة الخلفية باستخدام U-2-Net"""
    if model_session is None:
        raise Exception("Model not loaded")
    
    try:
        print(f"🔄 Starting background removal...")
        
        # قراءة بيانات الصورة
        image_bytes = image_file.read()
        print(f"📦 Image size: {len(image_bytes)} bytes")
        
        # تحويل الصورة إلى RGB
        image_np, original_format = ensure_rgb_image(image_bytes)
        
        # سجل إحصائيات الصورة
        print(f"📊 Image stats - Min: {image_np.min()}, Max: {image_np.max()}, "
              f"Mean: {image_np.mean():.1f}, Std: {image_np.std():.1f}")
        
        # معالجة الصورة
        input_data, original_h, original_w, new_h, new_w = preprocess_image(image_np)
        
        # التنبؤ باستخدام النموذج
        print(f"🤖 Running model inference...")
        input_name = model_session.get_inputs()[0].name
        output_name = model_session.get_outputs()[0].name
        
        prediction = model_session.run([output_name], {input_name: input_data})[0]
        print(f"✅ Model inference complete")
        
        # معالجة القناع
        binary_mask = postprocess_mask(prediction, original_w, original_h, new_h, new_w)
        
        # إنشاء صورة شفافة
        transparent_image = create_transparent_image(image_np, binary_mask)
        
        # تحويل إلى PNG باستخدام PIL للحفاظ على الجودة
        print(f"💾 Saving as PNG...")
        result_image_pil = Image.fromarray(transparent_image, 'RGBA')
        
        # حفظ إلى buffer مع ضغط جيد
        result_buffer = io.BytesIO()
        result_image_pil.save(result_buffer, 
                            format='PNG', 
                            optimize=True, 
                            compress_level=6)
        result_data = result_buffer.getvalue()
        
        print(f"✅ Background removal complete. Result size: {len(result_data)} bytes")
        return result_data
        
    except Exception as e:
        print(f"❌ Error in remove_background_u2net:")
        traceback.print_exc()
        raise e

class AutomaticTokenObtainView(APIView):
    authentication_classes = [] # No authentication for this endpoint
    permission_classes = [] # No permissions for this endpoint

    def post(self, request):
        api_key = request.headers.get('X-API-KEY')

        if not api_key or api_key != settings.STATIC_API_KEY:
            if not getattr(settings, "ALLOW_MACHINE_TOKEN_WITHOUT_API_KEY", False):
                return Response({"detail": "Invalid API Key"}, status=status.HTTP_401_UNAUTHORIZED)

        # Retrieve the designated machine user
        user, created = User.objects.get_or_create(username=settings.MACHINE_USERNAME)
        if created:
            user.set_unusable_password()
            user.is_active = True
            user.save()

        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def protected_test_view(request):
    """
    A sample protected endpoint to test JWT authentication.
    Only authenticated users can access this.
    """
    return Response({
        'message': f'Hello, {request.user.username}! You are authenticated and can access this protected data.',
        'user_id': request.user.id,
        'is_staff': request.user.is_staff,
    })

@api_view(['POST'])
def remove_background(request):
    """API endpoint لإزالة الخلفية"""
    try:
        # التحقق من وجود ملف الصورة
        if 'image' not in request.FILES:
            return Response({
                'success': False,
                'detail': 'No image provided',
                'error_code': 'NO_IMAGE'
            }, status=400)
        
        image_file = request.FILES['image']
        
        # التحقق من نوع الملف
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/bmp']
        if image_file.content_type not in allowed_types:
            return Response({
                'success': False,
                'detail': 'Invalid file type. Please upload JPEG, PNG, WebP, or BMP image',
                'error_code': 'INVALID_FILE_TYPE',
                'allowed_types': allowed_types
            }, status=400)
        
        # التحقق من حجم الملف (10MB كحد أقصى)
        if image_file.size > 10 * 1024 * 1024:
            return Response({
                'success': False,
                'detail': 'File size must be less than 10MB',
                'error_code': 'FILE_TOO_LARGE',
                'max_size': '10MB',
                'current_size': f"{image_file.size / 1024 / 1024:.1f}MB"
            }, status=400)
        
        # إعادة تعيين مؤشر الملف
        image_file.seek(0)
        
        print(f"🎯 Processing image: {image_file.name} ({image_file.size} bytes)")
        
        # إزالة الخلفية
        result_image_data = remove_background_u2net(image_file)
        
        # إرجاع النتيجة كـ PNG
        response = HttpResponse(result_image_data, content_type='image/png')
        
        # إضافة اسم ملف مع تاريخ ووقت
        timestamp = uuid.uuid4().hex[:8]
        filename = f"no-background-{timestamp}.png"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        # إضافة معلومات في الheaders
        response['X-Processing-Time'] = 'completed'
        response['X-Image-Size'] = str(len(result_image_data))
        
        print(f"✅ Successfully processed: {image_file.name} -> {filename}")
        return response
        
    except ValueError as e:
        print(f"⚠️ Validation error in remove_background: {e}")
        return Response({
            'success': False,
            'detail': str(e),
            'error_code': 'VALIDATION_ERROR'
        }, status=400)
    except Exception as e:
        print(f"❌ Error in remove_background: {e}")
        traceback.print_exc()
        return Response({
            'success': False,
            'detail': f'Error processing image: {str(e)}',
            'error_code': 'PROCESSING_ERROR'
        }, status=500)

@api_view(['GET'])
def health_check(request):
    """فحص حالة الخادم والنموذج"""
    model_status = "loaded" if model_session is not None else "not loaded"
    model_exists = os.path.exists(MODEL_PATH)
    
    return Response({
        'status': 'healthy',
        'service': 'Background Removal API',
        'version': '1.0.0',
        'model': {
            'status': model_status,
            'path': MODEL_PATH,
            'exists': model_exists,
            'loaded': model_session is not None
        },
        'system': {
            'python_version': os.sys.version,
            'django_version': '6.0.2',
            'numpy_version': np.__version__,
            'opencv_version': cv2.__version__,
            'pillow_version': Image.__version__
        }
    })

@api_view(['POST'])
def remove_background_from_url(request):
    """إزالة الخلفية من صورة عبر URL"""
    try:
        import requests
        from urllib.parse import urlparse
        
        url = request.data.get('url')
        if not url:
            return Response({
                'success': False,
                'detail': 'No URL provided',
                'error_code': 'NO_URL'
            }, status=400)
        
        # التحقق من صحة URL
        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            return Response({
                'success': False,
                'detail': 'Invalid URL',
                'error_code': 'INVALID_URL'
            }, status=400)
        
        # التحقق من أن الرابط آمن (تطويري فقط)
        if not url.startswith(('http://', 'https://')):
            return Response({
                'success': False,
                'detail': 'URL must start with http:// or https://',
                'error_code': 'INSECURE_URL'
            }, status=400)
        
        print(f"🌐 Downloading image from URL: {url}")
        
        # تنزيل الصورة
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return Response({
                'success': False,
                'detail': f'Failed to download image: HTTP {response.status_code}',
                'error_code': 'DOWNLOAD_FAILED'
            }, status=400)
        
        # التحقق من نوع المحتوى
        content_type = response.headers.get('content-type', '').lower()
        valid_types = ['image/jpeg', 'image/png', 'image/webp', 'image/bmp']
        
        if not any(img_type in content_type for img_type in valid_types):
            # محاولة التحقق من المحتوى نفسه
            from PIL import Image as PILImage
            from io import BytesIO
            
            try:
                # محاولة فتح الصورة للتحقق
                img_test = PILImage.open(BytesIO(response.content))
                img_test.verify()  # التحقق من أن البيانات صورة صالحة
            except:
                return Response({
                    'success': False,
                    'detail': 'URL does not point to a valid image',
                    'error_code': 'NOT_AN_IMAGE'
                }, status=400)
        
        # التحقق من حجم الملف
        if len(response.content) > 10 * 1024 * 1024:
            return Response({
                'success': False,
                'detail': 'Image from URL is too large (max 10MB)',
                'error_code': 'FILE_TOO_LARGE'
            }, status=400)
        
        # إنشاء ملف في الذاكرة
        from django.core.files.base import ContentFile
        image_file = ContentFile(response.content, name='downloaded_image.jpg')
        
        # إزالة الخلفية
        result_image_data = remove_background_u2net(image_file)
        
        # إرجاع النتيجة
        response_http = HttpResponse(result_image_data, content_type='image/png')
        timestamp = uuid.uuid4().hex[:8]
        response_http['Content-Disposition'] = f'attachment; filename="no-background-{timestamp}.png"'
        
        print(f"✅ Successfully processed image from URL")
        return response_http
        
    except requests.exceptions.Timeout:
        return Response({
            'success': False,
            'detail': 'Download timeout. Please try again.',
            'error_code': 'TIMEOUT'
        }, status=408)
    except requests.exceptions.RequestException as e:
        return Response({
            'success': False,
            'detail': f'Network error: {str(e)}',
            'error_code': 'NETWORK_ERROR'
        }, status=400)
    except Exception as e:
        print(f"❌ Error in remove_background_from_url: {e}")
        traceback.print_exc()
        return Response({
            'success': False,
            'detail': f'Error processing image: {str(e)}',
            'error_code': 'PROCESSING_ERROR'
        }, status=500)
    
from django.shortcuts import render
from django.urls import reverse
from datetime import datetime
import os
from . import wordtopdf

RUNTIME_TOOL_CHOICES = {"libreoffice", "imagemagick", "ffmpeg"}


def _run_runtime_tool_test(tool_name):
    """Run lightweight runtime checks and return normalized error codes."""
    import subprocess

    if tool_name == "libreoffice":
        from . import libreoffice

        soffice_path = libreoffice.find_soffice_path()
        if not soffice_path:
            return {
                "tool": "LibreOffice",
                "available": False,
                "error_code": "LIBREOFFICE_NOT_FOUND",
                "error_detail": "LibreOffice executable was not found in PATH or known install paths.",
            }
        version = libreoffice.get_libreoffice_version(soffice_path)
        return {
            "tool": "LibreOffice",
            "available": True,
            "error_code": None,
            "version": version or "unknown",
            "binary_path": soffice_path,
        }

    if tool_name == "imagemagick":
        from . import image_services

        magick_path = image_services._find_magick_command()
        if not magick_path:
            return {
                "tool": "ImageMagick",
                "available": False,
                "error_code": "IMAGEMAGICK_NOT_FOUND",
                "error_detail": "ImageMagick executable was not found in PATH or known install paths.",
            }
        try:
            result = subprocess.run(
                [magick_path, "--version"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if result.returncode != 0:
                details = (result.stderr or result.stdout or "").strip() or "version command failed"
                return {
                    "tool": "ImageMagick",
                    "available": False,
                    "error_code": "IMAGEMAGICK_VERSION_FAILED",
                    "error_detail": details,
                    "binary_path": magick_path,
                }
            version = (result.stdout or result.stderr or "").splitlines()[0].strip()
            return {
                "tool": "ImageMagick",
                "available": True,
                "error_code": None,
                "version": version or "unknown",
                "binary_path": magick_path,
            }
        except subprocess.TimeoutExpired:
            return {
                "tool": "ImageMagick",
                "available": False,
                "error_code": "IMAGEMAGICK_TIMEOUT",
                "error_detail": "ImageMagick version command timed out.",
                "binary_path": magick_path,
            }
        except Exception as exc:
            return {
                "tool": "ImageMagick",
                "available": False,
                "error_code": "IMAGEMAGICK_CHECK_ERROR",
                "error_detail": str(exc),
                "binary_path": magick_path,
            }

    if tool_name == "ffmpeg":
        from . import MediaCommon

        ffmpeg_path = MediaCommon._find_ffmpeg()
        if not ffmpeg_path:
            return {
                "tool": "FFmpeg",
                "available": False,
                "error_code": "FFMPEG_NOT_FOUND",
                "error_detail": "FFmpeg executable was not found in PATH or known install paths.",
            }
        try:
            result = subprocess.run(
                [ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if result.returncode != 0:
                details = (result.stderr or result.stdout or "").strip() or "version command failed"
                return {
                    "tool": "FFmpeg",
                    "available": False,
                    "error_code": "FFMPEG_VERSION_FAILED",
                    "error_detail": details,
                    "binary_path": ffmpeg_path,
                }
            version = (result.stdout or result.stderr or "").splitlines()[0].strip()
            return {
                "tool": "FFmpeg",
                "available": True,
                "error_code": None,
                "version": version or "unknown",
                "binary_path": ffmpeg_path,
            }
        except subprocess.TimeoutExpired:
            return {
                "tool": "FFmpeg",
                "available": False,
                "error_code": "FFMPEG_TIMEOUT",
                "error_detail": "FFmpeg version command timed out.",
                "binary_path": ffmpeg_path,
            }
        except Exception as exc:
            return {
                "tool": "FFmpeg",
                "available": False,
                "error_code": "FFMPEG_CHECK_ERROR",
                "error_detail": str(exc),
                "binary_path": ffmpeg_path,
            }

    return {
        "tool": tool_name,
        "available": False,
        "error_code": "INVALID_TOOL",
        "error_detail": "Unsupported tool requested for runtime test.",
    }


@login_required(login_url="/")
def test_download(request):
    """Test page for download links across all converters."""
    files = []
    selected_tool = "libreoffice"
    test_result = None
    form_error_code = None
    form_error_detail = None
    is_admin_tester = bool(getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False))

    if request.method == "POST":
        selected_tool = (request.POST.get("tool_name") or "").strip().lower()
        if selected_tool not in RUNTIME_TOOL_CHOICES:
            form_error_code = "TOOL_NAME_REQUIRED"
            form_error_detail = "Please select one of: LibreOffice, ImageMagick, or FFmpeg."
        else:
            test_result = _run_runtime_tool_test(selected_tool)

    def _append_file(path, filename, url_name, url_arg, source):
        """إضافة ملف مع التحقق من وجوده وإمكانية الوصول إليه"""
        try:
            # التحقق من وجود الملف قبل محاولة قراءة خصائصه
            if not os.path.exists(path):
                print(f"⚠️ الملف غير موجود: {path}")  # سجل الخطأ
                return
            
            # التحقق من صلاحيات القراءة للملف
            if not os.access(path, os.R_OK):
                print(f"🔒 لا توجد صلاحيات قراءة للملف: {path}")
                return
            
            files.append({
                'filename': filename,
                'size': os.path.getsize(path),
                'modified': datetime.fromtimestamp(os.path.getmtime(path)),
                'url': request.build_absolute_uri(reverse(url_name, args=[url_arg])),
                'source': source,
                'exists': True,  # تأكيد وجود الملف
                'path': path,     # المسار الكامل للمساعدة في التصحيح
            })
        except OSError as e:
            # خطأ في نظام الملفات (مثلاً: الملف محذوف أو تالف)
            print(f"💥 خطأ في قراءة خصائص الملف {path}: {str(e)}")
            files.append({
                'filename': filename,
                'error': str(e),
                'source': source,
                'exists': False,
                'url': None,
            })
        except Exception as e:
            # أي خطأ آخر غير متوقع
            print(f"🔥 خطأ غير متوقع للملف {path}: {str(e)}")
            files.append({
                'filename': filename,
                'error': f"خطأ غير متوقع: {str(e)}",
                'source': source,
                'exists': False,
                'url': None,
            })

    # Legacy word-to-pdf files
    try:
        word_pdf_dir = wordtopdf._ensure_files_directory()
        # التحقق من وجود المجلد
        if not os.path.exists(word_pdf_dir):
            print(f"❌ مجلد Word to PDF غير موجود: {word_pdf_dir}")
        elif not os.access(word_pdf_dir, os.R_OK):
            print(f"🔒 لا توجد صلاحيات قراءة لمجلد Word to PDF: {word_pdf_dir}")
        else:
            for name in os.listdir(word_pdf_dir):
                if not name.lower().endswith('.pdf'):
                    continue
                file_path = os.path.join(word_pdf_dir, name)
                if os.path.isfile(file_path):
                    _append_file(file_path, name, 'download_converted_file', name, 'Word to PDF')
    except PermissionError:
        print(f"🔒 خطأ في صلاحيات الوصول لمجلد Word to PDF")
    except Exception as e:
        print(f"💥 خطأ في قراءة مجلد Word to PDF: {str(e)}")

    # /api/convert/download/<file_id>/ files
    try:
        from . import libreoffice_services
        convert_dir = libreoffice_services._output_dir()
        # التحقق من وجود المجلد
        if not os.path.exists(convert_dir):
            print(f"❌ مجلد File Converter غير موجود: {convert_dir}")
        elif not os.access(convert_dir, os.R_OK):
            print(f"🔒 لا توجد صلاحيات قراءة لمجلد File Converter: {convert_dir}")
        else:
            valid_exts = set(libreoffice_services.MIME_TYPES.keys())
            for name in os.listdir(convert_dir):
                file_path = os.path.join(convert_dir, name)
                if not os.path.isfile(file_path):
                    continue
                ext = os.path.splitext(name)[1].lower().lstrip('.')
                if ext not in valid_exts:
                    continue
                file_id = os.path.splitext(name)[0]
                _append_file(file_path, name, 'download_converted_file_once', file_id, 'File Converter')
    except ImportError:
        print("❌ وحدة libreoffice_services غير موجودة")
    except PermissionError:
        print(f"🔒 خطأ في صلاحيات الوصول لمجلد File Converter")
    except Exception as e:
        print(f"💥 خطأ في قراءة مجلد File Converter: {str(e)}")

    # /api/image/download/<file_id>/ files
    try:
        from . import image_services
        image_dir = image_services._output_dir()
        # التحقق من وجود المجلد
        if not os.path.exists(image_dir):
            print(f"❌ مجلد Image Tools غير موجود: {image_dir}")
        elif not os.access(image_dir, os.R_OK):
            print(f"🔒 لا توجد صلاحيات قراءة لمجلد Image Tools: {image_dir}")
        else:
            valid_exts = set(image_services.IMAGE_MIME_TYPES.keys())
            for name in os.listdir(image_dir):
                file_path = os.path.join(image_dir, name)
                if not os.path.isfile(file_path):
                    continue
                ext = os.path.splitext(name)[1].lower().lstrip('.')
                if ext not in valid_exts:
                    continue
                file_id = os.path.splitext(name)[0]
                _append_file(file_path, name, 'download_image_file_once', file_id, 'Image Tools')
    except ImportError:
        print("❌ وحدة image_services غير موجودة")
    except PermissionError:
        print(f"🔒 خطأ في صلاحيات الوصول لمجلد Image Tools")
    except Exception as e:
        print(f"💥 خطأ في قراءة مجلد Image Tools: {str(e)}")

    # /api/convert/video/download/<file_id>/ files (media_tools videos)
    try:
        from . import MediaCommon
        media_dir = MediaCommon._output_dir()
        if not os.path.exists(media_dir):
            print(f"❌ مجلد Media Tools غير موجود: {media_dir}")
        elif not os.access(media_dir, os.R_OK):
            print(f"🔒 لا توجد صلاحيات قراءة لمجلد Media Tools: {media_dir}")
        else:
            video_exts = set(MediaCommon.VIDEO_MIME_TYPES.keys())
            for name in os.listdir(media_dir):
                file_path = os.path.join(media_dir, name)
                if not os.path.isfile(file_path):
                    continue
                ext = os.path.splitext(name)[1].lower().lstrip('.')
                if ext not in video_exts:
                    continue
                file_id = os.path.splitext(name)[0]
                _append_file(file_path, name, 'convert_video_download', file_id, 'Media Tools (Video)')
    except ImportError:
        print("❌ وحدة MediaCommon غير موجودة")
    except PermissionError:
        print("🔒 خطأ في صلاحيات الوصول لمجلد Media Tools")
    except Exception as e:
        print(f"💥 خطأ في قراءة مجلد Media Tools: {str(e)}")

    # ترتيب الملفات حسب تاريخ التعديل (الأحدث أولاً)
    try:
        files.sort(key=lambda x: x.get('modified', datetime.min), reverse=True)
    except Exception as e:
        print(f"⚠️ خطأ في ترتيب الملفات: {str(e)}")


    return render(
        request,
        'test_download.html',
        {
            'files': files,
            'tool_choices': [
                {"value": "libreoffice", "label": "LibreOffice"},
                {"value": "imagemagick", "label": "ImageMagick"},
                {"value": "ffmpeg", "label": "FFmpeg"},
            ],
            'selected_tool': selected_tool,
            'test_result': test_result,
            'form_error_code': form_error_code,
            'form_error_detail': form_error_detail if is_admin_tester else None,
            'is_admin_tester': is_admin_tester,
        },
    )


logger = logging.getLogger(__name__)

@require_http_methods(["POST"])
def save_page(request):
    """
    API لحفظ صفحة جديدة - يحفظ فقط الرابط والحالة
    """
    try:
        data = json.loads(request.body)
        
        url = data.get('url')
        if not url:
            return JsonResponse({
                'success': False,
                'error': 'URL is required'
            }, status=400)
        
        # استخراج المسار من الـ URL
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        path = parsed_url.path or '/'
        
        # الحالة (افتراضي pending إذا لم ترسل)
        status = data.get('status', 'pending')
        
        # معلومات إضافية اختيارية
        name = data.get('name', '')
        category = data.get('category', '')
        
        # البحث عن الصفحة بالـ URL (فريد)
        page, created = PageStatus.objects.get_or_create(
            url=url,  # نستخدم url كمعرف فريد كما هو محدد في الموديل
            defaults={
                'path': path,
                'name': name,
                'category': category,
                'status': status,
                'created_at': timezone.now(),
            }
        )
        
        if not created:
            # تحديث المعلومات الأساسية فقط
            page.path = path
            if name:
                page.name = name
            if category:
                page.category = category
            if status:
                page.status = status
            page.updated_at = timezone.now()
            page.save(update_fields=['path', 'name', 'category', 'status', 'updated_at'])
            
            return JsonResponse({
                'success': True,
                'message': 'Page updated successfully',
                'page': {
                    'id': page.id,
                    'url': page.url,
                    'path': page.path,
                    'status': page.status
                }
            })
        
        return JsonResponse({
            'success': True,
            'message': 'Page saved successfully',
            'page': {
                'id': page.id,
                'url': page.url,
                'path': page.path,
                'status': page.status
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON'
        }, status=400)
    except Exception as e:
        logger.error(f"Error saving page: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def save_multiple_pages(request):
    """
    API لحفظ صفحات متعددة في طلب واحد
    """
    try:
        data = json.loads(request.body)
        pages = data.get('pages', [])
        
        if not pages:
            return JsonResponse({
                'success': False,
                'error': 'Pages list is required'
            }, status=400)
        
        saved_count = 0
        updated_count = 0
        results = []
        
        for page_data in pages:
            url = page_data.get('url')
            if not url:
                continue
            
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            path = parsed_url.path or '/'
            
            page, created = PageStatus.objects.get_or_create(
                url=url,
                defaults={
                    'path': path,
                    'name': page_data.get('name', ''),
                    'category': page_data.get('category', ''),
                    'status': page_data.get('status', 'pending'),
                    'created_at': timezone.now(),
                }
            )
            
            if created:
                saved_count += 1
            else:
                updated_count += 1
                # تحديث إذا أردت
            
            results.append({
                'url': url,
                'status': page.status,
                'created': created
            })
        
        return JsonResponse({
            'success': True,
            'message': f'Saved: {saved_count}, Updated: {updated_count}',
            'saved': saved_count,
            'updated': updated_count,
            'results': results
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON'
        }, status=400)
    except Exception as e:
        logger.error(f"Error saving multiple pages: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
def get_page_by_url(request):
    """
    API لجلب صفحة بواسطة URL
    """
    url = request.GET.get('url')
    if not url:
        return JsonResponse({
            'success': False,
            'error': 'URL parameter is required'
        }, status=400)
    
    try:
        page = PageStatus.objects.get(url=url)
        return JsonResponse({
            'success': True,
            'page': {
                'id': page.id,
                'url': page.url,
                'path': page.path,
                'name': page.name,
                'category': page.category,
                'status': page.status,
                'created_at': page.created_at,
                'updated_at': page.updated_at
            }
        })
    except PageStatus.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Page not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
def get_all_pages(request):
    """
    API لجلب جميع الصفحات المحفوظة
    """
    try:
        pages = PageStatus.objects.all().values(
            'id', 'url', 'path', 'name', 'category', 'status', 'created_at', 'updated_at'
        )
        
        return JsonResponse({
            'success': True,
            'pages': list(pages),
            'count': pages.count()
        })
        
    except Exception as e:
        logger.error(f"Error getting pages: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.utils import timezone
from django.db.models import Q
import json
import logging
from .models import PageStatus

logger = logging.getLogger(__name__)

# ... الكود السابق ...

@require_http_methods(["GET"])
@api_view(['GET'])
def admin_get_pages(request):
    """
    API للإدارة - جلب الصفحات مع فلترة وبحث
    """
    try:
        # فلترة حسب الحالة
        status_filter = request.GET.get('status')
        search_query = request.GET.get('search')
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        
        # بناء query
        queryset = PageStatus.objects.all()
        
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        if search_query:
            queryset = queryset.filter(
                Q(url__icontains=search_query) |
                Q(title__icontains=search_query) |
                Q(path__icontains=search_query)
            )
        
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        
        # ترتيب
        queryset = queryset.order_by('-created_at')
        
        # Pagination
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 50))
        paginator = Paginator(queryset, page_size)
        
        current_page = paginator.get_page(page)
        
        # تجهيز البيانات
        pages_data = []
        for page_obj in current_page:
            pages_data.append({
                'id': page_obj.id,
                'url': page_obj.url,
                'path': page_obj.path,
                'name': page_obj.name,
                'category': page_obj.category,
                'status': page_obj.status,
                'title': page_obj.title,
                'meta_description': page_obj.meta_description,
                'last_checked': page_obj.last_checked,
                'response_time': page_obj.response_time,
                'http_status': page_obj.http_status,
                'error_message': page_obj.error_message,
                'check_count': page_obj.check_count,
                'failure_count': page_obj.failure_count,
                'is_dynamic': page_obj.is_dynamic,
                'created_at': page_obj.created_at,
                'updated_at': page_obj.updated_at,
            })
        
        return JsonResponse({
            'success': True,
            'results': pages_data,
            'total': paginator.count,
            'page': page,
            'page_size': page_size,
            'total_pages': paginator.num_pages,
        })
        
    except Exception as e:
        logger.error(f"Error in admin_get_pages: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET", "PUT", "PATCH", "DELETE"])
def admin_page_detail(request, page_id):
    """
    API للإدارة - جلب، تحديث، أو حذف صفحة محددة
    """
    try:
        try:
            page = PageStatus.objects.get(id=page_id)
        except PageStatus.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Page not found'
            }, status=404)
        
        if request.method == "GET":
            # جلب تفاصيل الصفحة
            return JsonResponse({
                'success': True,
                'id': page.id,
                'url': page.url,
                'path': page.path,
                'name': page.name,
                'category': page.category,
                'status': page.status,
                'title': page.title,
                'meta_description': page.meta_description,
                'last_checked': page.last_checked,
                'response_time': page.response_time,
                'http_status': page.http_status,
                'error_message': page.error_message,
                'check_count': page.check_count,
                'failure_count': page.failure_count,
                'is_dynamic': page.is_dynamic,
                'parameter_pattern': page.parameter_pattern,
                'created_at': page.created_at,
                'updated_at': page.updated_at,
            })
        
        elif request.method in ["PUT", "PATCH"]:
            # تحديث الصفحة
            data = json.loads(request.body)
            
            # تحديث الحقول المرسلة فقط
            if 'url' in data and data['url'] != page.url:
                # التحقق من عدم تكرار الـ URL
                if PageStatus.objects.filter(url=data['url']).exclude(id=page_id).exists():
                    return JsonResponse({
                        'success': False,
                        'error': 'URL already exists'
                    }, status=400)
                page.url = data['url']
                # تحديث المسار أيضاً
                from urllib.parse import urlparse
                parsed_url = urlparse(data['url'])
                page.path = parsed_url.path or '/'
            
            if 'name' in data:
                page.name = data['name']
            
            if 'category' in data:
                page.category = data['category']
            
            if 'status' in data:
                page.status = data['status']
            
            if 'title' in data:
                page.title = data['title']
            
            if 'meta_description' in data:
                page.meta_description = data['meta_description']
            
            if 'is_dynamic' in data:
                page.is_dynamic = data['is_dynamic']
            
            if 'parameter_pattern' in data:
                page.parameter_pattern = data['parameter_pattern']
            
            page.updated_at = timezone.now()
            page.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Page updated successfully',
                'page': {
                    'id': page.id,
                    'url': page.url,
                    'path': page.path,
                    'name': page.name,
                    'category': page.category,
                    'status': page.status,
                }
            })
        
        elif request.method == "DELETE":
            # حذف الصفحة
            page.delete()
            return JsonResponse({
                'success': True,
                'message': 'Page deleted successfully'
            })
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON'
        }, status=400)
    except Exception as e:
        logger.error(f"Error in admin_page_detail: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def admin_bulk_update(request):
    """
    API للإدارة - تحديث مجموعة من الصفحات
    """
    try:
        data = json.loads(request.body)
        ids = data.get('ids', [])
        update_data = data.get('data', {})
        
        if not ids:
            return JsonResponse({
                'success': False,
                'error': 'No page IDs provided'
            }, status=400)
        
        if not update_data:
            return JsonResponse({
                'success': False,
                'error': 'No update data provided'
            }, status=400)
        
        # تحديث الصفحات
        updated_count = PageStatus.objects.filter(id__in=ids).update(
            **update_data,
            updated_at=timezone.now()
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Updated {updated_count} pages',
            'updated_count': updated_count
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON'
        }, status=400)
    except Exception as e:
        logger.error(f"Error in admin_bulk_update: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def admin_bulk_delete(request):
    """
    API للإدارة - حذف مجموعة من الصفحات
    """
    try:
        data = json.loads(request.body)
        ids = data.get('ids', [])
        
        if not ids:
            return JsonResponse({
                'success': False,
                'error': 'No page IDs provided'
            }, status=400)
        
        # حذف الصفحات
        deleted_count = PageStatus.objects.filter(id__in=ids).delete()[0]
        
        return JsonResponse({
            'success': True,
            'message': f'Deleted {deleted_count} pages',
            'deleted_count': deleted_count
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON'
        }, status=400)
    except Exception as e:
        logger.error(f"Error in admin_bulk_delete: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
def admin_get_stats(request):
    """
    API للإدارة - جلب إحصائيات الصفحات
    """
    try:
        total = PageStatus.objects.count()
        working = PageStatus.objects.filter(status='working').count()
        not_working = PageStatus.objects.filter(status='not_working').count()
        pending = PageStatus.objects.filter(status='pending').count()
        reprocess = PageStatus.objects.filter(status='reprocess').count()
        
        # إحصائيات إضافية
        total_checks = PageStatus.objects.aggregate(total=models.Sum('check_count'))['total'] or 0
        avg_response = PageStatus.objects.filter(
            response_time__isnull=False
        ).aggregate(avg=models.Avg('response_time'))['avg']
        
        return JsonResponse({
            'success': True,
            'stats': {
                'total': total,
                'working': working,
                'not_working': not_working,
                'pending': pending,
                'reprocess': reprocess,
                'total_checks': total_checks,
                'avg_response_time': avg_response,
            }
        })
        
    except Exception as e:
        logger.error(f"Error in admin_get_stats: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


