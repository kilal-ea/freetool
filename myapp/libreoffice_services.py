import os
import tempfile
import threading
import uuid
from datetime import datetime
from io import BytesIO

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser

from .libreoffice import find_converted_file, run_convert


WORD_EXTENSIONS = {".doc", ".docx", ".odt", ".rtf", ".txt"}
EXCEL_EXTENSIONS = {".xls", ".xlsx", ".ods", ".csv"}
POWERPOINT_EXTENSIONS = {".ppt", ".pptx", ".odp"}
PDF_EXTENSIONS = {".pdf"}


MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

PDF_AUTO_DELETE_SECONDS = 180

def test_word_to_pdf_page(request):
    return render(request, 'test_word_to_pdf.html')


def _with_cors_headers(request, response):
    origin = request.META.get("HTTP_ORIGIN")
    if origin:
        response["Access-Control-Allow-Origin"] = origin
        response["Access-Control-Allow-Credentials"] = "true"
        response["Vary"] = "Origin"
    else:
        response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    response["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Length"
    return response


def _is_pdf_path(path):
    return os.path.splitext(str(path))[1].lower() == ".pdf"


def _fallback_pdf_to_excel_bytes(pdf_bytes):
    try:
        import pandas as pd
        import pdfplumber
    except Exception:
        return None, "Fallback dependencies missing (pdfplumber/pandas)."

    tables_data = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    if not table:
                        continue
                    if table[0]:
                        df = pd.DataFrame(table[1:], columns=table[0])
                    else:
                        df = pd.DataFrame(table)
                    tables_data.append(df)
    except Exception as exc:
        return None, f"Fallback table extraction failed: {exc}"

    if not tables_data:
        return None, "No extractable tables found in PDF."

    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for idx, df in enumerate(tables_data, start=1):
            df.to_excel(writer, sheet_name=f"Table_{idx}", index=False)
    return out.getvalue(), None


def _output_dir():
    base_dir = getattr(settings, "MEDIA_ROOT", None)
    if not base_dir:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        base_dir = os.path.join(project_root, "media")

    output_dir = os.path.join(base_dir, "libreoffice_converted")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _safe_name(name):
    return os.path.basename(name).replace(" ", "_")


def _get_uploaded_file(request, primary_key):
    return request.FILES.get(primary_key) or request.FILES.get("file")


def _validate_extension(uploaded_file, allowed_extensions):
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in allowed_extensions:
        return ext
    return None


def _build_filename(original_name, target_extension):
    base_name = os.path.splitext(_safe_name(original_name))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base_name}_{timestamp}.{target_extension}"


def _try_convert(input_path, output_dir, attempts, expected_extensions):
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    last_error = None

    for convert_to, infilter in attempts:
        _, error = run_convert(
            input_path,
            output_dir,
            convert_to,
            infilter=infilter,
            timeout=180,
        )
        if error:
            last_error = error
            continue

        converted_file = find_converted_file(output_dir, base_name, expected_extensions)
        if converted_file and os.path.exists(converted_file):
            return converted_file, None

    return None, last_error


def _schedule_file_deletion(file_path, delay_seconds):
    def delete_file():
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"[Backend] Auto-deleted file after {delay_seconds} seconds: {file_path}")
        except Exception as exc:
            print(f"[Backend] Failed auto-delete for {file_path}: {exc}")

    timer = threading.Timer(delay_seconds, delete_file)
    timer.daemon = True
    timer.start()


def _save_converted_output(output_bytes, output_extension, auto_delete_seconds=None):
    file_id = uuid.uuid4().hex
    stored_name = f"{file_id}.{output_extension}"
    stored_path = os.path.join(_output_dir(), stored_name)

    with open(stored_path, "wb") as f:
        f.write(output_bytes)

    if auto_delete_seconds and auto_delete_seconds > 0:
        _schedule_file_deletion(stored_path, auto_delete_seconds)

    return file_id, stored_path


def _download_url(request, file_id):
    relative_url = f"/api/convert/download/{file_id}/"
    return request.build_absolute_uri(relative_url)


def _convert_request_file(
    request,
    file_key,
    allowed_extensions,
    attempts,
    expected_extensions,
    output_extension,
):
    def _as_bool(value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    uploaded_file = _get_uploaded_file(request, file_key)
    if not uploaded_file:
        return JsonResponse({"success": False, "error": f"No file provided in '{file_key}' or 'file'."}, status=400)

    invalid_ext = _validate_extension(uploaded_file, allowed_extensions)
    if invalid_ext:
        supported = ", ".join(sorted(allowed_extensions))
        return JsonResponse({"success": False, "error": f"Unsupported format '{invalid_ext}'. Supported: {supported}"}, status=400)

    original_size = uploaded_file.size

    with tempfile.TemporaryDirectory() as temp_dir:
        safe_input_name = _safe_name(uploaded_file.name)
        input_path = os.path.join(temp_dir, safe_input_name)
        with open(input_path, "wb") as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)

        output_path, last_error = _try_convert(input_path, temp_dir, attempts, expected_extensions)
        if not output_path:
            return JsonResponse(
                {
                    "success": False,
                    "error": "LibreOffice conversion failed. Make sure LibreOffice is installed and supports this file.",
                    "detail": last_error or "No output file was generated.",
                },
                status=500,
            )

        with open(output_path, "rb") as f:
            output_bytes = f.read()

    filename = _build_filename(uploaded_file.name, output_extension)
    converted_size = len(output_bytes)
    saved_bytes = max(0, original_size - converted_size)

    delete_pdf_after_3_minutes = _as_bool(request.data.get("delete_after_3_minutes"))
    auto_delete_seconds = None
    if output_extension == "pdf":
        auto_delete_seconds = 180 if delete_pdf_after_3_minutes else None
    else:
        auto_delete_seconds = PDF_AUTO_DELETE_SECONDS
    file_id, _ = _save_converted_output(output_bytes, output_extension, auto_delete_seconds=auto_delete_seconds)

    return JsonResponse(
        {
            "success": True,
            "file_id": file_id,
            "filename": filename,
            "original_name": uploaded_file.name,
            "original_size": original_size,
            "converted_size": converted_size,
            "saved_bytes": saved_bytes,
            "download_url": _download_url(request, file_id),
            "auto_delete_after_3_minutes": bool(auto_delete_seconds == 180 and output_extension == "pdf"),
        }
    )


