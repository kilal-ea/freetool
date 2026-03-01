import os
import shutil
import subprocess
import sys

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


def find_soffice_path():
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            r"C:\Program Files\LibreOffice 26\program\soffice.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        ]
    else:
        candidates = [
            "soffice", 
            "libreoffice", 
            "/opt/libreoffice25.8/program/soffice",
            "/usr/bin/soffice",
            "/usr/local/bin/soffice",
        ]

    for candidate in candidates:
        if os.path.isabs(candidate):
            if os.path.exists(candidate):
                return candidate
        else:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved

    return None


def get_libreoffice_version(soffice_path):
    try:
        # استخدم الملف التنفيذي المباشر
        soffice_bin = soffice_path
        if soffice_path and 'soffice' in soffice_path and not soffice_path.endswith('.bin'):
            bin_path = soffice_path + '.bin'
            if os.path.exists(bin_path):
                soffice_bin = bin_path
        
        profile_dir = "/tmp/libreoffice-profile"
        if not os.path.exists(profile_dir):
            os.makedirs(profile_dir, mode=0o777, exist_ok=True)
        
        # PATH كامل
        env = os.environ.copy()
        env["HOME"] = "/home/www-data"
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        env["TMP"] = "/tmp"
        env["TEMP"] = "/tmp"
        env["TMPDIR"] = "/tmp"
        
        args = [
            soffice_bin,
            "-env:UserInstallation=file:///tmp/libreoffice-profile",
            "--version"
        ]
        
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        
        if result.returncode == 0:
            output = (result.stdout or result.stderr or "").strip()
            first_line = output.splitlines()[0] if output else None
            return first_line
        else:
            print(f"[LibreOffice] Version error: {result.stderr}", file=sys.stderr)
            return None
            
    except Exception as e:
        print(f"[LibreOffice] Version exception: {e}", file=sys.stderr)
        return None


def run_convert(input_path, output_dir, convert_to, infilter=None, timeout=120):
    soffice_path = find_soffice_path()
    if not soffice_path:
        return None, "LibreOffice not found"

    # استخدم الملف التنفيذي المباشر (.bin) بدلاً من السكريبت
    soffice_bin = soffice_path
    if soffice_path and 'soffice' in soffice_path and not soffice_path.endswith('.bin'):
        bin_path = soffice_path + '.bin'
        if os.path.exists(bin_path):
            soffice_bin = bin_path
            print(f"[LibreOffice] Using binary: {soffice_bin}", file=sys.stderr)
        else:
            print(f"[LibreOffice] Binary not found, using: {soffice_path}", file=sys.stderr)

    # التأكد من وجود مجلد البروفايل
    profile_dir = "/tmp/libreoffice-profile"
    if not os.path.exists(profile_dir):
        os.makedirs(profile_dir, mode=0o777, exist_ok=True)

    # تجربة استخدام المسار الكامل للأوامر
    env = os.environ.copy()
    env["HOME"] = "/home/www-data"
    env["PATH"] = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    env["TMP"] = "/tmp"
    env["TEMP"] = "/tmp"
    env["TMPDIR"] = "/tmp"
    
    # إضافة مسارات إضافية
    env["LD_LIBRARY_PATH"] = "/opt/libreoffice25.8/program:/usr/lib:/usr/lib/x86_64-linux-gnu"

    args = [
        soffice_bin,
        "--headless",
        "--invisible",
        "--nologo",
        "--nodefault",
        "--nofirststartwizard",
        "--nolockcheck",
        "--norestore",
        "-env:UserInstallation=file:///tmp/libreoffice-profile",
        "--convert-to",
        convert_to,
        input_path,
        "--outdir",
        output_dir,
    ]

    if infilter:
        args.append(f"--infilter={infilter}")

    try:
        print(f"[LibreOffice] Running: {' '.join(args)}", file=sys.stderr)
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            print(f"[LibreOffice] Error: {error_msg}", file=sys.stderr)
            return None, error_msg
            
    except subprocess.TimeoutExpired:
        print(f"[LibreOffice] Timeout after {timeout}s", file=sys.stderr)
        return None, "LibreOffice conversion timed out"
    except Exception as exc:
        print(f"[LibreOffice] Exception: {exc}", file=sys.stderr)
        return None, f"LibreOffice conversion error: {exc}"

    return soffice_path, None


def find_converted_file(output_dir, base_name, extensions):
    for ext in extensions:
        candidate = os.path.join(output_dir, f"{base_name}.{ext}")
        if os.path.exists(candidate):
            return candidate

    # Fallback: scan output dir for matching extension
    lower_extensions = {ext.lower() for ext in extensions}
    for entry in os.listdir(output_dir):
        name, ext = os.path.splitext(entry)
        if name == base_name and ext.lstrip(".").lower() in lower_extensions:
            return os.path.join(output_dir, entry)

    return None


def check_libreoffice(request):
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    soffice_path = find_soffice_path()
    if not soffice_path:
        return JsonResponse(
            {"available": False, "error": "LibreOffice not found"},
            status=200,
        )

    version = get_libreoffice_version(soffice_path)
    return JsonResponse(
        {
            "available": True,
            "path": soffice_path,
            "version": version,
        },
        status=200,
    )
