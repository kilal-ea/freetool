import json
import os
import tempfile
import pythoncom
import win32com.client
from datetime import datetime
from io import BytesIO
from django.http import FileResponse, JsonResponse
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def convert_excel_to_pdf(request):
    """
    Convert an uploaded Excel file to PDF using Microsoft Excel (via win32com).
    All original formatting, styles, colors, and fonts are preserved exactly
    as they appear when opening the file in Excel.
    """
    # --- 1. Validate input ---
    excel_file = request.FILES.get('excel_file')
    if not excel_file:
        return JsonResponse({
            'success': False,
            'error': 'No Excel file provided.'
        }, status=400)

    # --- 2. Parse PDF settings (optional) ---
    pdf_settings = request.POST.get('pdf_settings', '{}')
    try:
        pdf_settings = json.loads(pdf_settings)
    except json.JSONDecodeError:
        pdf_settings = {}

    # Map user-friendly settings to Excel constants
    orientation_map = {
        'portrait': 1,      # xlPortrait
        'landscape': 2,     # xlLandscape
    }
    page_size_map = {
        'A4': 9,            # xlPaperA4
        'A3': 8,            # xlPaperA3
        'Letter': 1,        # xlPaperLetter
        'A5': 11,           # xlPaperA5
        'B4': 12,           # xlPaperB4
        'B5': 13,           # xlPaperB5
    }

    # Extract settings with defaults
    page_size = pdf_settings.get('pageSize', 'A4')
    orientation = pdf_settings.get('orientation', 'landscape')  # تغيير الافتراضي إلى landscape
    fit_to_page = pdf_settings.get('fitToPage', True)
    scale_to_fit = pdf_settings.get('scaleToFit', True)  # إعداد جديد للتحكم في القياس
    print_area = pdf_settings.get('printArea', 'entire-workbook')

    # --- 3. Save uploaded file to a temporary location ---
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp_excel:
        tmp_excel_path = tmp_excel.name
        for chunk in excel_file.chunks():
            tmp_excel.write(chunk)

    # Determine output PDF path (same name, different extension)
    tmp_pdf_path = tmp_excel_path.replace('.xlsx', '.pdf')

    # --- 4. Convert using Excel ---
    excel_app = None
    workbook = None
    try:
        # Initialize COM for this thread (required in multi-threaded Django)
        pythoncom.CoInitialize()

        # Launch Excel application (invisible)
        excel_app = win32com.client.Dispatch("Excel.Application")
        excel_app.Visible = False
        excel_app.DisplayAlerts = False

        # Open the workbook
        workbook = excel_app.Workbooks.Open(tmp_excel_path)

        # --- تطبيق إعدادات الصفحة لجميع الأوراق ---
        for sheet in workbook.Sheets:
            # تفعيل الورقة
            sheet.Activate()
            
            # تعيين الاتجاه (portrait/landscape)
            if orientation in orientation_map:
                sheet.PageSetup.Orientation = orientation_map[orientation]
            
            # تعيين حجم الورق
            if page_size in page_size_map:
                sheet.PageSetup.PaperSize = page_size_map[page_size]
            
            # ضبط الهوامش لتكون صغيرة للاستفادة القصوى من المساحة
            sheet.PageSetup.LeftMargin = excel_app.InchesToPoints(0.2)
            sheet.PageSetup.RightMargin = excel_app.InchesToPoints(0.2)
            sheet.PageSetup.TopMargin = excel_app.InchesToPoints(0.3)
            sheet.PageSetup.BottomMargin = excel_app.InchesToPoints(0.3)
            sheet.PageSetup.HeaderMargin = excel_app.InchesToPoints(0.1)
            sheet.PageSetup.FooterMargin = excel_app.InchesToPoints(0.1)
            
            # ضبط المحتوى ليلائم صفحة واحدة عرضاً
            if scale_to_fit:
                # ضبط ليلائم صفحة واحدة عرضاً
                sheet.PageSetup.FitToPagesWide = 1
                # تحديد عدد الصفحات طولياً (False يعني تلقائي)
                sheet.PageSetup.FitToPagesTall = False
            else:
                # تكبير/تصغير المحتوى ليناسب الصفحة (بدون تقسيم)
                if fit_to_page:
                    sheet.PageSetup.Zoom = False
                    sheet.PageSetup.FitToPagesWide = 1
                    sheet.PageSetup.FitToPagesTall = False
                else:
                    sheet.PageSetup.Zoom = True
                    # يمكنك تحديد نسبة تكبير معينة هنا
                    sheet.PageSetup.Zoom = 100  # أو أي نسبة تناسبك
            
            # ضبط المنطقة المطبوعة لتشمل كل البيانات المستخدمة
            try:
                # تحديد آخر خلية مستخدمة
                last_row = sheet.UsedRange.Rows.Count
                last_col = sheet.UsedRange.Columns.Count
                
                # تعيين منطقة الطباعة
                if last_row > 0 and last_col > 0:
                    print_area_range = f"A1:{chr(64 + min(last_col, 26))}{last_row}"
                    sheet.PageSetup.PrintArea = print_area_range
                    
                    # تكبير/تصغير تلقائي ليلائم العرض
                    if fit_to_page:
                        sheet.PageSetup.Zoom = False
                        sheet.PageSetup.FitToPagesWide = 1
                        sheet.PageSetup.FitToPagesTall = False
            except:
                pass  # إذا فشل تعيين منطقة الطباعة، نستمر
            
            # إضافة خطوط الشبكة (اختياري)
            sheet.PageSetup.PrintGridlines = True
            
            # توسيط المحتوى أفقياً
            sheet.PageSetup.CenterHorizontally = True
            
            # توسيط المحتوى عمودياً (اختياري)
            sheet.PageSetup.CenterVertically = False

        # --- تصدير إلى PDF مع إعدادات محسنة ---
        workbook.ExportAsFixedFormat(
            Type=0,  # xlTypePDF
            Filename=tmp_pdf_path,
            Quality=0,  # xlQualityStandard
            IncludeDocProperties=True,
            IgnorePrintAreas=False if print_area == 'entire-workbook' else True,
            From=1,  # من الصفحة الأولى
            To=None,  # إلى آخر صفحة
            OpenAfterPublish=False  # لا تفتح PDF بعد النشر
        )

    except Exception as e:
        # تنظيف في حالة الخطأ
        try:
            if workbook:
                workbook.Close(SaveChanges=False)
            if excel_app:
                excel_app.Quit()
        except:
            pass
        return JsonResponse({
            'success': False,
            'error': f'Excel conversion failed: {str(e)}'
        }, status=500)

    finally:
        # التأكد من إغلاق Excel
        try:
            if workbook:
                workbook.Close(SaveChanges=False)
            if excel_app:
                excel_app.Quit()
        except:
            pass
        
        # إلغاء تهيئة COM
        pythoncom.CoUninitialize()

        # حذف ملف Excel المؤقت
        try:
            if os.path.exists(tmp_excel_path):
                os.unlink(tmp_excel_path)
        except Exception:
            pass

    # --- 5. التحقق من إنشاء PDF ---
    if not os.path.exists(tmp_pdf_path):
        return JsonResponse({
            'success': False,
            'error': 'PDF file was not created by Excel'
        }, status=500)

    # --- 6. قراءة محتوى PDF إلى الذاكرة ---
    with open(tmp_pdf_path, 'rb') as f:
        pdf_content = f.read()

    # --- 7. حذف ملف PDF المؤقت ---
    try:
        if os.path.exists(tmp_pdf_path):
            os.unlink(tmp_pdf_path)
    except Exception:
        pass

    # --- 8. إنشاء اسم ملف التحميل ---
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_name = excel_file.name.split('.')[0]
    filename = f'{base_name}_{timestamp}.pdf'

    # --- 9. إرجاع PDF كملف قابل للتحميل ---
    return FileResponse(
        BytesIO(pdf_content),
        content_type='application/pdf',
        as_attachment=True,
        filename=filename
    )