@api_view(["GET", "OPTIONS"])
def download_converted_file_once(request, file_id):
    if request.method == "OPTIONS":
        return _with_cors_headers(request, HttpResponse(status=200))

    storage_dir = _output_dir()

    target_path = None
    target_ext = None
    for ext in MIME_TYPES.keys():
        candidate = os.path.join(storage_dir, f"{file_id}.{ext}")
        if os.path.exists(candidate):
            target_path = candidate
            target_ext = ext
            break

    if not target_path:
        return _with_cors_headers(
            request,
            JsonResponse({"success": False, "error": "File not found or already downloaded."}, status=404),
        )

    filename = f"converted_{file_id[:8]}.{target_ext}"

    try:
        with open(target_path, "rb") as f:
            payload = f.read()
        if not _is_pdf_path(target_path):
            os.remove(target_path)
    except Exception as exc:
        return _with_cors_headers(
            request,
            JsonResponse({"success": False, "error": f"Failed to serve file: {exc}"}, status=500),
        )

    response = HttpResponse(payload, content_type=MIME_TYPES[target_ext])
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Content-Length"] = str(len(payload))
    return _with_cors_headers(request, response)


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def convert_word_to_pdf_libreoffice(request):
    return _convert_request_file(
        request=request,
        file_key="word_file",
        allowed_extensions=WORD_EXTENSIONS,
        attempts=[("pdf:writer_pdf_Export", None), ("pdf", None)],
        expected_extensions=["pdf"],
        output_extension="pdf",
    )


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def convert_excel_to_pdf_libreoffice(request):
    return _convert_request_file(
        request=request,
        file_key="excel_file",
        allowed_extensions=EXCEL_EXTENSIONS,
        attempts=[("pdf:calc_pdf_Export", None), ("pdf", None)],
        expected_extensions=["pdf"],
        output_extension="pdf",
    )


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def convert_powerpoint_to_pdf_libreoffice(request):
    return _convert_request_file(
        request=request,
        file_key="powerpoint_file",
        allowed_extensions=POWERPOINT_EXTENSIONS,
        attempts=[("pdf:impress_pdf_Export", None), ("pdf", None)],
        expected_extensions=["pdf"],
        output_extension="pdf",
    )


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def convert_pdf_to_word_libreoffice(request):
    return _convert_request_file(
        request=request,
        file_key="pdf_file",
        allowed_extensions=PDF_EXTENSIONS,
        attempts=[("docx", "writer_pdf_import"), ("docx", None)],
        expected_extensions=["docx"],
        output_extension="docx",
    )


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def convert_pdf_to_excel_libreoffice(request):
    uploaded_file = _get_uploaded_file(request, "pdf_file")
    if not uploaded_file:
        return JsonResponse({"success": False, "error": "No file provided in 'pdf_file' or 'file'."}, status=400)

    invalid_ext = _validate_extension(uploaded_file, PDF_EXTENSIONS)
    if invalid_ext:
        return JsonResponse({"success": False, "error": "Unsupported format. Expected .pdf"}, status=400)

    original_size = uploaded_file.size
    input_name = _safe_name(uploaded_file.name)
    pdf_bytes = uploaded_file.read()

    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = os.path.join(temp_dir, input_name)
        with open(input_path, "wb") as f:
            f.write(pdf_bytes)

        output_path, last_error = _try_convert(
            input_path,
            temp_dir,
            [("xlsx", "calc_pdf_import"), ("xlsx", None), ("xlsx", "draw_pdf_import")],
            ["xlsx"],
        )

        if output_path and os.path.exists(output_path):
            with open(output_path, "rb") as f:
                output_bytes = f.read()
        else:
            output_bytes, fallback_error = _fallback_pdf_to_excel_bytes(pdf_bytes)
            if not output_bytes:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "LibreOffice and fallback extraction failed.",
                        "detail": fallback_error or last_error or "No output generated.",
                    },
                    status=400,
                )

    converted_size = len(output_bytes)
    saved_bytes = max(0, original_size - converted_size)
    file_id, _ = _save_converted_output(output_bytes, "xlsx")

    return JsonResponse(
        {
            "success": True,
            "file_id": file_id,
            "filename": _build_filename(uploaded_file.name, "xlsx"),
            "original_name": uploaded_file.name,
            "original_size": original_size,
            "converted_size": converted_size,
            "saved_bytes": saved_bytes,
            "download_url": _download_url(request, file_id),
        }
    )


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def convert_pdf_to_powerpoint_libreoffice(request):
    return _convert_request_file(
        request=request,
        file_key="pdf_file",
        allowed_extensions=PDF_EXTENSIONS,
        attempts=[("pptx", "impress_pdf_import"), ("pptx", None)],
        expected_extensions=["pptx"],
        output_extension="pptx",
    )
